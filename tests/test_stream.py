from __future__ import annotations

import json

import pytest

from gateway.stream import text_to_sse_stream


def parse_sse_lines(chunks: list[bytes]) -> tuple[list[dict], bool]:
    """Decode SSE byte chunks into payloads. Returns (payloads, saw_done)."""
    payloads: list[dict] = []
    saw_done = False
    for chunk in chunks:
        assert chunk.endswith(b"\n\n"), f"chunk missing terminator: {chunk!r}"
        body = chunk[: -len(b"\n\n")]
        assert body.startswith(b"data: "), f"chunk missing data prefix: {chunk!r}"
        data = body[len(b"data: ") :]
        if data == b"[DONE]":
            saw_done = True
            continue
        payloads.append(json.loads(data.decode("utf-8")))
    return payloads, saw_done


@pytest.mark.asyncio
async def test_text_to_sse_stream_emits_role_content_finish_done() -> None:
    chunks = [chunk async for chunk in text_to_sse_stream("pong", "claude-primary")]
    payloads, saw_done = parse_sse_lines(chunks)

    assert saw_done is True
    assert len(payloads) >= 3

    for p in payloads:
        assert p["object"] == "chat.completion.chunk"
        assert p["model"] == "claude-primary"
        assert isinstance(p["created"], int)
        assert p["id"].startswith("chatcmpl-")
        assert len(p["choices"]) == 1
        assert p["choices"][0]["index"] == 0

    assert payloads[0]["choices"][0]["delta"].get("role") == "assistant"

    content_pieces = [
        p["choices"][0]["delta"]["content"]
        for p in payloads
        if "content" in p["choices"][0]["delta"]
    ]
    assert "".join(content_pieces) == "pong"

    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1]["choices"][0]["delta"] == {}


@pytest.mark.asyncio
async def test_text_to_sse_stream_consistent_id_and_created_across_chunks() -> None:
    chunks = [chunk async for chunk in text_to_sse_stream("abc", "codex-primary")]
    payloads, _ = parse_sse_lines(chunks)
    ids = {p["id"] for p in payloads}
    createds = {p["created"] for p in payloads}
    assert len(ids) == 1
    assert len(createds) == 1


@pytest.mark.asyncio
async def test_text_to_sse_stream_empty_text_still_emits_finish_and_done() -> None:
    chunks = [chunk async for chunk in text_to_sse_stream("", "claude-primary")]
    payloads, saw_done = parse_sse_lines(chunks)
    assert saw_done is True
    assert any("role" in p["choices"][0]["delta"] for p in payloads)
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
