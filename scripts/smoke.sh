#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
MODEL_PROMPT='Reply with exactly pong'

say() {
  printf '\n== %s ==\n' "$1"
}

json_post() {
  local path="$1"
  local body="$2"
  curl -fsS \
    -H 'Content-Type: application/json' \
    -X POST \
    "$BASE_URL$path" \
    -d "$body"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'Expected output to contain: %s\nActual output:\n%s\n' "$needle" "$haystack" >&2
    exit 1
  fi
}

say "health"
health="$(curl -fsS "$BASE_URL/health")"
printf '%s\n' "$health"
assert_contains "$health" '"status":"ok"'

say "models"
models="$(curl -fsS "$BASE_URL/v1/models")"
printf '%s\n' "$models"
assert_contains "$models" '"auto"'
assert_contains "$models" '"claude-primary"'
assert_contains "$models" '"codex-primary"'

say "admin switch"
switch="$(json_post /admin/switch '{"acct":"acct1"}')"
printf '%s\n' "$switch"
assert_contains "$switch" '"active_acct":"acct1"'

say "claude-primary"
claude="$(json_post /v1/chat/completions "{\"model\":\"claude-primary\",\"messages\":[{\"role\":\"user\",\"content\":\"$MODEL_PROMPT\"}]}")"
printf '%s\n' "$claude"
assert_contains "$claude" '"model":"claude-primary"'
assert_contains "$claude" '"content":"pong"'

say "codex-primary"
codex="$(json_post /v1/chat/completions "{\"model\":\"codex-primary\",\"messages\":[{\"role\":\"user\",\"content\":\"$MODEL_PROMPT\"}]}")"
printf '%s\n' "$codex"
assert_contains "$codex" '"model":"codex-primary"'
assert_contains "$codex" '"content":"pong"'

say "auto"
auto="$(json_post /v1/chat/completions "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"$MODEL_PROMPT\"}]}")"
printf '%s\n' "$auto"
assert_contains "$auto" '"content":"pong"'

say "auto fallback to Codex via temporary Claude cooldown"
docker compose exec -T gateway sh -lc 'python - <<'"'"'PY'"'"'
import json
from datetime import datetime, timedelta, timezone
p = "/state/cooldowns.json"
try:
    data = json.load(open(p))
except Exception:
    data = {}
data["acct1"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
open(p, "w").write(json.dumps(data))
PY'

fallback="$(json_post /v1/chat/completions "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"$MODEL_PROMPT\"}]}")"
printf '%s\n' "$fallback"
assert_contains "$fallback" '"model":"codex-primary"'
assert_contains "$fallback" '"content":"pong"'

docker compose exec -T gateway sh -lc 'rm -f /state/cooldowns.json'

say "unsupported stream"
stream_status="$(
  curl -sS -o /tmp/hermes-gw-stream.out -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/v1/chat/completions" \
    -d '{"model":"auto","stream":true,"messages":[{"role":"user","content":"ping"}]}'
)"
cat /tmp/hermes-gw-stream.out
printf '\n'
if [[ "$stream_status" != "400" ]]; then
  printf 'Expected stream request to return 400, got %s\n' "$stream_status" >&2
  exit 1
fi

say "ok"

