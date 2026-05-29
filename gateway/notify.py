from __future__ import annotations

import contextlib

import httpx

from gateway.config import Settings


async def notify_telegram(settings: Settings, text: str) -> None:
    if not (settings.tg_bot_token and settings.tg_chat_id):
        return
    with contextlib.suppress(Exception):
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage",
                json={"chat_id": settings.tg_chat_id, "text": text},
            )

