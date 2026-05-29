from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any]


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    stream: bool = False
    tools: list[Any] | None = None
    tool_choice: Any | None = None
    response_format: Any | None = None

    model_config = {"extra": "allow"}


class BackendResult(BaseModel):
    ok: bool
    backend: Literal["claude", "codex", "dgx"]
    text: str = ""
    failure_code: str | None = None
    detail: str = ""
    acct: str | None = None


class OpenAIModel(BaseModel):
    id: str
    object: str = "model"


class SwitchAccountRequest(BaseModel):
    acct: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
