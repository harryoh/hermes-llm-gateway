# Hermes LLM Gateway

OpenAI-compatible local Gateway that routes requests to Claude Code CLI and OpenAI Codex CLI, with cooldown-aware fallback.

```text
Hermes (host or container)
  -> http://127.0.0.1:8080/v1
  -> Gateway container
       -> Claude CLI  (primary)
       -> Codex CLI   (fallback)
       -> 503         (no DGX backend yet)
```

---

## New-machine setup (dev mode)

Follow in order. Each step is independent and the order matters — auth must land inside the container, mount source dirs must exist before `compose up`, etc.

### 0. Prerequisites

- Docker Desktop (Mac/Windows) 4.34+ or Docker Engine (Linux)
- Claude subscription (Pro/Max/Team) — required for `claude auth login`
- ChatGPT/Codex account — required for `codex login`
- Node + npm on host (only for installing the `codex` CLI on host; the gateway container has its own)

### 1. Clone and create mount source dirs

Docker bind-mounts fail or create root-owned dirs if the host path is missing — create them first.

```bash
git clone https://github.com/harryoh/hermes-llm-gateway.git
cd hermes-llm-gateway

mkdir -p ~/.claude-accounts/acct1 ~/.codex
```

### 2. Create `.env` (local dev)

```bash
cp .env.example .env
```

The defaults (`HERMES_ALLOW_INSECURE_DEV=1`, empty `GATEWAY_API_KEY`) let the gateway run without an API key for localhost-only use. Clients can omit the `X-API-Key` header in this mode. For LAN exposure (different machine calling in), see the "Production / LAN exposure" section below.

### 3. Build and start the gateway

```bash
docker compose up -d --build gateway
```

Verify:

```bash
curl -s http://127.0.0.1:8080/health      # {"status":"ok"}
curl -s http://127.0.0.1:8080/v1/models   # auto / claude-primary / codex-primary
```

### 4. Authenticate Claude **inside the container**

This is the most error-prone step. Read the warnings.

```bash
docker compose exec gateway sh -lc \
  'CLAUDE_CONFIG_DIR=/accounts/claude/acct1 claude auth login'
```

The CLI prints a URL and a device code, then blocks waiting for the code — **keep the terminal open**. Open the URL in your host browser, approve, copy the code shown after approval, paste it back into the CLI. On success, `~/.claude-accounts/acct1/.credentials.json` appears on the host (via the bind mount).

Verify:

```bash
docker compose exec gateway sh -lc \
  'CLAUDE_CONFIG_DIR=/accounts/claude/acct1 claude -p --output-format json "Reply: pong"' \
  | python -c "import sys,json; d=json.load(sys.stdin); print('is_error:', d['is_error'], '| result:', d['result'])"
```

#### Why not `claude setup-token` or host-side `claude auth login`?

- `claude setup-token` (Claude Code 2.x) **prints the token to stdout** instead of writing a credential file. The container has nowhere to persist it.
- `claude auth login` **on the host (macOS)** stores OAuth credentials in the **macOS Keychain**, which Linux containers cannot read. The login must happen *inside* the container so the credential file lands on the bind-mounted volume.

### 5. Authenticate Codex **on the host**

Unlike Claude, Codex login is done on the **host**, not inside the container. Codex stores its auth in `$CODEX_HOME/auth.json` — a plain file with no Keychain involvement on Linux — and `~/.codex` is bind-mounted into the container, so a host-side login lands the credentials exactly where the gateway reads them.

> **Do not use `codex login --device-auth` inside the container.** It hits an account-level "Enable device code authorization for Codex" gate that cannot be cleared from the CLI, and the default in-container `codex login` opens a `localhost:1455` browser callback the container cannot serve. Host login sidesteps both.

Install the CLI on the host (once) and log in:

```bash
npm install -g @openai/codex
CODEX_HOME=~/.codex codex login
```

A browser opens (or a URL is printed) and redirects to `http://localhost:1455/...` — on a host with a desktop browser this just works. On success, `~/.codex/auth.json` appears and the container sees it immediately.

**Headless / remote host (no local browser):** the `localhost:1455` callback runs on the *server*, so you must reach it from your workstation. Forward the port over SSH, then log in inside that session:

```bash
ssh -L 1455:localhost:1455 <user>@<server>
CODEX_HOME=~/.codex codex login        # open the printed URL in your laptop browser
```

The OAuth redirect to `localhost:1455` tunnels back to the server's callback server and completes. Alternatively, run `codex login` on your laptop and copy the result over: `scp ~/.codex/auth.json <user>@<server>:~/.codex/auth.json` — the token is account-bound, not machine-bound.

Verify (writes the final assistant message to a file, then reads it back — this matches how the gateway invokes Codex):

```bash
docker compose exec gateway sh -lc '
  echo "Reply with exactly: pong" \
    | CODEX_HOME=/accounts/codex/acct1 codex exec \
        --sandbox read-only --skip-git-repo-check --color never \
        --cd /work --output-last-message /tmp/codex-last - \
    && echo --- && cat /tmp/codex-last && rm -f /tmp/codex-last
'
```

Expect `pong` after the `---` separator.

### 6. End-to-end check

```bash
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply with: pong"}]}' \
  | python -m json.tool
```

Expected: HTTP 200, `choices[0].message.content == "pong"`, `model == "claude-primary"`.

Streaming:

```bash
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","stream":true,"messages":[{"role":"user","content":"hi"}]}'
```

Run the smoke tests to exercise every endpoint, the model fallback chain, and the rejected-fields path in one shot:

```bash
bash scripts/smoke.sh
```

---

## Deploying on DGX (single host)

Use this when both the gateway **and** Hermes will run on the same DGX machine — no LAN exposure, no API key. SSH in, then follow steps 1–6 above verbatim. The gateway itself is CPU-only (vLLM backend that needs the GPU is planned for Phase 3 and not in this repo yet).

DGX-specific notes:

- **Headless is fine.** `claude auth login` prints a URL + device code. Open the URL in your laptop's browser, approve, copy the code shown after approval, paste it back into the SSH terminal. No browser needed on the DGX itself.
- **Linux keyring trap is the same shape as macOS Keychain.** Running `claude auth login` on the DGX host (not inside the container) tries to use libsecret/gnome-keyring, which is usually missing on a headless server and leaves no credential file. Always `docker compose exec gateway sh -lc 'claude auth login'` so the token lands on the bind-mounted volume.
- **No GPU access needed.** Plain Docker Engine works; you don't need `--gpus` or nvidia-docker for the gateway container.

After the gateway is up and authenticated, install Hermes on the same DGX:

```bash
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
mkdir -p ~/.hermes
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up -d --build
```

Hermes' compose uses `network_mode: host`, so `127.0.0.1:8080` inside the Hermes container reaches the gateway directly. Configure `~/.hermes/config.yaml` as in the "Hermes integration" section below.

---

## Hermes integration

Point Hermes' custom provider at the gateway. Hermes can run on the host (recommended for system access) or in its own container.

`~/.hermes/config.yaml`:

```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:8080/v1
  default: auto
  api_key: ""   # gateway runs with HERMES_ALLOW_INSECURE_DEV=1; set this if you enable GATEWAY_API_KEY
```

Networking notes:

- **Hermes on the host** — `http://127.0.0.1:8080/v1` works directly.
- **Hermes in a Docker container with `network_mode: host`** — same URL works (Linux only — Docker Desktop for macOS/Windows does not fully honor `network_mode: host`).
- **Hermes in a bridge-network container, or Docker Desktop on macOS/Windows** — use `http://host.docker.internal:8080/v1`.

Hermes is **chat-only** through this gateway — see "Request field policy" below for why.

---

## Request field policy

| Field | Behavior | Notes |
|---|---|---|
| `stream` | Supported | `stream=true` → `text/event-stream` (role / content / finish / `[DONE]`) |
| `tools`, `tool_choice` | **Silently dropped** | Backend CLI cannot emit `tool_calls`. Dropped field names recorded as `silently_stripped` in `gateway.jsonl`. |
| `response_format` | **Rejected (HTTP 400)** | Silently violating an output-format constraint would mislead clients. |
| Unknown `model` | Rejected (HTTP 400) | Allowed: `auto`, `claude-primary`, `codex-primary`. |

Hermes' agentic capabilities (file editing, terminal, browser) are blocked by the silent-strip — see `tasks.md` for the planned Anthropic Messages API migration that would enable real tool passthrough.

---

## Operations cheatsheet

```bash
# Tail the structured event log
docker compose exec gateway sh -lc 'tail -f /state/gateway.jsonl'

# Show active account and current cooldowns
curl -s http://127.0.0.1:8080/admin/health | python -m json.tool

# Switch active account (validated against ^[A-Za-z0-9_.-]+$)
curl -s -X POST http://127.0.0.1:8080/admin/switch \
  -H "Content-Type: application/json" -d '{"acct":"acct2"}'

# Smoke tests (health / models / switch / claude / codex / response_format 400)
bash scripts/smoke.sh
```

---

## Production / LAN exposure

Use this when the gateway runs on one machine (e.g., DGX, NAS) and clients on **other** machines call into it.

1. Generate a strong API key and switch off insecure-dev mode in `.env`:

   ```bash
   echo "GATEWAY_API_KEY=$(openssl rand -hex 32)" > .env
   echo "HERMES_ALLOW_INSECURE_DEV=0" >> .env
   ```

2. Change the port binding in `docker-compose.yml` from loopback to all interfaces (or a specific LAN IP):

   ```yaml
   ports:
     - "0.0.0.0:8080:8080"   # was "127.0.0.1:8080:8080"
   ```

3. Recreate the container so the new env vars and port mapping take effect:

   ```bash
   docker compose up -d --force-recreate gateway
   ```

4. Every request must now include the API key:

   ```bash
   curl -s http://<gateway-host-ip>:8080/health -H "X-API-Key: <your-key>"

   curl -s -X POST http://<gateway-host-ip>:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "X-API-Key: <your-key>" \
     -d '{"model":"auto","messages":[{"role":"user","content":"Reply: pong"}]}'
   ```

5. Remote Hermes config:

   ```yaml
   model:
     provider: custom
     base_url: http://<gateway-host-ip>:8080/v1
     default: auto
     api_key: "<your-key>"
   ```

Host-firewall reminder: on Ubuntu/DGX OS, allow inbound 8080 with `sudo ufw allow from <client-ip> to any port 8080` if `ufw` is active.

---

## Multi-account

Set up additional accounts by repeating step 4 with a different mount target:

```bash
mkdir -p ~/.claude-accounts/acct2
# Uncomment the matching `acct2` mount line that already exists in
# docker-compose.yml (and add acct3 there if you want a third):
#   - ${HOME}/.claude-accounts/acct2:/accounts/claude/acct2
docker compose up -d gateway
docker compose exec gateway sh -lc \
  'CLAUDE_CONFIG_DIR=/accounts/claude/acct2 claude auth login'
```

The gateway auto-cools down an account when it hits `RATE_LIMIT` / `AUTH` markers. Switching active accounts after that is manual via `/admin/switch` (Telegram bot is planned).

---

## Further reading

- `tasks.md` — phase plan and open work
- `prd.md` — design rationale (Korean)
