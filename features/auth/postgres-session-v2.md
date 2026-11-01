# Auth / browser-session-v2 — PostgreSQL

v1의 HTTP 입력·Origin·CSRF·쿠키·절대 만료·오류 형식을 유지하면서 사용자, 세션, 실패 기록을 공통 PostgreSQL에 저장한다. 기존 `browser-session-v1`은 기본 메모리 방식으로 유지한다. 회원가입·비밀번호 재설정·역할 관리는 이 버전의 범위 밖이다.

## 선택과 설정

- `AUTH_STORE=memory`가 기본이며 기존 v1 동작을 유지한다. `AUTH_STORE=postgres`가 v2를 선택한다. 다른 값은 시작 전에 거절한다.
- v2에는 `AUTH_DATABASE_URL` PostgreSQL URI가 필수이다. DB URL과 연결 오류의 원문을 로그·HTTP 응답에 출력하지 않는다. 별도 schema 선택은 제공하지 않는다.
- 기존 host/port, allowed origin, cookie secure, TTL, rate max/window 설정을 유지한다. v2는 사용자 이메일·비밀번호 환경 변수를 요구하거나 사용하는 대신 DB의 사용자를 조회한다.
- `AUTH_DEMO=true`는 기존 로컬 HTTP·쿠키 예외를 허용한다. DB 모드에서 사용자를 자동 생성하거나 비밀번호를 변경하지 않는다. 데모 밖에는 HTTPS origin과 secure cookie가 필수이다.
- 스키마는 앱 시작 전에 명시적으로 migrate한다. 앱은 schema version=1과 연결 가능 여부를 확인하고 불일치·연결 실패 시 바인딩 전에 시작을 거절한다. 자동 DDL·seed·메모리 fallback은 금지한다.
- `/healthz`는 v2에서 DB 준비 상태를 확인하고 준비되었을 때 `profile: browser-session-v2`로 200을 반환한다. 런타임 DB 실패는 503 `STORAGE_UNAVAILABLE`이다. `/auth/*` DB 실패도 같은 일반 오류와 no-store/nosniff이며 세션 쿠키를 새로 발급하지 않는다.

## 공통 저장 형식

기준 DDL은 `features/auth/postgres/001_initial.sql`이다. schema 이름은 `feature_auth`이다.

- `schema_version`: 한 행(version=1). version 변경 없이 DDL 계약을 조용히 바꾸지 않는다.
- `users`: id text PK, 정규화한 email text UNIQUE(C collation), password_hash text(PHC), enabled boolean. 이메일은 v1과 같은 ASCII 공백 제거·ASCII A–Z 소문자화만 적용한다. id는 원본 그대로 JSON 문자열로 반환한다.
- 비밀번호 PHC는 Argon2id v=19, m=65536 KiB, t=3, p=4, salt 16바이트, hash 32바이트 형식을 사용한다. 표준 base64(no padding) PHC를 네 언어가 검증한다. 비정상·지원하지 않는 저장 해시는 503으로 fail closed한다. 알 수 없는 사용자도 동일 비용 dummy hash를 검증하고 동일한 401 오류를 반환한다. enabled=false도 로그인·조회에서 인증되지 않는다.
- `sessions`: `token_hash`=SHA-256(쿠키 값의 UTF-8 bytes) 32바이트 bytea PK. 원문 세션 토큰은 DB에 저장하지 않는다. user_id FK, csrf_token(32바이트 난수의 base64url no padding), created_at, expires_at timestamptz. 삭제된 사용자 세션은 FK CASCADE로 제거된다.
- `login_attempts`: peer inet PK, failures bigint, expires_at timestamptz. 프록시 헤더를 신뢰하지 않는다. peer는 PostgreSQL inet/host 정규형으로 동일시한다.
- 시간 판정은 애플리케이션 시계 대신 DB `clock_timestamp()`를 사용한다. me 조회는 수명을 연장하지 않는다. 만료 기록은 인증 변경 트랜잭션에서 정리할 수 있으며 활성 상태를 지우면 안 된다.

## 트랜잭션과 원자성

로그인은 한 DB 트랜잭션에서 다음 순서를 따른다. 잠금 대기 전에 얻은 오래된 시간을 쓰지 않는다.

1. `SELECT pg_advisory_xact_lock(20261102, hashtext(host(CAST(peer AS inet))))`로 동일 peer의 검사·해싱·실패 기록·성공 갱신을 직렬화한다. 이 잠금 키는 네 언어에서 동일해야 한다.
2. 잠금 획득 후 DB 시각을 읽고 만료된 해당 peer 실패 기록을 제거한다. 활성 failures >= max이면 429와 양의 정수 ceil(남은 초) Retry-After를 반환한다.
3. DB의 사용자 PHC 또는 dummy PHC를 검증한다. 실패는 현재 활성 창의 횟수를 증가시키며 새 창은 DB 시각+window로 만든다. 실패 기록을 COMMIT한 후 401을 반환한다. 유효한 계정 여부에 따른 오류 본문 차이는 없다.
4. 성공이면 해당 peer의 실패 기록을 삭제하고 요청 쿠키의 이전 token_hash 세션만 삭제한다. 독립적인 32바이트 세션 토큰·CSRF를 생성하고 사용자 id와 DB 시각+TTL을 저장한다. COMMIT 성공 이후에만 200·쿠키를 반환한다.

me는 token_hash와 enabled 사용자, DB 시각 기준 유효 세션을 join해 조회한다. 로그인 응답과 동일한 `{user:{id,email},csrfToken}`을 반환한다. 세션은 자신이 연결된 사용자만 나타낸다.

로그아웃은 해당 세션 행을 `FOR UPDATE`로 잠근 트랜잭션에서 처리한다. 아직 만료되지 않은 저장 세션에는 사용자의 enabled 여부와 무관하게 상수 시간으로 검증한 정확히 한 개의 X-CSRF-Token이 필수이다. 잘못된 CSRF는 403이며 세션은 유지한다. 올바르면 서버 행을 지우고 COMMIT 성공 후 204와 쿠키 제거를 반환한다. 세션 누락·만료도 Origin 검증 후 멱등 204를 반환한다. DB 실패를 로그아웃 성공으로 표현하지 않는다.

독립 언어 서버·같은 언어의 두 인스턴스·재시작 후에도 같은 DB 상태를 관찰해야 한다. DB 연결 타임아웃은 유한해야 하며 실패 시 credential·URL을 드러내지 않는다. 테스트는 loopback PostgreSQL의 `sslmode=disable`을 사용한다. 원격 운영 DB는 별도의 인증·TLS·권한·용량 검토가 필요하다.

## 재사용과 테스트 경계

HTTP 어댑터는 저장소 구현과 SQL을 직접 알지 않는다. 메모리와 PostgreSQL을 선택하거나 주입할 수 있는 서비스/저장소 경계를 제공한다. Python 구현은 별도 프로젝트가 import 가능한 `feature_auth` 패키지로 제공하고 기존 `app:app` 실행을 유지한다. 공개 factory `create_app()`과 FastAPI dependency `current_user(request)`를 제공한다. current_user는 인증된 user dict를 반환하고 인증/저장소 실패를 기존 오류 계약으로 변환한다.

공통 테스트용 사용자 두 명은 명시적 도구에서만 seed한다: `demo-user`/`demo@example.com`/`correct-horse-battery-staple`, `other-user`/`other@example.com`/`other-correct-horse-password`. 실제 앱 시작에는 seed가 없다. seed 재실행은 기존 사용자·비밀번호를 덮어쓰지 않는다.

수용 기준: 기존 네 언어 v1 회귀, v2의 동일 API/React 검사, 네 언어 간 조회·폐기, 재시작 후 유지, 서로 다른 사용자 세션 분리, 공유 실패 제한·동시 요청의 원자성, 만료·CSRF, DB 장애 fail closed, 별도 Python+React 소비 앱 통합. 파괴적 테스트는 이름이 `feature_standards_test`로 시작하는 작업 전용 DB에서만 실행한다. 운영 DB·기존 사용자 데이터에는 테스트하지 않는다.
