# Hermes LLM Gateway

OpenAI-compatible local Gateway for Hermes.

Current local flow:

```text
Hermes host process
  -> http://127.0.0.1:8080/v1
  -> Gateway container
  -> Claude CLI
  -> fallback to Codex CLI
```

Local-only development mode is enabled with:

```bash
HERMES_ALLOW_INSECURE_DEV=1 GATEWAY_API_KEY= docker compose up -d gateway
```

Hermes Custom API:

```text
base_url = http://127.0.0.1:8080/v1
model = auto
api_key = empty
```

Run smoke tests:

```bash
bash scripts/smoke.sh
```

## Request field policy

- `stream` — supported. `stream=true` returns `text/event-stream` (role / content / finish / `[DONE]`).
- `tools`, `tool_choice` — accepted but **silently dropped**. The backend CLI does not surface tool calls, so the response is plain text. Dropped field names are recorded as `silently_stripped` in `gateway.jsonl`.
- `response_format` — rejected with HTTP 400. The gateway cannot guarantee structured output and silently violating the constraint would mislead clients.

Operational details are in `runbook.md`. Implementation tasks are tracked in `tasks.md`.

