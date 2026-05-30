from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from gateway.backends import call_claude, call_codex, serialize_messages
from gateway.config import Settings, load_settings
from gateway.models import ChatCompletionRequest, SwitchAccountRequest
from gateway.notify import notify_telegram
from gateway.state import GatewayState
from gateway.stream import text_to_sse_stream

settings: Settings = load_settings()
state = GatewayState(settings.state_dir, settings.active_claude_acct, settings.cooldown_hours)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.gateway_api_key and not settings.allow_insecure_dev:
        raise RuntimeError("GATEWAY_API_KEY is required unless HERMES_ALLOW_INSECURE_DEV=1")
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Hermes LLM Gateway", lifespan=lifespan)


def check_api_key(x_api_key: str | None) -> None:
    if settings.allow_insecure_dev and not settings.gateway_api_key:
        return
    if not settings.gateway_api_key:
        raise HTTPException(status_code=500, detail="gateway api key is not configured")
    if x_api_key != settings.gateway_api_key:
        raise HTTPException(status_code=401, detail="invalid api key")


def unsupported_fields(req: ChatCompletionRequest) -> list[str]:
    fields: list[str] = []
    if req.tools is not None:
        fields.append("tools")
    if req.tool_choice is not None:
        fields.append("tool_choice")
    if req.response_format is not None:
        fields.append("response_format")
    return fields


def openai_response(model: str, text: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def build_response(model: str, text: str, stream: bool):
    if stream:
        return StreamingResponse(
            text_to_sse_stream(text, model),
            media_type="text/event-stream",
        )
    return openai_response(model, text)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/health")
async def admin_health(x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    return {
        "status": "ok",
        "active_acct": state.active_acct(),
        "cooldowns": state.cooldowns(),
        "state_dir": str(settings.state_dir),
        "work_dir": str(settings.work_dir),
    }


@app.post("/admin/switch")
async def admin_switch(req: SwitchAccountRequest, x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    state.set_active_acct(req.acct)
    state.log_event(
        request_id=uuid.uuid4().hex,
        backend=None,
        event="switch_account",
        acct=req.acct,
    )
    return {"status": "ok", "active_acct": state.active_acct()}


@app.get("/v1/models")
async def models(x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    return {
        "object": "list",
        "data": [
            {"id": "auto", "object": "model"},
            {"id": "claude-primary", "object": "model"},
            {"id": "codex-primary", "object": "model"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat(
    req: ChatCompletionRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    check_api_key(x_api_key)
    request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
    t0 = time.monotonic()
    unsupported = unsupported_fields(req)
    prompt = serialize_messages(req.messages)

    if req.model not in {"auto", "claude-primary", "codex-primary"}:
        raise HTTPException(status_code=400, detail=f"unsupported model for Phase 1: {req.model}")
    if unsupported:
        state.log_event(
            request_id=request_id,
            backend=None,
            requested_model=req.model,
            failure_code="UNSUPPORTED_FIELDS",
            unsupported_fields=unsupported,
            prompt_chars=len(prompt),
        )
        raise HTTPException(
            status_code=400,
            detail=f"unsupported request fields for Phase 1: {', '.join(unsupported)}",
        )

    if req.model == "codex-primary":
        result = await call_codex(req, settings, state)
        duration_ms = int((time.monotonic() - t0) * 1000)
        if result.ok:
            state.log_event(
                request_id=request_id,
                backend="codex",
                requested_model=req.model,
                resolved_model="codex-primary",
                acct=result.acct,
                duration_ms=duration_ms,
                prompt_chars=len(prompt),
                output_chars=len(result.text),
                unsupported_fields=[],
            )
            return build_response("codex-primary", result.text, req.stream)
        state.log_event(
            request_id=request_id,
            backend="codex",
            requested_model=req.model,
            resolved_model=None,
            acct=result.acct,
            duration_ms=duration_ms,
            prompt_chars=len(prompt),
            output_chars=0,
            failure_code=result.failure_code,
            detail=result.detail,
            unsupported_fields=[],
        )
        raise HTTPException(
            status_code=503,
            detail={"message": "codex backend failed", "failure_code": result.failure_code},
        )

    result = await call_claude(req, settings, state)
    duration_ms = int((time.monotonic() - t0) * 1000)

    if result.ok:
        state.log_event(
            request_id=request_id,
            backend="claude",
            requested_model=req.model,
            resolved_model="claude-primary",
            acct=result.acct,
            duration_ms=duration_ms,
            prompt_chars=len(prompt),
            output_chars=len(result.text),
            unsupported_fields=[],
        )
        return build_response("claude-primary", result.text, req.stream)

    state.log_event(
        request_id=request_id,
        backend="claude",
        requested_model=req.model,
        resolved_model=None,
        acct=result.acct,
        duration_ms=duration_ms,
        prompt_chars=len(prompt),
        output_chars=0,
        failure_code=result.failure_code,
        detail=result.detail,
        unsupported_fields=[],
    )
    if result.failure_code in {"RATE_LIMIT", "AUTH", "TIMEOUT", "ERROR"}:
        key = f"claude:{result.acct}:{result.failure_code}"
        if state.should_notify_once(key):
            await notify_telegram(
                settings,
                f"Claude backend failed ({result.failure_code}) for {result.acct}. "
                "Trying Codex fallback.",
            )

    codex_t0 = time.monotonic()
    codex_result = await call_codex(req, settings, state)
    codex_duration_ms = int((time.monotonic() - codex_t0) * 1000)
    if codex_result.ok:
        state.log_event(
            request_id=request_id,
            backend="codex",
            requested_model=req.model,
            resolved_model="codex-primary",
            acct=codex_result.acct,
            duration_ms=codex_duration_ms,
            prompt_chars=len(prompt),
            output_chars=len(codex_result.text),
            fallback_from="claude",
            fallback_reason=result.failure_code,
            unsupported_fields=[],
        )
        return build_response("codex-primary", codex_result.text, req.stream)

    state.log_event(
        request_id=request_id,
        backend="codex",
        requested_model=req.model,
        resolved_model=None,
        acct=codex_result.acct,
        duration_ms=codex_duration_ms,
        prompt_chars=len(prompt),
        output_chars=0,
        fallback_from="claude",
        fallback_reason=result.failure_code,
        failure_code=codex_result.failure_code,
        detail=codex_result.detail,
        unsupported_fields=[],
    )
    if codex_result.failure_code in {"RATE_LIMIT", "AUTH", "TIMEOUT", "ERROR"}:
        key = f"codex:{codex_result.acct}:{codex_result.failure_code}"
        if state.should_notify_once(key):
            await notify_telegram(
                settings,
                f"Codex backend failed ({codex_result.failure_code}) for {codex_result.acct}. "
                "No DGX fallback is active yet.",
            )

    raise HTTPException(
        status_code=503,
        detail={
            "message": "claude and codex backends failed; no DGX fallback is active yet",
            "failure_code": codex_result.failure_code,
            "claude_failure_code": result.failure_code,
        },
    )
