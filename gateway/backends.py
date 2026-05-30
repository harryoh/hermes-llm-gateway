from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from gateway.config import Settings
from gateway.models import BackendResult, ChatCompletionRequest, ChatMessage
from gateway.state import GatewayState

RATE_LIMIT_MARKERS = ("usage limit", "5-hour limit", "rate limit", "too many requests")
AUTH_MARKERS = ("not logged in", "login", "auth", "unauthorized", "forbidden")


def serialize_messages(messages: list[ChatMessage]) -> str:
    blocks: list[str] = []
    for message in messages:
        content = message.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        blocks.append(f"[{message.role}]\n{content}")
    return "\n\n".join(blocks) + "\n\nRespond to the last user message."


async def call_claude(
    req: ChatCompletionRequest,
    settings: Settings,
    state: GatewayState,
) -> BackendResult:
    acct = state.active_acct()
    if state.in_cooldown(acct):
        return BackendResult(
            ok=False,
            backend="claude",
            failure_code="COOLDOWN",
            detail=f"acct={acct}",
            acct=acct,
        )

    account_dir = resolve_account_dir(settings.claude_account_base, acct)
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(account_dir),
    }
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    prompt = serialize_messages(req.messages)

    def run_locked() -> tuple[int, bytes, bytes]:
        async def run_proc() -> tuple[int, bytes, bytes]:
            proc = await asyncio.create_subprocess_exec(
                settings.claude_bin,
                "-p",
                "--output-format",
                "json",
                "--no-session-persistence",
                "--tools",
                "",
                cwd=settings.work_dir,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(prompt.encode("utf-8")),
                    timeout=settings.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return 124, b"", b"timeout"
            return proc.returncode or 0, out, err

        return asyncio.run(run_proc())

    try:
        returncode, out, err = await asyncio.to_thread(_run_with_lock, state, run_locked)
    except (FileNotFoundError, OSError) as exc:
        return BackendResult(
            ok=False,
            backend="claude",
            failure_code="ERROR",
            detail=f"failed to spawn {settings.claude_bin}: {exc}"[:500],
            acct=acct,
        )
    stdout = out.decode("utf-8", "ignore")
    stderr = err.decode("utf-8", "ignore")

    text = ""
    is_error = returncode != 0
    try:
        data = json.loads(stdout)
        text = str(data.get("result") or "").strip()
        is_error = bool(data.get("is_error")) or is_error
    except json.JSONDecodeError:
        text = stdout.strip()

    if not is_error and text:
        return BackendResult(ok=True, backend="claude", text=text, acct=acct)

    detail = " ".join(part for part in [text, stderr] if part).strip()
    lower = detail.lower()
    if any(marker in lower for marker in RATE_LIMIT_MARKERS):
        state.mark_cooldown(acct)
        return BackendResult(
            ok=False,
            backend="claude",
            failure_code="RATE_LIMIT",
            detail=detail[:500],
            acct=acct,
        )
    if any(marker in lower for marker in AUTH_MARKERS):
        return BackendResult(
            ok=False,
            backend="claude",
            failure_code="AUTH",
            detail=detail[:500],
            acct=acct,
        )
    if returncode == 124:
        return BackendResult(
            ok=False,
            backend="claude",
            failure_code="TIMEOUT",
            detail=detail[:500],
            acct=acct,
        )
    return BackendResult(
        ok=False,
        backend="claude",
        failure_code="ERROR",
        detail=detail[:500],
        acct=acct,
    )


async def call_codex(
    req: ChatCompletionRequest,
    settings: Settings,
    state: GatewayState,
) -> BackendResult:
    acct = state.active_acct()
    if state.in_cooldown(f"codex:{acct}"):
        return BackendResult(
            ok=False,
            backend="codex",
            failure_code="COOLDOWN",
            detail=f"acct={acct}",
            acct=acct,
        )

    account_dir = resolve_account_dir(settings.codex_account_base, acct)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    output_file = settings.work_dir / f"codex-last-{uuid.uuid4().hex}.txt"
    env = {
        **os.environ,
        "CODEX_HOME": str(account_dir),
    }
    prompt = serialize_messages(req.messages)

    def run_locked() -> tuple[int, bytes, bytes]:
        async def run_proc() -> tuple[int, bytes, bytes]:
            proc = await asyncio.create_subprocess_exec(
                settings.codex_bin,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ignore-rules",
                "--color",
                "never",
                "--cd",
                str(settings.work_dir),
                "--output-last-message",
                str(output_file),
                "-",
                cwd=settings.work_dir,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(prompt.encode("utf-8")),
                    timeout=settings.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return 124, b"", b"timeout"
            return proc.returncode or 0, out, err

        return asyncio.run(run_proc())

    try:
        try:
            returncode, out, err = await asyncio.to_thread(_run_with_lock, state, run_locked)
        except (FileNotFoundError, OSError) as exc:
            return BackendResult(
                ok=False,
                backend="codex",
                failure_code="ERROR",
                detail=f"failed to spawn {settings.codex_bin}: {exc}"[:500],
                acct=acct,
            )
        stdout = out.decode("utf-8", "ignore")
        stderr = err.decode("utf-8", "ignore")
        text = ""
        if output_file.exists():
            text = output_file.read_text(encoding="utf-8").strip()
        if returncode == 0 and text:
            return BackendResult(ok=True, backend="codex", text=text, acct=acct)

        detection_detail = " ".join(part for part in [text, stdout, stderr] if part).strip()
        log_detail = stderr.strip() or f"codex exited with code {returncode} without last message"
        lower = detection_detail.lower()
        if any(marker in lower for marker in RATE_LIMIT_MARKERS):
            state.mark_cooldown(f"codex:{acct}")
            return BackendResult(
                ok=False,
                backend="codex",
                failure_code="RATE_LIMIT",
                detail=log_detail[:500],
                acct=acct,
            )
        if any(marker in lower for marker in AUTH_MARKERS):
            return BackendResult(
                ok=False,
                backend="codex",
                failure_code="AUTH",
                detail=log_detail[:500],
                acct=acct,
            )
        if returncode == 124:
            return BackendResult(
                ok=False,
                backend="codex",
                failure_code="TIMEOUT",
                detail=log_detail[:500],
                acct=acct,
            )
        return BackendResult(
            ok=False,
            backend="codex",
            failure_code="ERROR",
            detail=log_detail[:500],
            acct=acct,
        )
    finally:
        output_file.unlink(missing_ok=True)


def _run_with_lock(state: GatewayState, fn):
    with state.backend_lock():
        return fn()


def resolve_account_dir(base: Path, acct: str) -> Path:
    candidate = base / acct
    if candidate.exists():
        return candidate
    return base
