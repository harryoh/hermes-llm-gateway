# Hermes LLM Gateway Runbook

## 1. Claude 격리 계정 로그인

Gateway는 기본 Claude profile이 아니라 계정별 격리 directory를 사용한다.

기본 계정:

```bash
mkdir -p "$HOME/.claude-accounts/acct1"
CLAUDE_CONFIG_DIR="$HOME/.claude-accounts/acct1" claude login
```

host 로그인 확인:

```bash
CLAUDE_CONFIG_DIR="$HOME/.claude-accounts/acct1" \
  claude -p --output-format json "Reply with exactly: pong"
```

성공 기준:

- exit code 0
- JSON field `is_error`가 `false`
- JSON field `result`가 `pong`

주의:

- `claude -p "hi"`가 기본 profile에서 동작해도 `CLAUDE_CONFIG_DIR` 격리 profile은 별도 로그인해야 한다.
- Codex/Codex sandbox 안에서 실행한 `claude`는 macOS keychain 접근 제한 때문에 `Not logged in`으로 보일 수 있다. 실제 검증은 일반 터미널에서 수행한다.
- macOS OAuth/keychain 기반 로그인은 Docker container 안에서 그대로 재사용되지 않을 수 있다.

## 1.1 Claude 컨테이너 인증 토큰 설정

Gateway container 안에서 Claude를 실행하려면 long-lived token 설정이 필요하다.

먼저 Gateway container를 실행한다.

```bash
docker compose up -d --build gateway
```

그 다음 일반 터미널에서 다음 명령을 실행한다.

```bash
docker compose exec gateway sh -lc \
  'CLAUDE_CONFIG_DIR=/accounts/claude/acct1 claude setup-token'
```

이 명령은 Claude subscription이 필요하며, 안내에 따라 인증을 완료한다.

컨테이너 내부 검증:

```bash
docker compose exec gateway sh -lc \
  'CLAUDE_CONFIG_DIR=/accounts/claude/acct1 claude -p --output-format json "Reply with exactly: pong"'
```

성공 기준:

- exit code 0
- JSON field `is_error`가 `false`
- JSON field `result`가 `pong`

보안 주의:

- `setup-token` 과정에서 표시되는 토큰이나 URL은 채팅/로그에 붙여넣지 않는다.
- `~/.claude-accounts/acct1`은 credential material을 포함할 수 있으므로 외부 저장소에 커밋하지 않는다.

## 2. Gateway 컨테이너 실행

`.env` 파일 생성:

```bash
cp .env.example .env
```

로컬에서만 접속할 개발 모드라면 `.env`를 이렇게 둔다.

```text
HERMES_ALLOW_INSECURE_DEV=1
GATEWAY_API_KEY=
```

이 경우 `X-API-Key` 없이 호출할 수 있다.

LAN에 노출하거나 운영 모드로 쓸 때는 `.env`를 이렇게 바꾼다.

```text
HERMES_ALLOW_INSECURE_DEV=0
GATEWAY_API_KEY=<strong-local-secret>
```

컨테이너 실행:

```bash
docker compose up -d --build gateway
```

상태 확인:

```bash
curl -sS -H "X-API-Key: $GATEWAY_API_KEY" \
  http://127.0.0.1:8080/health
```

개발 모드에서는 header 없이 호출한다.

```bash
curl -sS http://127.0.0.1:8080/health
```

모델 목록:

```bash
curl -sS -H "X-API-Key: $GATEWAY_API_KEY" \
  http://127.0.0.1:8080/v1/models
```

채팅 completion:

```bash
curl -sS -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Reply with exactly: pong"}]
  }'
```

Codex 직접 경로 확인:

```bash
curl -sS -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "codex-primary",
    "messages": [{"role": "user", "content": "Reply with exactly: pong"}]
  }'
```

Fallback 확인:

- 정상 상태의 `model=auto`는 Claude를 우선 사용한다.
- Claude cooldown 또는 실패 상태에서는 Codex로 fallback한다.
- Phase 3 전까지 Claude와 Codex가 모두 실패하면 503을 반환한다.

활성 계정 전환:

```bash
curl -sS -X POST http://127.0.0.1:8080/admin/switch \
  -H "Content-Type: application/json" \
  -d '{"acct": "acct1"}'
```

현재 활성 계정 확인:

```bash
curl -sS http://127.0.0.1:8080/admin/health
```

## 3. Hermes 설정

Hermes는 host에서 실행하고 Gateway container의 published port를 호출한다.

```text
base_url = http://127.0.0.1:8080/v1
model = auto
api_key = 비워둠
```

Hermes에서 테스트 프롬프트를 실행한 뒤 Gateway 로그를 본다.

```bash
docker compose logs -f gateway
```

JSONL request event 로그:

```bash
docker compose exec gateway sh -lc 'tail -50 /state/gateway.jsonl'
```

Hermes가 다른 장비에서 실행되면 Gateway compose port binding을 LAN IP에 맞게 조정한 뒤:

```text
base_url = http://<gateway-host-ip>:8080/v1
model = auto
api_key = <GATEWAY_API_KEY>
```

## 4. 반복 smoke test

```bash
scripts/smoke.sh
```

이 테스트는 다음을 확인한다.

- `/health`
- `/v1/models`
- `/admin/switch`
- `model=claude-primary`
- `model=codex-primary`
- `model=auto`
- Claude cooldown 시 Codex fallback
- `stream: true` 400
