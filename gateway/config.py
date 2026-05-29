from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    gateway_api_key: str | None
    allow_insecure_dev: bool
    state_dir: Path
    work_dir: Path
    claude_bin: str
    codex_bin: str
    claude_account_base: Path
    codex_account_base: Path
    active_claude_acct: str
    timeout_seconds: int
    cooldown_hours: int
    tg_bot_token: str | None
    tg_chat_id: str | None


def load_settings() -> Settings:
    state_dir = Path(os.environ.get("HERMES_STATE_DIR", "~/.hermes-gw")).expanduser()
    work_dir = Path(os.environ.get("HERMES_WORK_DIR", "/tmp/hermes-gw-work")).expanduser()

    return Settings(
        gateway_api_key=os.environ.get("GATEWAY_API_KEY"),
        allow_insecure_dev=os.environ.get("HERMES_ALLOW_INSECURE_DEV") == "1",
        state_dir=state_dir,
        work_dir=work_dir,
        claude_bin=os.environ.get("CLAUDE_BIN", "claude"),
        codex_bin=os.environ.get("CODEX_BIN", "codex"),
        claude_account_base=Path(
            os.environ.get("CLAUDE_ACCOUNT_BASE", "~/.claude-accounts")
        ).expanduser(),
        codex_account_base=Path(os.environ.get("CODEX_ACCOUNT_BASE", "~/.codex-accounts")).expanduser(),
        active_claude_acct=os.environ.get("ACTIVE_CLAUDE_ACCT", "acct1"),
        timeout_seconds=int(os.environ.get("BACKEND_TIMEOUT_SECONDS", "300")),
        cooldown_hours=int(os.environ.get("BACKEND_COOLDOWN_HOURS", "5")),
        tg_bot_token=os.environ.get("TG_BOT_TOKEN"),
        tg_chat_id=os.environ.get("TG_CHAT_ID"),
    )

