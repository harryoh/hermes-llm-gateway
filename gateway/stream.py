from __future__ import annotations

import json
import time
import uuid
from typing import AsyncIterator


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _chunk(
    request_id: str, created: int, model: str, delta: dict, finish_reason: str | None = None
) -> dict:
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


async def text_to_sse_stream(text: str, model: str) -> AsyncIterator[bytes]:
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    yield _sse(_chunk(request_id, created, model, {"role": "assistant"}))
    if text:
        yield _sse(_chunk(request_id, created, model, {"content": text}))
    yield _sse(_chunk(request_id, created, model, {}, finish_reason="stop"))
    yield b"data: [DONE]\n\n"
