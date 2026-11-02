# 계정 생명주기 v3 사용과 검증

`browser-session-v3`는 [계약](../features/auth/account-session-v3.md)과 [schema 2 마이그레이션](../features/auth/postgres/002_accounts.sql)으로 가입·이메일 확인·비밀번호 재설정을 정의한다. 기본 메모리 v1과 PostgreSQL v2는 별도 프로필에서 유지한다. 현재 확장 작업의 전체 실행 결과는 최종 검증 기록과 해당 커밋 Actions에서 확인한다. 아래 소스 매핑은 실행 성공이나 운영 보안 감사를 뜻하지 않는다.

## 명시적 선택과 이관

`AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`와 `AUTH_DATABASE_URL`이 필요하다. flag 기본값은 false이며, 존재하면 정확한 true/false만 허용한다. true+memory는 시작을 거절한다. v3는 schema version 2, v2는 version 1만 허용하고 `/healthz`는 선택한 프로필을 반환한다.

기존 서버를 중단하고 DB 백업·권한을 검토한 뒤 저장소 루트에서 실행한다. 앱은 migration·seed·memory fallback을 하지 않는다.

```sh
uv sync --frozen --project tools
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
uv run --frozen --project tools python tools/auth_db.py status
# 공개 계정이 필요한 로컬 데모에만:
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

기존 `enabled`를 `admin_enabled`로 이관하고 기존 계정을 확인된 것으로 처리한다. 새 `enabled`는 `admin_enabled AND email_verified_at IS NOT NULL`의 generated column이다. 새 가입은 확인 전 false이므로 이전 바이너리가 남더라도 로그인·조회가 차단된다. 이관된 DB에서 관리자 차단은 `admin_enabled`를 변경한다. 확인과 재설정이 관리자 비활성을 해제하지 않는다. migration 재실행은 새 pending 계정을 확인된 것으로 바꾸지 않는다.

서버는 구현별 실행에 v3 flag를 추가한다. React 개발 서버에는 빌드 시 `VITE_AUTH_ACCOUNT_LIFECYCLE=true`를 지정한다.

```sh
cd implementations/python-fastapi
AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true AUTH_DEMO=true \
AUTH_COOKIE_SECURE=false AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 \
uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
cd clients/react
VITE_AUTH_ACCOUNT_LIFECYCLE=true AUTH_API_TARGET=http://127.0.0.1:8000 npm run dev
```

## HTTP와 트랜잭션

| POST 경로 | 정확한 JSON 필드 | 성공 |
|---|---|---|
| `/auth/register` | email, password | 일반 202 accepted |
| `/auth/email-verification/request` | email | 같은 202 |
| `/auth/email-verification/confirm` | token | 본문 없는 204 |
| `/auth/password-reset/request` | email | 같은 202 |
| `/auth/password-reset/confirm` | token, password | 본문 없는 204 |

v1/v2에서는 새 경로가 404이다. v3의 모든 계정 경로는 정확한 Origin·JSON·최대 4096byte·중복/추가 키 및 UTF-8 규칙을 적용하고 쿠키를 발급하지 않는다. 계정 존재·확인·비활성 상태를 접수 응답으로 공개하지 않는다. 신규·재설정 비밀번호는 Unicode scalar 15개 이상·UTF-8 1024byte 이하이고 공백과 NUL을 보존한다. 이메일은 ASCII 정규화 후 내부 U+0000..U+0020 및 U+007F를 거절한다.

형식 오류는 `400 INVALID_REQUEST`, 올바른 형식의 무효·종류 불일치·만료·재사용 token은 동일 `400 INVALID_TOKEN`이다. peer+action당 60초 10회 제한을 넘으면 양의 Retry-After와 `429 RATE_LIMITED`이다. DB/커밋 오류는 일반 503이며 새 쿠키가 없다.

공통 DB gateway와 스택별 저장소가 하나의 트랜잭션을 소유한다. `account_reserve`가 공유 peer 제한을 먼저 예약하고, 허용된 요청만 64 MiB Argon2id PHC와 난수를 생성한다. `account_apply`는 그 예약을 한 번 소비하며 email cooldown·계정·token·outbox를 원자적으로 갱신한다. 제한된 요청에 비밀번호 해싱을 먼저 수행하지 않는다. 직접 SQL gateway 호출도 자체 제한을 적용한다.

확인 token은 24시간, reset token은 15분 수명이고 검증 테이블에는 SHA-256만 저장한다. 같은 이메일/종류는 60초 발송 cooldown을 가진다. 새 발급은 이전 같은 종류 token을 폐기한다. reset은 새 PHC·전체 사용자 세션 삭제·reset token 삭제를 함께 commit한다. 로그인은 사용자 FOR SHARE 잠금을 PHC 검증부터 세션 commit까지 유지하고 reset은 동일 사용자를 FOR UPDATE로 잠가, 구 비밀번호의 지연 로그인이 reset 후 새 세션을 만들지 못하게 한다.

## 로컬 메일 수신

기본 계정 API는 outbox에 기록하며 별도의 [SMTP 전달 워커](smtp-delivery.md)를 선택할 수 있다. 전달은 명시적 addon migration·SMTP 설정·워커 실행이 필요하고 운영 제공자 계정을 자동 생성하거나 외부 발송을 실행하지 않는다. 공개 HTTP 수신함은 없다. `account_tokens`와 달리 `mail_outbox`는 전달할 원문 capability를 보관한다. DB 접근과 수신 파일을 별도 민감 데이터로 다루고 운영의 역할 분리·암호화·보존 정책을 준비해야 한다.

로컬 데모 DB 이름도 `feature_standards_test*`이고 loopback·명시적 포트·sslmode=disable이어야 캡처 도구를 사용할 수 있다. `FEATURE_STANDARDS_TEST_DATABASE_URL`에 그 작업 전용 URI를 설정한다. 도구는 기존 파일·symlink를 덮어쓰지 않고 새 mode 0600 파일에만 기록한다.

```sh
uv run --frozen --project tools python tools/mail_capture.py --output /tmp/feature-auth-mail.jsonl
```

파일을 로컬 편집기로 열어 확인/재설정 링크를 사용한다. 파일을 로그·이슈·CI artifact에 올리지 않는다. SMTP addon이 있으면 캡처는 아직 claim되지 않은 pending 메시지만 소비하고 leased/retry/terminal 메시지를 가져가지 않는다. 캡처 후 outbox 원문은 제거하고 전달 시각을 기록한다. 소비·만료된 원문도 제거한다. 로컬 queue는 at-least-once이므로 메시지 id로 중복을 구분한다. 링크는 URL fragment에 token을 넣으며 React가 메모리로 읽은 뒤 주소에서 지운다. 페이지 로드만으로 확인하지 않고 사용자의 버튼으로 POST한다. 브라우저 영구 저장소에는 token을 남기지 않는다. SMTP의 DATA 수락·DB ACK와 실제 수신함 도착은 별개다.

## Rust PostgreSQL TLS

원격 연결은 `sslmode=verify-full`과 TLS 1.2 이상으로 인증서 체인·hostname을 검증한다. `sslrootcert`가 없으면 플랫폼 신뢰 루트, 있으면 지정한 PEM CA만 신뢰한다. 루트 파일 경로는 URI percent encoding을 사용한다.

```text
postgresql://auth_user@db.example.com:5432/auth?sslmode=verify-full&sslrootcert=%2Fetc%2Fauth%2Froot.pem
```

`require`, `prefer`, `verify-ca` 같은 불완전 외부 모드, query host/hostaddr 우회, TLS 거절 뒤 평문 fallback은 거절한다. 기존 평문은 명시적 loopback `sslmode=disable`만 허용한다. 이는 원격 운영 DB의 인증·최소 권한·백업·용량이나 실제 인터넷 네트워크 배포를 검증했다는 의미가 아니다.

## 검증과 소스 근거

[v3 시나리오 맵](../features/auth/scenarios-v3.json)은 공통 AuthContract, 계정 AccountContract, mixed 전용 SharedAccounts, SQL gateway와 실제 브라우저·Rust TLS 테스트를 연결한다. 혼합 검사 안에서 네 언어의 로그인/reset 경합과 프로세스 재시작을 각각 순회한다. 정적 검사와 실제 실행 결과는 구분한다.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v3.py --check
uv run --frozen --project tools python tests/account_conformance.py --browser
python3 implementations/rust-axum/tests/postgres_tls.py
```

공통 v3 harness는 PostgreSQL 서버 바이너리 또는 `FEATURE_STANDARDS_TEST_DATABASE_URL`의 **전용 테스트 DB**를 사용하고 스키마를 삭제·재생성한다. 한 구현만 볼 때는 `--backend python|go|java|rust`를 지정한다. TLS fixture는 SSL 지원 PostgreSQL 서버 바이너리와 openssl이 필요하며 `FEATURE_STANDARDS_TLS_PG_BIN`으로 경로를 지정할 수 있다. fixture가 소유한 두 임시 서버만 시작·종료한다.

언어별 자체 테스트는 `AUTH_TEST_DATABASE_URL`의 schema-1 DB와 `AUTH_ACCOUNT_TEST_DATABASE_URL`의 schema-2 DB를 분리한다. [CI 준비 도구](../tests/prepare_postgres.py)는 네 언어 각각의 두 DB와 SQL 전용 DB를 명시적으로 migrate·seed한다. [워크플로](../.github/workflows/ci.yml)는 v1/v2 회귀, v3 HTTP·mixed·browser, SQL transaction, Rust TLS와 기존 소비 앱을 실행하도록 정의하며 [템플릿](../ci/github-actions.yml)과 동일하게 유지한다.
