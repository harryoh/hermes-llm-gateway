from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from gateway.app import app, silently_stripped_fields, unsupported_fields
from gateway.models import BackendResult, ChatCompletionRequest, ChatMessage


def _req(**overrides) -> ChatCompletionRequest:
    base = {
        "model": "auto",
        "messages": [ChatMessage(role="user", content="hi")],
    }
    base.update(overrides)
    return ChatCompletionRequest(**base)


def test_tools_no_longer_in_unsupported_fields() -> None:
    req = _req(tools=[{"type": "function", "function": {"name": "f"}}])
    assert "tools" not in unsupported_fields(req)


def test_tool_choice_no_longer_in_unsupported_fields() -> None:
    req = _req(tool_choice="auto")
    assert "tool_choice" not in unsupported_fields(req)


def test_response_format_still_unsupported() -> None:
    req = _req(response_format={"type": "json_object"})
    assert "response_format" in unsupported_fields(req)


def test_silently_stripped_fields_lists_tools() -> None:
    req = _req(tools=[{"type": "function", "function": {"name": "f"}}])
    assert silently_stripped_fields(req) == ["tools"]


def test_silently_stripped_fields_lists_tool_choice() -> None:
    req = _req(tool_choice="auto")
    assert silently_stripped_fields(req) == ["tool_choice"]


def test_silently_stripped_fields_lists_both_in_order() -> None:
    req = _req(
        tools=[{"type": "function", "function": {"name": "f"}}],
        tool_choice="auto",
    )
    assert silently_stripped_fields(req) == ["tools", "tool_choice"]


def test_silently_stripped_fields_empty_when_neither_set() -> None:
    assert silently_stripped_fields(_req()) == []


def test_post_with_tools_returns_200_and_logs_silently_stripped() -> None:
    fake_claude = AsyncMock(
        return_value=BackendResult(ok=True, backend="claude", text="pong", acct="acct1")
    )
    fake_log = MagicMock()
    with patch("gateway.app.call_claude", fake_claude), patch(
        "gateway.app.state.log_event", fake_log
    ):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function", "function": {"name": "do_thing"}}],
                "tool_choice": "auto",
            },
        )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "pong"

    success_calls = [
        call
        for call in fake_log.call_args_list
        if call.kwargs.get("backend") == "claude"
        and call.kwargs.get("resolved_model") == "claude-primary"
    ]
    assert success_calls, "expected one successful claude log entry"
    kwargs = success_calls[-1].kwargs
    assert kwargs.get("silently_stripped") == ["tools", "tool_choice"]


def test_post_with_response_format_still_400() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {"type": "json_object"},
        },
    )
    assert response.status_code == 400
    assert "response_format" in response.json()["detail"]
