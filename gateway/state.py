from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


class GatewayState:
    def __init__(self, state_dir: Path, default_acct: str, cooldown_hours: int) -> None:
        self.state_dir = state_dir
        self.default_acct = default_acct
        self.cooldown_hours = cooldown_hours
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.active_acct_file = self.state_dir / "active_acct"
        self.cooldowns_file = self.state_dir / "cooldowns.json"
        self.log_file = self.state_dir / "gateway.jsonl"
        self.notify_state_file = self.state_dir / "notify_state.json"
        self.lock_file = self.state_dir / "gateway.lock"

    def active_acct(self) -> str:
        try:
            value = self.active_acct_file.read_text(encoding="utf-8").strip()
            return value or self.default_acct
        except FileNotFoundError:
            return self.default_acct

    def set_active_acct(self, acct: str) -> None:
        atomic_write_text(self.active_acct_file, acct + "\n")

    def load_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

    def save_json(self, path: Path, data: dict) -> None:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def cooldowns(self) -> dict:
        return self.load_json(self.cooldowns_file)

    def in_cooldown(self, acct: str) -> bool:
        value = self.cooldowns().get(acct)
        if not value:
            return False
        try:
            return datetime.fromisoformat(value) > datetime.now(timezone.utc)
        except ValueError:
            return False

    def mark_cooldown(self, acct: str) -> str:
        until = datetime.now(timezone.utc) + timedelta(hours=self.cooldown_hours)
        data = self.cooldowns()
        data[acct] = until.isoformat()
        self.save_json(self.cooldowns_file, data)
        return until.isoformat()

    def log_event(self, **entry: object) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def should_notify_once(self, key: str) -> bool:
        data = self.load_json(self.notify_state_file)
        if data.get(key):
            return False
        data[key] = datetime.now(timezone.utc).isoformat()
        self.save_json(self.notify_state_file, data)
        return True

    @contextlib.contextmanager
    def backend_lock(self) -> Iterator[None]:
        with self.lock_file.open("a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8")
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp.name)
        raise

