---
title: Hermes LLM Gateway PRD — OpenAI 호환 라우터
tags: [hermes, llm-gateway, prd, openai-compatible, claude-headless, codex, dgx, vllm, router]
created: 2026-05-29
status: draft
supersedes: 2026-05-29_plan-hermes-llm-gateway.md
---

# Hermes LLM Gateway PRD

## 1. 요약

Hermes Agent에 단일 OpenAI 호환 API 엔드포인트를 제공하고, 내부에서 우선 Claude Code CLI와 OpenAI Codex CLI로 요청을 라우팅하는 LLM Gateway를 구축한다. DGX Spark 로컬 LLM 서버는 초기 MVP 이후 확장 backend로 붙인다.

핵심 목적은 다음과 같다.

- Hermes에는 `base_url = http://nas:8080/v1`, `model = auto` 하나만 제공한다.
- Gateway는 기본적으로 컨테이너 내부에서 실행하고, Hermes는 기본적으로 호스트에서 실행한다.
- 초기 백엔드는 `Claude -> Codex` 순서의 capacity-based fallback 체인으로 운용한다.
- DGX 로컬 LLM은 후속 Phase에서 `Claude -> Codex -> DGX` fallback 체인으로 확장한다.
- Claude/Codex 구독 백엔드는 opportunistic frontier backend로 취급하고, DGX 로컬 LLM은 추후 production-safe fallback으로 둔다.
- 한 백엔드가 한도 소진, 인증 만료, 장애, timeout 상태가 되어도 Hermes 요청은 가능한 한 중단 없이 다음 백엔드로 처리한다.

## 2. 배경

Hermes는 Anthropic API를 직접 지원하지 않고, OpenAI 호환 엔드포인트와 로컬 vLLM 계열 구성을 지원한다. 따라서 Claude Code나 Codex를 Hermes에 직접 붙이는 대신, OpenAI `/v1/chat/completions` 호환 gateway를 NAS에 두고 내부 backend adapter로 변환해야 한다.

보유 자원은 다음과 같다.

- Claude Max 구독 계정 3개
- ChatGPT 구독 기반 Codex 사용권
- NVIDIA DGX Spark (후속 확장)
- NAS 및 기존 Telegram 운영 채널

정책 및 운영상 중요한 전제는 다음과 같다.

- Gateway는 컨테이너로 격리하지만, Hermes는 기본적으로 호스트에서 실행하여 로컬 PC, NAS, Mac mini M2 Pro, DGX 등 설치 대상 시스템을 직접 조작할 수 있어야 한다.
- Hermes는 컨테이너가 publish한 host port로 Gateway를 호출한다.
- Claude/Codex CLI는 순수 completion API가 아니라 agent runtime이다.
- CLI backend는 prompt injection, 파일 접근, 명령 실행 가능성에 대해 별도 격리가 필요하다.
- 멀티계정은 병렬 pooling이 아니라 순차 단일활성 failover만 허용한다.
- 구독 기반 CLI backend는 production SLA backend로 보지 않는다.

## 3. 목표

### 3.1 Product Goals

- Hermes에서 OpenAI 호환 Custom API provider로 바로 사용할 수 있는 endpoint 제공
- Claude/Codex backend fallback을 먼저 구현하여 로컬 PC에서 즉시 사용할 수 있는 MVP 확보
- DGX 로컬 LLM 서버는 후속 확장으로 붙여 무제한 fallback 확보
- Telegram 알림과 수동 계정 전환으로 사람이 통제하는 운영 흐름 제공

### 3.2 Engineering Goals

- Phase 1에서 non-streaming `/v1/chat/completions` MVP 제공
- Docker/Compose 기반 Gateway 배포 제공
- API key 인증을 기본 필수로 적용
- Claude/Codex CLI 호출은 전역 단일 실행으로 강제
- CLI backend는 전용 working directory와 sandbox/approval 제한으로 격리
- backend 실패, 한도 소진, cooldown, latency를 JSONL 로그로 추적
- Hermes가 사용하는 OpenAI request subset을 캡처하고 명시적으로 지원/거절

## 4. 비목표

- Phase 1에서 streaming SSE를 구현하지 않는다.
- Phase 1에서 OpenAI tools/function calling을 변환하지 않는다.
- 자동 난이도 분류 라우팅을 구현하지 않는다.
- Claude/Codex 멀티계정 병렬 pooling을 구현하지 않는다.
- CLI backend를 공식 production API와 동일한 안정성으로 간주하지 않는다.
- Phase 1에서 DGX/vLLM/Ollama 연동을 구현하지 않는다.
- DGX 모델 품질을 Claude/Codex와 동일하게 보장하지 않는다.

## 5. 사용자 및 사용 시나리오

### 5.1 Primary User

Hermes Agent를 로컬 PC, NAS, Mac mini M2 Pro, DGX 환경에서 운영하는 개인 운영자.

### 5.2 Deployment Topology

기본 배포 토폴로지는 다음과 같다.

```text
Host OS
  ├─ Hermes Agent
  │    └─ calls http://127.0.0.1:8080/v1 or http://<host-ip>:8080/v1
  │
  └─ Docker / Compose
       └─ hermes-llm-gateway container
            ├─ FastAPI Gateway :8080
            ├─ claude CLI
            ├─ codex CLI
            ├─ mounted credentials/state
            └─ optional later: calls DGX local LLM http://dgx:8000/v1
```

이 토폴로지의 의도는 다음과 같다.

- Gateway와 Claude/Codex credentials/state는 컨테이너로 격리한다.
- Hermes는 호스트에서 실행하여 대상 시스템의 파일, shell, GUI, 로컬 도구를 직접 사용할 수 있게 한다.
- 로컬 PC, NAS, Mac mini M2 Pro, DGX 어디에 설치하더라도 Hermes의 시스템 조작 능력을 컨테이너 경계로 제한하지 않는다.
- Gateway는 host port `8080`으로 publish하고, Hermes는 OpenAI-compatible Custom API로 이 port를 호출한다.

선택 배포 모드:

- Hermes도 컨테이너 내부에서 실행할 수 있다.
- 이 경우 Hermes가 조작해야 하는 host path, Docker socket, GPU/device, network 권한을 별도 mount/capability로 명시해야 한다.
- Hermes 컨테이너화는 기본값이 아니라 보안/재현성이 시스템 조작 범위보다 중요한 경우의 옵션이다.

### 5.3 Main Flow

1. Hermes가 `POST /v1/chat/completions`로 요청을 보낸다.
2. Gateway가 API key와 request shape를 검증한다.
3. Gateway가 활성 Claude 계정의 cooldown 여부를 확인한다.
4. Claude가 사용 가능하면 `claude -p --output-format json`으로 처리한다.
5. Claude가 한도 소진, timeout, 인증 실패, 실행 실패이면 Codex backend로 fallback한다.
6. Codex도 실패하면 Phase 1/2에서는 명시적 503을 반환한다.
7. DGX 확장 이후에는 Codex 실패 시 DGX 로컬 LLM `/v1/chat/completions`로 passthrough한다.
8. backend 전환과 failure event는 JSONL 로그와 Telegram 알림으로 남긴다.

### 5.4 Manual Switch Flow

1. 활성 계정 `acct1`에서 rate limit이 감지된다.
2. Gateway가 해당 계정에 cooldown을 기록한다.
3. Gateway가 Telegram으로 알린다.
4. 운영자가 `/switch acct2` 또는 수동 파일 변경으로 활성 계정을 바꾼다.
5. 다음 요청부터 `acct2`를 사용한다.

## 6. 기능 요구사항

### 6.1 OpenAI 호환 API

Phase 1에서 다음 endpoint를 제공한다.

| Method | Path | Requirement |
|---|---|---|
| `POST` | `/v1/chat/completions` | non-streaming chat completion |
| `GET` | `/v1/models` | 지원 model id 목록 |
| `GET` | `/health` | 기본 health |
| `GET` | `/admin/health` | 인증된 상세 health |

`/v1/chat/completions`는 다음 request field를 처리한다.

| Field | Phase 1 behavior |
|---|---|
| `model` | Phase 1: `auto`, `claude-primary`, `codex-primary` 허용. DGX 확장 후 `dgx-fast` 추가 |
| `messages` | 필수 |
| `max_tokens` | backend가 지원하면 전달, CLI backend는 prompt instruction으로만 반영 가능 |
| `temperature` | CLI backend는 Phase 1에서 무시하되 로그. DGX 확장 후 local LLM에는 전달 |
| `top_p` | CLI backend는 Phase 1에서 무시하되 로그. DGX 확장 후 local LLM에는 전달 |
| `stop` | CLI backend는 Phase 1에서 미지원 로그. DGX 확장 후 local LLM에는 전달 |
| `stream` | `true`면 400 |
| `tools` | 존재하면 400 |
| `tool_choice` | 존재하면 400 |
| `response_format` | Phase 1에서는 400 또는 명시적 미지원 로그 후 400 |

지원하지 않는 위험 field는 조용히 무시하지 않는다. 미지원 field는 400 또는 structured warning log 중 하나로 명확히 처리한다.

### 6.2 Response Format

응답은 OpenAI chat completion 형식을 따른다.

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "claude-primary",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

Phase 1에서 usage 값은 정확하지 않을 수 있다. 단, field는 항상 포함한다.

### 6.3 Routing

Phase 1/2 기본 fallback 순서는 다음과 같다.

```text
auto:
  1. claude-primary
  2. codex-primary
  3. fail with 503
```

DGX 확장 이후 fallback 순서는 다음과 같다.

```text
auto:
  1. claude-primary
  2. codex-primary
  3. dgx-fast
```

명시 model 요청은 다음처럼 처리한다.

| Requested model | Behavior |
|---|---|
| `auto` | 현재 Phase에서 사용 가능한 전체 fallback chain 사용 |
| `claude-primary` | Claude 우선, 실패 시 기본적으로 fallback 허용 |
| `codex-primary` | Phase 1/2에서는 Codex 우선, 실패 시 503. DGX 확장 후 DGX fallback |
| `dgx-fast` | DGX 확장 후에만 허용. 확장 전에는 400 |

fallback 허용 여부는 Phase 1에서는 기본 허용으로 둔다. 추후 `x-hermes-no-fallback: true` 같은 header를 검토할 수 있다.

### 6.4 Claude Backend

Claude backend는 다음을 만족해야 한다.

- `claude -p --output-format json` 사용
- stdout JSON의 실제 응답 field를 Phase 0에서 확인 후 parser에 반영
- stderr는 rate limit/auth/network/error 감지에만 사용하고 사용자 응답에 그대로 노출하지 않음
- `CLAUDE_CONFIG_DIR=/accounts/claude/{acct}`로 계정별 설정 격리
- host에서는 `$HOME/.claude-accounts/{acct}`를 container의 `/accounts/claude/{acct}`에 mount
- 활성 계정은 state file에서 읽음
- rate limit 감지 시 해당 계정 cooldown 기록
- timeout 시 process kill 후 fallback

### 6.5 Codex Backend

Codex backend는 Phase 2 정식 구현 전에 spike를 수행해야 한다.

검증할 항목은 다음과 같다.

- `codex exec`가 일반 chat response backend로 사용할 만큼 안정적인지
- stdout에 최종 응답만 안정적으로 남는지
- `--json`, `--output-last-message`, sandbox, approval 옵션 조합
- `CODEX_HOME=~/.codex-{acct}` 계정 격리
- rate limit/auth/network/error stderr 또는 JSON marker
- 파일 접근, 명령 실행, repo context 개입을 충분히 제한할 수 있는지

Codex backend 정식 구현 요구사항은 다음과 같다.

- 전용 빈 working directory에서 실행
- 명령 실행 자동 승인 금지
- 가능하면 read/write scope를 빈 디렉토리로 제한
- stdout 최종 메시지만 assistant content로 사용
- 진행 로그는 gateway log로만 저장
- rate limit 감지 시 cooldown 기록

### 6.6 DGX Local LLM Backend (Later Extension)

DGX backend는 Phase 1/2 이후 확장 backend다. 초기 로컬 PC MVP에서는 구현하지 않는다. 확장 시 OpenAI-compatible local LLM server로 처리한다. 현재 기억상 vLLM을 설치해 구동했을 가능성이 높지만, 실제 DGX 환경이 vLLM인지 Ollama인지 확장 Phase에서 확인해야 한다.

- 기본 endpoint: `http://dgx:8000/v1`
- Gateway는 local LLM server의 `/v1/chat/completions`로 passthrough한다.
- DGX 요청에는 Hermes request field 중 local LLM server가 지원하는 field를 최대한 전달한다.
- DGX 장애 시 Gateway는 503을 반환한다.
- 모델은 MoE 또는 30B급 우선으로 선정한다. dense 70B는 latency 문제로 기본 후보에서 제외한다.
- vLLM이면 native OpenAI-compatible endpoint를 그대로 사용한다.
- Ollama이면 OpenAI-compatible `/v1` endpoint가 켜져 있는지 확인하고, 미지원/차이점이 있으면 Ollama adapter를 추가한다.
- Gateway는 local LLM 구현체를 `LOCAL_LLM_KIND=vllm|ollama|openai-compatible`로 구분할 수 있어야 한다.

### 6.7 DGX Container Network Topology

DGX local LLM도 컨테이너에서 실행될 가능성이 높다. Gateway container가 local LLM container에 접근하는 방식은 배포 위치에 따라 달라진다.

#### Case A: Gateway와 DGX LLM이 같은 Docker host에서 실행

같은 Docker host라면 하나의 `docker compose.yml`에 Gateway와 vLLM/Ollama service를 함께 묶을 수 있다.

```text
Docker host
  └─ compose project
       ├─ gateway
       │    └─ DGX_BASE=http://llm:8000/v1
       └─ llm
            └─ vLLM or Ollama container
```

이 경우 요구사항:

- Gateway는 Docker service name으로 LLM에 접근한다.
- 예: `DGX_BASE=http://llm:8000/v1`
- LLM port를 host에 publish하지 않아도 Gateway container는 internal compose network로 접근 가능하다.
- Hermes는 host에서 Gateway published port만 호출한다.

#### Case B: Gateway는 NAS/Mac mini, DGX LLM은 별도 DGX 장비에서 실행

Gateway와 DGX가 서로 다른 물리 장비라면 하나의 local Compose network로 묶을 수 없다. Gateway는 DGX host의 LAN 주소 또는 DNS 이름으로 접근한다.

```text
NAS or Mac mini
  └─ gateway container
       └─ DGX_BASE=http://192.168.x.y:8000/v1

DGX Spark
  └─ vLLM/Ollama container
       └─ publishes 8000/tcp to LAN
```

이 경우 요구사항:

- DGX LLM container는 `0.0.0.0:8000` 또는 DGX host LAN IP에 port publish
- DGX firewall에서 Gateway host의 접근 허용
- Gateway의 `DGX_BASE`는 `http://<dgx-lan-ip>:8000/v1`
- Docker service name `llm`은 사용할 수 없다.

#### Case C: Gateway와 LLM을 모두 DGX에서 실행

DGX 한 대에서 Gateway와 vLLM/Ollama를 같이 돌리면 Case A처럼 Compose로 묶는 것이 가장 단순하다.

이 경우 Hermes가 같은 DGX host에서 실행되면:

```text
Hermes base_url = http://127.0.0.1:8080/v1
Gateway DGX_BASE = http://llm:8000/v1
```

Hermes가 다른 장비에서 실행되면:

```text
Hermes base_url = http://<dgx-lan-ip>:8080/v1
Gateway DGX_BASE = http://llm:8000/v1
```

#### Case D: 기존 DGX LLM container를 그대로 사용

이미 DGX에서 vLLM/Ollama container가 따로 떠 있다면 Gateway Compose에 억지로 합치지 않는다. 먼저 다음을 확인한다.

```bash
docker ps
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/v1/chat/completions
```

기존 container가 OpenAI-compatible `/v1`을 제공하면 Gateway의 `DGX_BASE`만 그 주소로 지정한다.

### 6.8 Cooldown Management

계정별 cooldown state를 유지한다.

- 저장 파일: `${HERMES_STATE_DIR}/cooldowns.json`
- atomic write 사용
- 기본 cooldown은 5시간
- stderr/stdout에 reset timestamp가 있으면 실제 reset time을 우선
- cooldown 중인 계정은 호출하지 않음
- 중복 Telegram 알림은 억제

### 6.9 Global Single Active Lock

CLI backend는 process 전체에서 동시에 하나만 실행되어야 한다.

`asyncio.Semaphore(1)`만으로는 부족하다. 다음 중 하나를 적용한다.

- `fcntl` 기반 lock file
- SQLite transaction lock
- Redis lock

Phase 1 기본 선택은 `fcntl` lock file이다.

추가 운영 제약:

- `uvicorn --workers 1`
- 컨테이너 replica는 기본 1개만 허용
- Compose/Kubernetes 등에서 horizontal scaling 금지
- Claude와 Codex를 포함한 전체 CLI backend에 동일 lock 적용

### 6.10 Authentication

API key는 기본 필수다.

- 환경변수: `GATEWAY_API_KEY`
- 모든 `/v1/*` endpoint는 `X-API-Key` 검증
- `GATEWAY_API_KEY`가 없으면 서버는 기본적으로 startup fail
- 개발용 무인증은 `HERMES_ALLOW_INSECURE_DEV=1`이 있을 때만 허용
- `/health`는 무인증 가능하지만 상세 정보를 노출하지 않음
- `/admin/health`는 인증 필수

### 6.11 Logging

요청별 JSONL 로그를 남긴다.

기본 경로:

```text
${HERMES_STATE_DIR}/gateway.jsonl
```

필수 field:

- `ts`
- `request_id`
- `backend`
- `requested_model`
- `resolved_model`
- `acct`
- `duration_ms`
- `prompt_chars`
- `output_chars`
- `fallback_from`
- `failure_code`
- `unsupported_fields`

로그에는 API key, credential, full prompt, full response를 기본 저장하지 않는다. 디버그용 full capture는 별도 flag와 짧은 retention으로만 허용한다.

### 6.12 Telegram Notification

다음 event에서 Telegram 알림을 보낸다.

- Claude/Codex rate limit 감지
- 인증 만료 감지
- backend down 지속
- DGX fallback 진입 (DGX 확장 이후)
- active account switch 성공/실패

중복 알림 방지를 위해 같은 계정/같은 failure code는 cooldown 동안 1회만 알린다.

### 6.13 Container Deployment

Gateway는 기본적으로 Docker/Compose 컨테이너로 배포한다.

컨테이너 요구사항:

- FastAPI app과 Claude/Codex CLI를 포함한 image 제공
- `uvicorn --workers 1`로 실행
- host port `8080`을 container port `8080`에 publish
- state directory를 named volume 또는 host directory로 mount
- Claude/Codex 계정별 credential directory를 volume으로 mount
- timezone과 DNS 설정은 host 환경에 맞게 지정
- container restart policy는 `unless-stopped` 권장

기본 network mode:

- `bridge` network + `ports: ["8080:8080"]`
- Hermes가 같은 host에서 실행되면 `http://127.0.0.1:8080/v1` 사용
- Hermes가 다른 장비에서 실행되면 `http://<gateway-host-ip>:8080/v1` 사용

선택 network mode:

- `network_mode: host`는 NAS/DGX 환경에서 mDNS, host-only service, 특수 DNS가 필요할 때만 사용한다.
- host network 사용 시 port 충돌과 firewall 규칙을 별도 확인한다.

컨테이너 mount 원칙:

| Host path / volume | Container path | Purpose |
|---|---|---|
| `hermes-gw-state` | `/state` | active account, cooldown, logs, lock |
| `~/.claude-acct1` | `/accounts/claude/acct1` | Claude account 1 credentials |
| `~/.claude-acct2` | `/accounts/claude/acct2` | Claude account 2 credentials |
| `~/.claude-acct3` | `/accounts/claude/acct3` | Claude account 3 credentials |
| `~/.codex-acct1` | `/accounts/codex/acct1` | Codex account 1 credentials |
| `hermes-gw-work` | `/work` | CLI backend 전용 빈 working directory |

컨테이너 내부 환경변수:

| Variable | Requirement |
|---|---|
| `GATEWAY_API_KEY` | 필수 |
| `HERMES_STATE_DIR=/state` | 필수 |
| `HERMES_WORK_DIR=/work` | 필수 |
| `DGX_BASE=http://dgx:8000/v1` | 환경별 설정 |
| `LOCAL_LLM_KIND=vllm` | `vllm`, `ollama`, `openai-compatible` 중 하나 |
| `CLAUDE_ACCOUNT_BASE=/accounts/claude` | 필수 |
| `CODEX_ACCOUNT_BASE=/accounts/codex` | Phase 2 |
| `TG_BOT_TOKEN` | 선택 |
| `TG_CHAT_ID` | 선택 |

Claude/Codex backend는 host home path를 가정하지 않고, 위 account base path를 기준으로 credential directory를 찾아야 한다.

## 7. 비기능 요구사항

### 7.1 Security

- API key 필수
- 상세 health 인증 필수
- CLI backend는 전용 working directory 사용
- CLI command execution 자동 승인 금지
- credential file path는 로그에 남기지 않음
- stderr 원문은 내부 로그에만 제한적으로 보관
- gateway container port는 필요한 host interface에만 노출하거나 firewall로 제한
- container는 가능한 non-root user로 실행
- Docker socket은 Gateway container에 mount하지 않음
- Hermes가 host에서 실행되는 것이 기본이므로, Gateway container에는 host filesystem 전체를 mount하지 않음

### 7.2 Reliability

- backend timeout 기본 300초
- timeout 발생 시 subprocess kill
- fallback 가능한 failure는 다음 backend로 전환
- 모든 state write는 atomic write
- gateway 재시작 후 active account와 cooldown 복구
- 컨테이너 재시작 후 volume 기반 state 복구
- Gateway container replica는 1개만 실행

### 7.3 Observability

- `/health`: `{"status":"ok"}`
- `/admin/health`: active account, cooldown, backend availability, last failure summary
- JSONL 로그
- container stdout/stderr logs
- logrotate

### 7.4 Performance

초기 목표:

- Gateway overhead: 100ms 이하
- Claude/Codex cold start/warm latency는 Phase 0에서 측정
- CLI backend latency가 Hermes UX에 부적합하면 stream-json 또는 warm process 전략을 재검토
- DGX local LLM first token은 Phase 3에서 별도 측정

## 8. State Files

기본 state directory:

```text
~/.hermes-gw
```

파일:

| File | Purpose |
|---|---|
| `active_acct` | 현재 활성 Claude/Codex 계정 |
| `cooldowns.json` | 계정별 cooldown |
| `gateway.jsonl` | request event log |
| `notify_state.json` | Telegram 중복 알림 억제 |
| `gateway.lock` | 전역 CLI 실행 lock |

## 9. Phase Plan

### Phase 0: 로컬 PC 환경 및 CLI 계약 검증

- [ ] 로컬 PC에서 `claude -p` 동작 확인
- [ ] Gateway container 안에서 `claude -p` 동작 확인
- [ ] `claude -p --output-format json` stdout schema 확인
- [ ] Claude rate limit/auth/network/timeout error marker 캡처
- [ ] `CLAUDE_CONFIG_DIR` 계정 격리 확인
- [ ] Codex CLI auth 방식과 `CODEX_HOME` 격리 확인
- [ ] `codex exec` stdout/stderr/JSON output 계약 확인
- [ ] Codex sandbox/approval/cwd 제한 가능성 확인
- [ ] Hermes 실제 request capture: `stream`, `tools`, `response_format`, 기타 field 확인
- [ ] Claude/Codex cold start와 warm latency 측정
- [ ] Hermes host process에서 `http://127.0.0.1:8080/v1` 또는 host IP로 Gateway container 호출 확인

### Phase 1: Local PC Gateway MVP (Claude)

- [ ] FastAPI gateway 생성
- [ ] Dockerfile 작성
- [ ] docker compose 기본 배포 파일 작성
- [ ] 필수 API key 인증
- [ ] `/v1/chat/completions`, `/v1/models`, `/health`, `/admin/health`
- [ ] Claude backend
- [ ] 전역 `fcntl` lock
- [ ] cooldown state
- [ ] atomic state write
- [ ] JSONL logging
- [ ] Telegram 알림
- [ ] unsupported OpenAI field 처리
- [ ] curl 기반 smoke test
- [ ] container single-replica 실행 문서
- [ ] Hermes host 실행 + Gateway container 호출 문서

### Phase 2: Codex Backend + Hermes 연동

- [ ] Hermes Custom API 설정
- [ ] 실제 Hermes traffic으로 request compatibility 검증
- [ ] Codex backend spike 결과 반영
- [ ] Codex backend 정식 구현
- [ ] fallback chain `Claude -> Codex -> 503`
- [ ] Telegram `/switch` handler
- [ ] auth expired 복구 절차 문서화

### Phase 3: DGX Local LLM 확장

- [ ] DGX LLM runtime 확인: vLLM인지 Ollama인지, 또는 다른 OpenAI-compatible server인지 확인
- [ ] DGX LLM container 실행 방식 확인: 기존 container, Compose service, host process 중 무엇인지 확인
- [ ] DGX local LLM `/v1/models` 동작 확인
- [ ] DGX local LLM `/v1/chat/completions` 동작 확인
- [ ] Gateway와 DGX LLM이 같은 Docker host인지, 별도 물리 장비인지 확인
- [ ] DGX passthrough backend
- [ ] DGX network mode 문서화: same-compose, remote-DGX, existing-container 중 선택
- [ ] fallback chain `Claude -> Codex -> DGX`
- [ ] DGX fallback curl smoke test

### Phase 4: 운영 배포

- [ ] Docker Compose 운영 배포
- [ ] container restart policy
- [ ] container log rotation
- [ ] LAN firewall
- [ ] backup/restore 대상 파일 정의
- [ ] 운영 runbook

### Phase 5: 필요 시 확장

- [ ] streaming SSE
- [ ] Claude `--output-format stream-json` mapping
- [ ] vLLM streaming passthrough
- [ ] Ollama adapter, 필요 시
- [ ] OpenAI tools/function calling mapping
- [ ] 명시적 routing hint
- [ ] warm process 또는 persistent session 전략

## 10. Acceptance Criteria

### Phase 1 완료 기준

- Hermes 없이 curl로 `/v1/chat/completions` 호출 성공
- 잘못된 API key는 401
- `GATEWAY_API_KEY` 미설정 시 기본 startup fail
- `stream: true` 요청은 명시적 400
- `tools` 포함 요청은 명시적 400
- Claude 성공 시 OpenAI chat completion 응답 반환
- Claude cooldown 중에는 Claude subprocess를 실행하지 않고 fallback
- Claude failure 시 Codex 미구현 상태에서는 명시적 503 또는 configured fallback 응답
- CLI backend 동시 요청 2개가 들어와도 전역 lock으로 직렬화
- `/health`는 상세 계정 정보를 노출하지 않음
- `/admin/health`는 인증 후 상세 상태 반환
- JSONL 로그에 backend, duration, fallback reason 기록
- Gateway가 컨테이너에서 실행됨
- Hermes가 호스트에서 `http://127.0.0.1:8080/v1` 또는 host IP로 Gateway 호출 성공
- 컨테이너 재시작 후 `/state` volume의 active account와 cooldown 복구

### Phase 2 완료 기준

- Hermes Custom API에서 `model=auto`로 실제 요청 처리
- Codex backend가 일반 chat response backend로 사용할 수 있음을 spike 결과로 확인
- Claude 실패 시 Codex fallback
- Codex 실패 시 명시적 503
- Telegram `/switch acctN`로 활성 계정 변경
- Claude/Codex rate limit marker가 실측값으로 갱신됨

### Phase 3 완료 기준

- DGX local LLM runtime이 vLLM/Ollama/OpenAI-compatible 중 무엇인지 확인됨
- Gateway에서 DGX `/v1/models`와 `/v1/chat/completions` 접근 성공
- Codex 실패 시 DGX fallback 성공
- same-compose 또는 remote-DGX network mode가 문서화됨

## 11. 주요 리스크와 완화

| Risk | Impact | Mitigation |
|---|---:|---|
| CLI backend prompt injection | 높음 | 전용 cwd, sandbox, command approval 금지, stdout final response만 사용 |
| 멀티계정 ToS 리스크 | 높음 | 순차 단일활성, 수동 전환, 병렬 pooling 금지, DGX는 후속 fallback |
| `asyncio.Semaphore` 한계 | 중간 | `fcntl` 전역 lock, `uvicorn --workers 1` |
| 컨테이너 replica 중복 실행 | 중간 | Compose replica 1 고정, 전역 lock, 운영 runbook |
| Hermes를 컨테이너에 넣어 시스템 조작 능력 상실 | 중간 | 기본은 Hermes host 실행, Hermes container는 선택 모드로만 문서화 |
| Codex가 chat backend로 부적합 | 중간 | Phase 2 전에 spike, 부적합 시 Claude-only MVP로 유지하고 DGX 확장 우선순위 상승 |
| Claude/Codex CLI output 변경 | 중간 | Phase 0 schema capture, parser version logging, smoke test |
| Hermes가 streaming/tools 필수 사용 | 중간 | Phase 0 request capture, 필요 시 Phase 4를 Phase 2로 승격 |
| Phase 1/2에서 Claude/Codex 모두 실패 시 fallback 없음 | 중간 | 명시적 503, Telegram 알림, DGX 확장 Phase 우선순위 상승 |
| DGX 모델 품질 부족 | 중간 | MoE/30B 후보 평가, Claude/Codex 우선 유지 |
| API key 누락 배포 | 높음 | startup fail 기본값 |

## 12. Open Questions

1. Hermes Custom API가 실제로 보내는 request field 전체 목록은 무엇인가?
2. Hermes UX가 non-streaming 응답을 견딜 수 있는가?
3. Hermes가 tool/function calling을 필수로 사용하는가?
4. Claude `--output-format json`의 현재 stdout schema는 무엇인가?
5. Codex `exec`에서 가장 안전한 non-interactive 옵션 조합은 무엇인가?
6. Codex 구독 한도 소진 시 marker는 무엇인가?
7. DGX local LLM runtime은 vLLM인가, Ollama인가, 또는 다른 OpenAI-compatible server인가?
8. DGX에 올릴 1차 모델은 GPT-OSS 120B, Qwen3-MoE, GLM 중 무엇인가?
9. Gateway와 DGX LLM은 같은 Docker host에서 Compose로 묶을 것인가, 별도 DGX 장비의 published port로 접근할 것인가?
10. 기존 DGX LLM container가 이미 있다면 그 container의 port, image, startup command, model path는 무엇인가?
11. ChatGPT 구독 등급과 Codex 계정 수는 어떻게 되는가?
12. 운영상 fallback 발생 시 Hermes 사용자에게 backend model명을 노출할 것인가?
13. 각 설치 대상에서 Gateway host port는 `127.0.0.1` 전용으로 충분한가, 아니면 LAN IP 노출이 필요한가?
14. Claude/Codex credential volume은 host home directory bind mount로 둘 것인가, Docker named volume로 둘 것인가?

## 13. Initial Implementation Notes

Phase 1 구현 시 기본 Python stack은 다음을 사용한다.

- FastAPI
- Uvicorn single worker
- httpx
- pydantic
- stdlib `fcntl`, `tempfile`, `os.replace`, `asyncio.subprocess`

권장 실행 형태는 Docker Compose다.

```yaml
services:
  gateway:
    build: .
    container_name: hermes-llm-gateway
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    environment:
      GATEWAY_API_KEY: "${GATEWAY_API_KEY}"
      HERMES_STATE_DIR: "/state"
      HERMES_WORK_DIR: "/work"
      CLAUDE_ACCOUNT_BASE: "/accounts/claude"
      CODEX_ACCOUNT_BASE: "/accounts/codex"
      # Phase 3 DGX extension:
      # DGX_BASE: "${DGX_BASE:-http://dgx:8000/v1}"
      # LOCAL_LLM_KIND: "${LOCAL_LLM_KIND:-vllm}"
    volumes:
      - hermes-gw-state:/state
      - hermes-gw-work:/work
      - ${HOME}/.claude-acct1:/accounts/claude/acct1:ro
      - ${HOME}/.claude-acct2:/accounts/claude/acct2:ro
      - ${HOME}/.claude-acct3:/accounts/claude/acct3:ro
      - ${HOME}/.codex-acct1:/accounts/codex/acct1:ro

volumes:
  hermes-gw-state:
  hermes-gw-work:
```

컨테이너 내부 command:

```bash
GATEWAY_API_KEY="..." \
HERMES_STATE_DIR="/state" \
HERMES_WORK_DIR="/work" \
uvicorn gateway:app --host 0.0.0.0 --port 8080 --workers 1
```

Hermes host 설정:

```text
base_url = http://127.0.0.1:8080/v1
model = auto
api_key = <GATEWAY_API_KEY>
```

개발용 무인증 실행은 명시적으로만 허용한다.

```bash
HERMES_ALLOW_INSECURE_DEV=1 uvicorn gateway:app --host 127.0.0.1 --port 8080 --workers 1
```

운영 컨테이너에서는 `GATEWAY_API_KEY` 미설정을 fatal로 취급한다.
