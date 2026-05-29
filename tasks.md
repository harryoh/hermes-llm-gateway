# Hermes LLM Gateway Tasks

이 파일은 실제 작업 진행용 체크리스트다. 요구사항 원문은 `prd.md`를 기준으로 한다.

## Phase 0: 로컬 PC 환경 및 CLI 계약 검증

목표: 로컬 PC에서 Claude/Codex CLI를 Gateway backend로 쓸 수 있는지 실행 계약을 확인한다.

### 0.1 Claude CLI 확인

- [x] 로컬 PC에서 `claude --version` 확인
- [x] 로컬 PC에서 `claude -p "ping"` 성공 확인
- [x] `claude -p --output-format json "ping"` stdout schema 저장
- [x] stdout에서 assistant 응답 field 확정
- [x] stderr와 exit code 정상 케이스 저장
- [ ] timeout이 필요한 장기 요청 샘플 확인

결과:

- `claude --version`: `2.1.149 (Claude Code)`
- sandbox 안에서 `claude -p`는 keychain/login storage 접근 문제로 `Not logged in` 발생
- sandbox 밖에서 `claude -p "hi"` 정상 동작
- sandbox 밖에서 `claude -p --output-format json "Reply with exactly: pong"` 정상 동작
- JSON 성공 응답의 assistant text field는 `result`
- JSON 실패 응답도 `result` field에 오류 메시지를 담음
- 응답 text field는 `result`
- error 판단에는 exit code, `is_error`, `result` 문자열을 함께 사용해야 함

완료 조건:

- Claude 응답 text를 안정적으로 추출할 수 있는 field가 확인됨
- 실패/성공 케이스의 stdout/stderr/exit code가 기록됨

### 0.2 Claude 계정 격리 확인

- [x] `CLAUDE_CONFIG_DIR`로 계정별 config directory 구조 확인
- [x] `acct1` credential directory 준비
- [ ] `acct2`, `acct3` 사용 여부 결정
- [x] Gateway container mount 대상 host path 확정
- [x] `CLAUDE_CONFIG_DIR=$HOME/.claude-accounts/acct1 claude login`
- [x] `acct1` login 후 host `claude -p --output-format json` 성공 확인
- [x] container 내부 `claude setup-token` 완료
- [x] container 내부 `claude -p --output-format json` 성공 확인

완료 조건:

- 컨테이너에 mount할 Claude credential path가 정해짐
- host와 container 양쪽에서 `acct1` 격리 profile Claude JSON 응답이 성공함

결과:

- mount 대상 host path: `$HOME/.claude-accounts/acct1`
- host `acct1`은 로그인 완료, `result: pong` 확인
- container 내부 `acct1`은 `claude setup-token` 후 `loggedIn: true`
- container 내부 `claude -p --output-format json`에서 `result: pong` 확인
- 컨테이너에서는 OAuth/keychain 기반 host login 재사용이 안 되므로 `claude setup-token` 필요
- 기본 Claude profile 로그인과 `CLAUDE_CONFIG_DIR` profile 로그인은 별개

### 0.3 Codex CLI 확인

- [x] 로컬 PC에서 `codex --version` 확인
- [x] `CODEX_HOME` 기반 계정 격리 가능 여부 확인
- [x] `codex exec` non-interactive 실행 샘플 확인
- [x] stdout/stderr/exit code 계약 확인
- [x] 최종 응답만 출력하는 옵션 조합 확인
- [x] sandbox/approval/cwd 제한 옵션 확인

결과:

- `codex --version`: `codex-cli 0.133.0`
- `codex exec --sandbox read-only --skip-git-repo-check --output-last-message <file> "Reply with exactly: pong"` 성공
- stdout에는 실행 로그와 최종 응답이 섞임
- `--output-last-message` 파일에는 최종 assistant message만 저장됨
- backend parser는 stdout 대신 `--output-last-message` 파일을 우선 사용해야 함

완료 조건:

- Codex를 chat response backend로 쓸 수 있는지 1차 판단 가능
- Phase 2 구현 또는 보류 결정 가능

### 0.4 Hermes 요청 형태 캡처

- [ ] Hermes Custom API 설정 가능 필드 확인
- [ ] Hermes가 보내는 request body 캡처
- [ ] `stream` 사용 여부 확인
- [ ] `tools`, `tool_choice`, `response_format` 사용 여부 확인
- [ ] `temperature`, `top_p`, `stop`, `max_tokens` 사용 여부 확인

완료 조건:

- Phase 1에서 허용/거절할 OpenAI-compatible field 목록 확정

### 0.5 컨테이너 실행성 확인

- [x] Gateway base image 후보 결정
- [x] 컨테이너 내부에서 Claude CLI 설치 가능 여부 확인
- [x] 컨테이너 내부에서 Codex CLI 설치 가능 여부 확인
- [x] host credential directory mount 방식 확인
- [x] Hermes host process에서 container port 호출 가능 여부 확인

결과:

- Docker version: `29.3.1`
- Docker Compose version: `v5.1.0`
- Docker image build 성공
- Container Claude version: `2.1.156 (Claude Code)`
- Container Codex version: `codex-cli 0.135.0`
- Credential mount는 token refresh 가능성을 고려해 read-write bind mount로 조정
- 기본 host Claude profile과 `~/.claude-accounts/acct1` 격리 profile 모두 로그인 확인
- `~/.codex`를 `/accounts/codex/acct1`로 mount해 컨테이너 내부 Codex 실행 확인

완료 조건:

- Phase 1 Dockerfile/Compose 구현 전제 확정

## Phase 1: Local PC Gateway MVP (Claude)

목표: 로컬 PC에서 Gateway container를 띄우고 Hermes가 Claude backend를 OpenAI-compatible API로 호출할 수 있게 한다.

### 1.1 프로젝트 스캐폴딩

- [x] Python package layout 생성
- [x] FastAPI app 생성
- [x] dependency 파일 작성
- [x] local dev 실행 명령 작성
- [x] 기본 lint/test 명령 결정

완료 조건:

- `uvicorn`으로 빈 Gateway app 실행 가능

### 1.2 Docker/Compose

- [x] Dockerfile 작성
- [x] `docker-compose.yml` 작성
- [x] `GATEWAY_API_KEY` env 주입
- [x] `/state` volume 구성
- [x] `/work` volume 구성
- [x] Claude credential mount 구성
- [x] container port `127.0.0.1:8080:8080` publish
- [x] replica 1 / workers 1 문서화

완료 조건:

- `docker compose up`으로 Gateway container 실행 가능

### 1.3 API 인증 및 기본 endpoint

- [x] `GATEWAY_API_KEY` 미설정 시 startup fail
- [x] `HERMES_ALLOW_INSECURE_DEV=1` 개발용 예외 구현
- [x] `X-API-Key` 검증 구현
- [x] `GET /health` 구현
- [x] `GET /admin/health` 구현
- [x] `GET /v1/models` 구현
- [x] `POST /v1/chat/completions` request model 구현

완료 조건:

- 잘못된 API key는 401
- `/health`는 상세 계정 정보를 노출하지 않음
- `/admin/health`는 인증 필요

### 1.4 OpenAI-compatible request 정책

- [x] `model=auto`, `claude-primary`, `codex-primary` 허용
- [x] `dgx-fast`는 Phase 3 전까지 400
- [x] `stream: true`는 400
- [x] `tools` 존재 시 400
- [x] `tool_choice` 존재 시 400
- [x] `response_format` 존재 시 400
- [x] unsupported field logging 구현

완료 조건:

- Hermes request subset이 조용히 무시되지 않음

### 1.5 State 관리

- [x] `/state/active_acct` read/write
- [x] `/state/cooldowns.json` read/write
- [x] atomic write 구현
- [x] invalid state 복구 정책 구현
- [x] `/state/gateway.lock` 전역 `fcntl` lock 구현
- [x] container restart 후 state 유지 확인

완료 조건:

- 재시작 후 active account와 cooldown 유지
- 동시 요청에서 Claude subprocess가 병렬 실행되지 않음

### 1.6 Claude backend

- [x] `CLAUDE_ACCOUNT_BASE` 기반 credential directory resolve
- [x] `CLAUDE_CONFIG_DIR=/accounts/claude/<acct>` 설정
- [x] 전용 `/work` cwd에서 실행
- [x] `claude -p --output-format json` subprocess 호출
- [x] stdout JSON parser 구현
- [x] timeout 처리 및 process kill
- [x] stderr rate limit marker parser 구현
- [x] auth/network/error failure code 분류
- [x] cooldown 중인 계정 호출 skip

완료 조건:

- Claude 성공 응답이 OpenAI chat completion response로 반환됨
- Claude 실패는 명확한 failure code로 기록됨

### 1.7 Logging 및 Telegram

- [x] `/state/gateway.jsonl` JSONL logging 구현
- [x] request id 생성
- [x] backend, acct, duration, fallback reason 기록
- [x] full prompt/response 기본 미기록
- [ ] Telegram env 확인
- [x] rate limit/auth/down 알림 구현
- [x] duplicate notification suppression 구현

완료 조건:

- 요청 1건당 JSONL 1줄 기록
- 같은 cooldown event에 중복 알림이 반복되지 않음

### 1.8 Smoke Test

- [x] `/health` curl
- [x] `/admin/health` curl
- [x] `/v1/models` curl
- [x] `/v1/chat/completions` Claude 성공 curl
- [x] wrong API key 401 확인
- [x] `stream: true` 400 확인
- [x] `tools` 400 확인
- [x] cooldown state 수동 주입 후 Claude skip 확인
- [ ] 동시 요청 2개 직렬화 확인
- [x] smoke test script 작성

결과:

- Local dev server는 sandbox 밖 권한으로 `127.0.0.1:18080`에서 실행 확인
- `/health` 정상
- `/v1/models` 정상
- `/admin/health` 정상
- `stream: true`는 400
- `tools`는 400
- `dgx-fast`는 Phase 1 unsupported model 400
- wrong API key는 401
- 과거 Claude 미로그인 상태에서는 chat completion이 `AUTH` failure code로 503이었음
- Docker Compose container smoke test 성공: `/health`, `/v1/models`
- Claude container path는 `setup-token` 전까지 `AUTH` 503
- `setup-token` 후 `/v1/chat/completions` `model=claude-primary` 성공
- `setup-token` 후 `/v1/chat/completions` `model=auto`가 Claude로 성공
- `scripts/smoke.sh` 추가
- `scripts/smoke.sh` 전체 통과

완료 조건:

- Phase 1 acceptance criteria 전부 통과

## Phase 2: Codex Backend + Hermes 연동

목표: Claude 실패 시 Codex로 fallback하고, 실제 Hermes Custom API와 연결한다.

### 2.1 Codex spike 결과 정리

- [x] Phase 0 Codex stdout/stderr 계약 정리
- [x] 최종 응답 추출 방식 확정
- [x] sandbox/approval 옵션 확정
- [x] chat backend로 부적합한 경우 사유 기록

완료 조건:

- Codex 구현 진행/보류 결정이 문서화됨

### 2.2 Codex backend 구현

- [x] `CODEX_ACCOUNT_BASE` 기반 credential directory resolve
- [x] `CODEX_HOME=/accounts/codex/<acct>` 설정
- [x] 전용 `/work` cwd에서 실행
- [x] `codex exec` subprocess 호출
- [x] 최종 응답 parser 구현
- [x] timeout 처리 및 process kill
- [x] rate limit/auth/network/error marker parser 구현
- [x] cooldown 기록 구현
- [x] Claude와 동일 전역 lock 사용

완료 조건:

- Codex 성공 응답이 OpenAI chat completion response로 반환됨

### 2.3 Fallback chain

- [x] `auto`: Claude -> Codex -> 503 구현
- [x] `claude-primary`: Claude 우선, 실패 시 Codex fallback
- [x] `codex-primary`: Codex 우선, 실패 시 503
- [x] fallback reason logging
- [x] fallback Telegram notification

완료 조건:

- Claude 실패 시 Codex fallback 성공
- Codex까지 실패하면 명시적 503

결과:

- Container Codex direct test 성공: `CODEX_HOME=/accounts/codex/acct1 codex exec ...`, output-last-message `pong`
- Gateway `model=codex-primary` 성공
- Gateway `model=auto` 정상 상태에서 Claude 성공
- `/state/cooldowns.json`에 Claude cooldown을 수동 주입했을 때 `model=auto`가 Codex로 fallback 성공

### 2.4 Hermes 연동

- [ ] Hermes Custom API `base_url` 설정
- [x] Hermes Custom API `api_key` 설정
- [ ] Hermes Custom API `model=auto` 설정
- [ ] 실제 Hermes 요청 1회 성공 확인
- [ ] Hermes request body와 Gateway parser 차이 확인
- [ ] 필요 시 unsupported field 정책 조정

완료 조건:

- Hermes host process가 Gateway container를 통해 Claude/Codex 응답을 받음

다음 작업:

- Hermes 앱에서 provider 설정:
  - `base_url = http://127.0.0.1:8080/v1`
  - `model = auto`
  - `api_key = 비워둠`
- Hermes 프롬프트 1회 실행 후 `/state/gateway.jsonl`로 실제 request field 확인

### 2.5 계정 전환

- [x] active account 수동 변경 명령 문서화
- [x] `/admin/switch` 구현
- [ ] Telegram `/switch acctN` handler 설계
- [ ] Telegram `/switch acctN` 구현
- [x] invalid account 방어
- [x] switch event logging

완료 조건:

- Telegram 또는 수동 명령으로 활성 계정 변경 가능

## Phase 3: DGX Local LLM 확장

목표: DGX local LLM을 `Claude -> Codex -> DGX` fallback의 마지막 backend로 붙인다.

### 3.1 DGX runtime 확인

- [ ] DGX에서 `docker ps` 확인
- [ ] LLM runtime이 vLLM인지 Ollama인지 확인
- [ ] LLM container image와 startup command 기록
- [ ] model path와 model id 기록
- [ ] `/v1/models` 지원 여부 확인
- [ ] `/v1/chat/completions` 지원 여부 확인

완료 조건:

- Gateway가 호출할 `DGX_BASE`와 `LOCAL_LLM_KIND` 결정

### 3.2 네트워크 토폴로지 결정

- [ ] Gateway와 LLM이 같은 Docker host인지 확인
- [ ] same-compose 가능 여부 확인
- [ ] remote-DGX LAN 접근 필요 여부 확인
- [ ] existing-container 유지 여부 확인
- [ ] firewall/port publish 확인

완료 조건:

- same-compose, remote-DGX, existing-container 중 하나로 결정

### 3.3 DGX backend 구현

- [ ] `DGX_BASE` env 추가
- [ ] `LOCAL_LLM_KIND` env 추가
- [ ] OpenAI-compatible passthrough 구현
- [ ] Ollama 차이점이 있으면 adapter 구현
- [ ] request field 전달 정책 구현
- [ ] timeout/error 처리 구현

완료 조건:

- Gateway에서 DGX `/v1/chat/completions` 호출 성공

### 3.4 Fallback 확장

- [ ] `auto`: Claude -> Codex -> DGX 구현
- [ ] `codex-primary`: Codex -> DGX 구현
- [ ] `dgx-fast`: DGX only 구현
- [ ] DGX fallback logging
- [ ] DGX fallback Telegram notification
- [ ] DGX curl smoke test

완료 조건:

- Codex 실패 시 DGX fallback 성공

## Phase 4: 운영 배포

목표: 로컬 PC에서 검증한 Gateway를 NAS/Mac mini/DGX에 재현 가능하게 배포한다.

- [ ] production compose 파일 정리
- [ ] `.env.example` 작성
- [ ] secret 관리 방식 문서화
- [ ] container restart policy 적용
- [ ] container log rotation 설정
- [ ] `/state` backup/restore 절차 작성
- [ ] credential volume backup 제외 정책 작성
- [ ] LAN firewall 규칙 문서화
- [ ] 운영 runbook 작성
- [ ] 장애 복구 절차 작성

완료 조건:

- 새 host에서 문서만 보고 Gateway를 재배포할 수 있음

## Phase 5: 필요 시 확장

목표: Hermes 요구나 UX 병목이 확인된 경우 기능을 확장한다.

- [ ] streaming SSE 필요성 판단
- [ ] Claude `--output-format stream-json` mapping
- [ ] vLLM streaming passthrough
- [ ] Ollama adapter 보강
- [ ] OpenAI tools/function calling mapping
- [ ] 명시적 routing hint 설계
- [ ] warm process 또는 persistent session 검토
- [ ] latency benchmark 자동화

완료 조건:

- 병목 또는 미지원 Hermes 기능이 실제 요구에 맞게 해소됨
