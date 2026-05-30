from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from gateway.app import app, unsupported_fields
from gateway.models import BackendResult, ChatCompletionRequest, ChatMessage


def test_stream_true_is_not_in_unsupported_fields() -> None:
    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    assert "stream" not in unsupported_fields(req)


def test_tools_still_rejected_as_unsupported() -> None:
    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "f"}}],
    )
    assert "tools" in unsupported_fields(req)


def _decode_sse(body: bytes) -> tuple[list[dict], bool]:
    payloads: list[dict] = []
    saw_done = False
    for raw in body.split(b"\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        assert raw.startswith(b"data: ")
        data = raw[len(b"data: ") :]
        if data == b"[DONE]":
            saw_done = True
            continue
        payloads.append(json.loads(data.decode("utf-8")))
    return payloads, saw_done


@pytest.mark.parametrize(
    "requested_model,resolved_model",
    [("auto", "claude-primary"), ("claude-primary", "claude-primary")],
)
def test_streaming_claude_path_returns_sse_chunks(
    requested_model: str, resolved_model: str
) -> None:
    fake_claude = AsyncMock(
        return_value=BackendResult(ok=True, backend="claude", text="pong", acct="acct1")
    )
    with patch("gateway.app.call_claude", fake_claude):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": requested_model,
                "messages": [{"role": "user", "content": "Reply: pong"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads, saw_done = _decode_sse(response.content)
    assert saw_done
    assert all(p["model"] == resolved_model for p in payloads)
    content = "".join(
        p["choices"][0]["delta"].get("content", "") for p in payloads
    )
    assert content == "pong"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"


def test_streaming_codex_direct_returns_sse_chunks() -> None:
    fake_codex = AsyncMock(
        return_value=BackendResult(ok=True, backend="codex", text="pong", acct="acct1")
    )
    with patch("gateway.app.call_codex", fake_codex):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "codex-primary",
                "messages": [{"role": "user", "content": "Reply: pong"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads, saw_done = _decode_sse(response.content)
    assert saw_done
    assert all(p["model"] == "codex-primary" for p in payloads)


def test_streaming_falls_back_to_codex_on_claude_failure() -> None:
    fake_claude = AsyncMock(
        return_value=BackendResult(
            ok=False,
            backend="claude",
            failure_code="AUTH",
            detail="Not logged in",
            acct="acct1",
        )
    )
    fake_codex = AsyncMock(
        return_value=BackendResult(ok=True, backend="codex", text="pong", acct="acct1")
    )
    with patch("gateway.app.call_claude", fake_claude), patch(
        "gateway.app.call_codex", fake_codex
    ):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads, _ = _decode_sse(response.content)
    assert all(p["model"] == "codex-primary" for p in payloads)
    fake_claude.assert_called_once()
    fake_codex.assert_called_once()


def test_streaming_returns_503_when_both_backends_fail() -> None:
    fake_claude = AsyncMock(
        return_value=BackendResult(
            ok=False, backend="claude", failure_code="ERROR", detail="x", acct="acct1"
        )
    )
    fake_codex = AsyncMock(
        return_value=BackendResult(
            ok=False, backend="codex", failure_code="ERROR", detail="x", acct="acct1"
        )
    )
    with patch("gateway.app.call_claude", fake_claude), patch(
        "gateway.app.call_codex", fake_codex
    ):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["failure_code"] == "ERROR"
    assert body["detail"]["claude_failure_code"] == "ERROR"
