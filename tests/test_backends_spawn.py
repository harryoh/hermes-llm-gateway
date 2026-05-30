from __future__ import annotations

from pathlib import Path

import pytest

from gateway.backends import call_claude, call_codex
from gateway.config import Settings
from gateway.models import ChatCompletionRequest, ChatMessage
from gateway.state import GatewayState


def make_settings(tmp_path: Path, claude_bin: str, codex_bin: str) -> Settings:
    return Settings(
        gateway_api_key=None,
        allow_insecure_dev=True,
        state_dir=tmp_path / "state",
        work_dir=tmp_path / "work",
        claude_bin=claude_bin,
        codex_bin=codex_bin,
        claude_account_base=tmp_path / "claude-accounts",
        codex_account_base=tmp_path / "codex-accounts",
        active_claude_acct="acct1",
        timeout_seconds=5,
        cooldown_hours=5,
        tg_bot_token=None,
        tg_chat_id=None,
    )


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="hi")],
    )


@pytest.mark.asyncio
async def test_call_claude_returns_error_when_binary_missing(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, claude_bin="/nonexistent/claude-xyz", codex_bin="codex")
    state = GatewayState(settings.state_dir, settings.active_claude_acct, settings.cooldown_hours)

    result = await call_claude(make_request(), settings, state)

    assert result.ok is False
    assert result.backend == "claude"
    assert result.failure_code == "ERROR"
    assert result.acct == "acct1"
    assert "/nonexistent/claude-xyz" in result.detail or "No such file" in result.detail


@pytest.mark.asyncio
async def test_call_codex_returns_error_when_binary_missing(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, claude_bin="claude", codex_bin="/nonexistent/codex-xyz")
    state = GatewayState(settings.state_dir, settings.active_claude_acct, settings.cooldown_hours)

    result = await call_codex(make_request(), settings, state)

    assert result.ok is False
    assert result.backend == "codex"
    assert result.failure_code == "ERROR"
    assert result.acct == "acct1"
    assert "/nonexistent/codex-xyz" in result.detail or "No such file" in result.detail
