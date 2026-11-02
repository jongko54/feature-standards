# SMTP outbox 전달

네 언어의 v3 API가 같은 PostgreSQL outbox에 넣은 확인·재설정 메일을 별도 Python 워커가 전달한다. 기준은 [mail-delivery-v1 계약](../features/auth/mail-delivery-v1.md)이며 HTTP와 기본 v1/v2/v3 프로필은 바뀌지 않는다. 공급자 독립 SMTP 어댑터와 로컬 TLS 검증을 제공한다. 이 변경을 작성하는 시점에는 실제 SMTP 계정·발신 주소가 설정되지 않았으며 운영 발송을 실행하지 않았다.

## 준비와 실행

Python 3.12+, uv와 PostgreSQL 계정 schema 2가 필요하다. 기존 schema 1 서버는 중단하고 백업·DDL 권한을 확인한 뒤 `migrate-accounts`로 먼저 이관한다. 새 DB도 같은 계정 도구로 준비한다. `migrate-mail`은 기존 schema 2에 선택적인 delivery addon만 추가하며 계정 이관을 자동 실행하지 않는다.

```sh
uv sync --frozen --project tools
# AUTH_DATABASE_URL을 로컬 환경 또는 배포 시크릿에 설정한 뒤:
# 계정 schema 2가 없는 경우에만 먼저 실행
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
uv run --frozen --project tools python tools/auth_db.py migrate-mail
# 한 batch를 처리하고 종료
uv run --frozen --project tools python tools/mail_worker.py --once
# 지속 실행, SIGTERM/SIGINT로 종료 요청
uv run --frozen --project tools python tools/mail_worker.py
```

[003 migration](../features/auth/postgres/003_mail_delivery.sql)은 `schema_version=2`를 유지하고 `mail_delivery_schema_version=1`과 sidecar·enqueue trigger를 추가한다. 과거 outbox도 backfill하며 재실행은 delivery ID·lease·상태를 보존한다. API나 워커가 migration·데모 seed를 자동 실행하지 않는다.

마이그레이션은 워커를 중단한 상태에서 DDL 권한이 있는 별도 계정으로 수행한다. 기존 API의 outbox enqueue trigger는 `mail_delivery` INSERT 권한도 필요하다. 워커 계정에는 계정·token 준비 상태 SELECT와 outbox/sidecar SELECT·UPDATE 범위를 구성하고, 사용자·비밀번호를 수정하는 권한이나 DDL 계정을 그대로 부여하지 않는다. 구체적인 역할 이름과 자격 증명은 배포 환경에서 정한다.

## 설정

값은 로컬 환경변수나 배포 시크릿으로 주입한다. 비밀번호·DB URL·수신자·메일 원문을 채팅, 저장소, 로그에 복사하지 않는다.

[설정 템플릿](../examples/smtp/.env.example)을 별도의 무시된 `.env` 또는 배포 시크릿으로 옮겨 실제 값으로 채운다. 예제 값은 연결 가능한 계정이 아니다. private CA가 필요하지 않으면 선택 변수를 빈 문자열로 넣는 대신 생략한다.

| 변수 | 의미·기본값 |
|---|---|
| `AUTH_DATABASE_URL` | 필수 PostgreSQL URI. 운영은 명시적 `sslmode=verify-full` |
| `AUTH_SMTP_HOST` | 필수 SMTP 호스트. URL이나 userinfo가 아닌 호스트만 지정 |
| `AUTH_SMTP_MODE` | `starttls` 기본, 또는 `tls`, 제한된 `plain-local` |
| `AUTH_SMTP_PORT` | starttls 587, tls 465 기본. 실제 제공자 포트로 설정 |
| `AUTH_SMTP_FROM` | 필수 단일 ASCII 발신 mailbox. 제공자에서 검증한 주소 사용 |
| `AUTH_SMTP_USERNAME` / `AUTH_SMTP_PASSWORD` | 둘 다 설정하거나 둘 다 생략. 빈 값을 설정 누락으로 숨기지 않음 |
| `AUTH_SMTP_CA_FILE` | 선택 PEM CA. 생략하면 플랫폼 신뢰 루트 |
| `AUTH_SMTP_TIMEOUT_SECONDS` | blocking socket 작업 timeout, 기본 10초·1..30 |
| `AUTH_MAIL_PUBLIC_ORIGIN` | 필수 정확한 HTTPS origin. 확인·재설정 링크의 신뢰 출처 |
| `AUTH_MAIL_DEMO` | 기본 false. 명시적 loopback HTTP·평문 데모만 허용 |
| `AUTH_MAIL_MAX_ATTEMPTS` | 기본 5·1..20 |
| `AUTH_MAIL_BATCH_SIZE` | 기본 20·1..100, `--once` 한 번의 처리 상한 |
| `AUTH_MAIL_POLL_SECONDS` | 기본 5초·1..60 |
| `AUTH_MAIL_LEASE_SECONDS` | 기본 `max(300, timeout×30+30)`초. 같은 최솟값 이상·최대 86400 |

STARTTLS는 EHLO→TLS 승격→EHLO를 요구하고, TLS 1.2 이상·인증서 체인·호스트명을 검증한다. 지원하지 않는 서버에서 평문으로 내리지 않는다. 인증은 TLS 뒤에서만 수행한다. 직접 TLS도 같은 검증을 적용한다. `plain-local`은 `AUTH_MAIL_DEMO=true`, 숫자 loopback SMTP 목적지와 loopback HTTP origin, 인증 정보 없음일 때만 허용한다. API의 `AUTH_DEMO`가 메일 데모 설정을 대신하지 않는다.

DB도 운영에서는 verify-full을 요구한다. `sslrootcert` 등의 TLS 옵션은 URI에 설정하며 host·port·dbname·service query override를 금지한다. `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`로 접속 경로를 바꾸지 말고 명시 URI를 사용한다. DB 평문은 `AUTH_MAIL_DEMO=true`의 loopback URI에서만 허용한다. 운영 DB 인증·권한·백업·용량과 시크릿 수명 관리는 별도 구성이다.

실제 제공자를 연결하려면 SMTP 호스트·포트·보안 모드, 발신 주소/domain 검증, 인증정보를 준비하고 위 설정으로 워커를 실행한다. 제공자의 발송 한도와 SPF/DKIM/DMARC 정책도 해당 계정에서 맞춘다. 이 저장소가 특정 제공자 계정이나 DNS를 생성하지 않는다. 실제 메일 도착을 검사하려면 운영 설정과 확인된 테스트 수신 주소가 필요하다.

## 전달 상태와 실패

짧은 트랜잭션에서 `FOR UPDATE SKIP LOCKED`로 한 메시지를 claim하고 lease·새 claim ID·attempt를 commit한다. SMTP I/O 중에는 DB 트랜잭션을 유지하지 않는다. 전송 직전에 현재 account token·hash·기한·계정 상태·claim을 다시 검사한다. 이미 소비·교체·만료·관리자 차단된 capability는 취소하고 원문을 지운다.

| 상태 | 의미 |
|---|---|
| `pending` | 아직 SMTP가 소유하지 않은 메시지 |
| `leased` | 현재 claim이 처리 중. lease 만료 후 재claim 가능 |
| `retry` | 정해진 재시도 시각을 기다림 |
| `delivered` | SMTP 최종 DATA 250과 DB ACK를 확인함 |
| `failed` | 영구 실패 또는 최대 시도 초과. 원문 제거 |
| `cancelled` | capability가 더 이상 유효하지 않음. 원문 제거 |

4xx·네트워크·시간초과·TLS/인증 오류는 제한된 재시도 대상이고, 5xx·잘못된 주소·SMTPUTF8 미지원은 terminal 실패다. 지연은 `min(3600, 30×2^(attempts-1))`초이며 DB 시각으로 판정한다. 수신자·발신자 거절과 DATA 거절도 같은 코드 정책을 따른다. 로그와 `last_error_code`에는 허용된 일반 코드만 보관한다.

`accepted`는 관찰한 SMTP DATA 수락 횟수, `acknowledged`는 DB ACK까지 확인한 횟수다. 수신함 도착·열람 확인은 아니다. SMTP 수락 이후 QUIT 실패는 성공을 취소하지 않는다. SMTP 수락 응답 유실, DB ACK 결과 불명확, lease 만료·재시작에서는 중복 전송이 가능하다. 같은 delivery ID의 Message-ID를 재사용하는 at-least-once 전달이며, 수신 서버의 중복 제거 또는 exactly-once를 보장하지 않는다. socket timeout은 전체 전송의 벽시계 제한이 아니다.

ACK는 outbox와 sidecar를 차례로 잠근 뒤 delivery ID·claim ID·lease·현재 token을 비교한다. stale worker가 새 claim이나 재발급 메시지를 변경하지 못한다. 영구 실패·시도 초과·취소는 `delivered_at`을 성공처럼 기록하지 않고 원문을 지운다. terminal 메시지의 링크가 필요하면 계정 확인/재설정 요청으로 새 capability를 발급한다.

국제 수신 주소는 SMTPUTF8을 협상하며 서버가 지원하지 않으면 임의의 ASCII 주소로 바꾸지 않는다. 한국어 plain/html 본문은 신뢰 origin의 URL fragment 링크를 사용하고 HTML을 escape한다. 주소의 CR/LF·다중 수신자 주입을 거절한다. `account_tokens`에는 해시만 있지만 outbox와 로컬 수신 파일에는 원문 bearer capability가 있으므로 별도 접근 권한·암호화·보존 정책이 필요하다.

## 로컬 캡처와 검증

테스트용 [캡처 도구](../tools/mail_capture.py)는 아직 SMTP가 소유하지 않은 pending 메시지만 가져온다. leased·retry·terminal 메시지를 소비하지 않으며, outbox 잠금 뒤 최신 sidecar를 확인해 claim 경합을 피한다. addon이 없는 schema 2에서는 기존 동작을 유지한다. 새 mode 0600 파일에 fsync하고, DB ACK 결과가 불명확하면 파일을 보존한다. 파일·token을 CI artifact로 올리지 않는다.

[소스 시나리오 맵](../features/auth/mail-scenarios.json)과 [정적 checker](../tools/check_mail_contract.py)는 실제 테스트 선언과 SMTP/SQL 오류 코드를 연결한다. 테스트를 import하거나 실행하지 않으며 정적 매핑 자체는 통과 근거가 아니다.

```sh
uv run --frozen --project tools python tools/check_mail_contract.py
# stdlib SMTP wire 검사. 임시 CA와 loopback SMTP 서버만 사용한다.
uv run --frozen --project tools python -m unittest discover -s tests -p test_smtp_transport.py -v
# 각각 다른 전용 DB URL을 설정한 상태에서:
uv run --frozen --project tools python -m unittest discover -s tests -p test_mail_worker.py -v
uv run --frozen --project tools python -m unittest discover -s tests -p test_mail_capture_delivery.py -v
uv run --frozen --project tools python tests/mail_conformance.py
```

worker 자체 검사는 `AUTH_MAIL_TEST_DATABASE_URL`, 캡처 검사는 `AUTH_MAIL_CAPTURE_TEST_DATABASE_URL`, 네 언어 통합은 `FEATURE_STANDARDS_TEST_DATABASE_URL`을 사용한다. 모두 loopback·명시적 포트·ASCII `feature_standards_test*` DB명을 요구한다. 통합 하네스는 `feature_auth`를 삭제·재생성하므로 다른 작업과 공유하지 않는다. 통합 URL이 없으면 공통 fixture가 임시 PostgreSQL 서버를 소유·종료하며 `FEATURE_STANDARDS_PG_BIN`으로 서버 바이너리를 지정할 수 있다. SMTP fixture는 stdlib socket/TLS와 openssl로 임시 인증서를 만들며 외부 서버에 연결하지 않는다.

[CI](../.github/workflows/ci.yml)는 기존 v1/v2/v3·소비 앱 검사에 분리된 메일 DB의 worker·캡처 검사, 실제 TLS SMTP 계정 흐름과 queue 경합을 추가한다. [준비 도구](../tests/prepare_postgres.py)는 기존 schema-1·schema-2 DB를 유지하면서 메일 전용 worker/capture/integration DB에 선택 addon을 migrate·seed한다. 워크플로와 [템플릿](../ci/github-actions.yml)은 byte 동일하게 유지한다. 실제 실행 범위와 원격 결과는 해당 검증 기록·커밋 Actions로 확인한다.
