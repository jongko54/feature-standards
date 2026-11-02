# PostgreSQL v2 사용과 검증

`browser-session-v2`는 DB 사용자·세션·실패 기록을 공유하는 선택 프로필입니다. 기본값인 메모리 `browser-session-v1`도 유지합니다. 동작 기준은 [v2 명세](../features/auth/postgres-session-v2.md)와 [DDL](../features/auth/postgres/001_initial.sql)이며, 이 문서는 실행·재사용·검증 경계를 설명합니다.

가입·이메일 확인·비밀번호 재설정이 필요하면 별도 [v3 계약](../features/auth/account-session-v3.md)과 [실행 안내](account-v3.md)를 따릅니다. 기본 `AUTH_ACCOUNT_LIFECYCLE=false`는 v2/schema 1을 유지합니다.

전용 로컬 PostgreSQL 18.6에서 실행한 결과는 [검증 기록](validation-2026-11-02.md)에 정리했습니다. 아래 표의 시나리오 수는 소스에 연결된 범위이며, 원격 CI와 운영 보안 감사 상태를 뜻하지 않습니다.

## 저장소 선택과 준비

| 설정 | 메모리 v1 | PostgreSQL v2 |
|---|---|---|
| `AUTH_STORE` | `memory`(기본) | `postgres` |
| 사용자 | 환경 설정 한 명 | DB의 정규화된 이메일·원본 사용자 ID |
| `AUTH_USER_EMAIL/PASSWORD` | 비데모에서 필수 | 사용하지 않음 |
| 세션·실패 기록 | 프로세스 메모리 | 같은 DB를 사용하는 인스턴스·언어가 공유 |
| 시간 | 구현의 주입 가능한 시계 | DB `clock_timestamp()` |
| 준비 상태 | `browser-session-v1` | 연결·schema version 1 확인 후 `browser-session-v2` |
| 저장소 실패 | 해당 없음 | `503 STORAGE_UNAVAILABLE`, 새 쿠키 없음 |

`AUTH_DATABASE_URL`에 PostgreSQL URI를 설정합니다. DB 이름과 권한은 미리 준비해야 합니다. 네 언어의 로컬 공통 검증에는 loopback 호스트와 명시적인 `sslmode=disable`을 사용합니다. URI와 오류 원문은 로그나 HTTP 응답에 출력하지 않습니다.

저장소 루트에서 다음 명령을 명시적으로 실행합니다.

```sh
uv sync --frozen --project tools
uv run --frozen --project tools python tools/auth_db.py migrate
uv run --frozen --project tools python tools/auth_db.py status
# 공개 테스트 계정이 필요한 로컬 데모에만 사용
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

앱은 시작 시 연결·스키마 버전만 확인하며 DDL·seed를 실행하지 않습니다. `AUTH_DEMO=true`도 DB의 계정을 생성하거나 해시를 바꾸지 않습니다. 명시적 seed는 기존 사용자·비밀번호를 덮어쓰지 않고 다음 공개 계정을 준비합니다.

| ID | 이메일 | 공개 테스트 비밀번호 |
|---|---|---|
| `demo-user` | `demo@example.com` | `correct-horse-battery-staple` |
| `other-user` | `other@example.com` | `other-correct-horse-password` |

DB 모드는 `AUTH_USER_EMAIL`·`AUTH_USER_PASSWORD`를 요구하지 않습니다. 데모 밖에서는 HTTPS Origin과 secure 쿠키를 요구합니다. TLS 종료와 운영 DB 연결을 준비하는 작업은 이 참조 구현의 적합성 검사와 별개입니다.

## 서버와 저장소 경계

각 구현의 HTTP 어댑터는 SQL을 직접 다루지 않으며 서비스·저장소 경계에서 메모리 또는 PostgreSQL을 선택·주입합니다. 구현별 API와 실행은 [Python](../implementations/python-fastapi/README.md), [Go](../implementations/go-net-http/README.md), [Java](../implementations/java-spring/README.md), [Rust](../implementations/rust-axum/README.md)를 따릅니다.

공통 저장 형식은 Argon2id v19 PHC(m=65536, t=3, p=4, salt 16바이트, hash 32바이트), SHA-256 세션 토큰 해시, 독립 CSRF, PostgreSQL inet peer입니다. 로그인은 namespace `20261102`의 공통 advisory transaction lock 아래에서 실패 창·자격 증명·성공 시 실패 제거·세션 회전을 원자적으로 처리합니다. 잠금 후 DB 시각을 사용하고 commit 성공 뒤에만 응답합니다.

로그아웃은 저장 세션 행을 `FOR UPDATE`로 잠급니다. 사용자 enabled 여부와 무관하게 아직 만료되지 않은 저장 세션에는 정확히 한 개의 일치하는 CSRF가 필요합니다. 누락·오류는 403이며 세션을 유지합니다. 올바른 CSRF이면 삭제를 commit한 뒤 204를 반환합니다. 사용자 비활성화는 로그인·조회에서 거절하며, 없는 세션·만료 세션의 로그아웃은 Origin 검증 후 멱등입니다.

현재 Rust PostgreSQL 어댑터는 원격 `sslmode=verify-full`에서 TLS 1.2 이상·인증서 체인·hostname을 검증합니다. `sslrootcert`가 없으면 플랫폼 신뢰 루트, 있으면 지정한 PEM CA만 신뢰합니다. `require`·`prefer`·`verify-ca` 등의 불완전한 외부 모드와 TLS 거절 뒤 평문 재시도는 허용하지 않습니다. 기존 평문은 명시적 loopback+`sslmode=disable`만 유지합니다. [TLS 설정·fixture 안내](account-v3.md#rust-postgresql-tls)는 운영 DB의 인증·권한·백업·용량 검증과 구분합니다.

## 계정 생명주기 v3로 이관

v1/v2를 유지하면서 계정 흐름이 필요한 DB만 schema 2로 이관합니다. 서버 중단과 DB 이관 범위를 확인한 뒤 `AUTH_DATABASE_URL`을 설정하고 명시적 도구를 실행합니다. 앱이 자동 DDL·seed를 수행하지 않습니다.

```sh
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
uv run --frozen --project tools python tools/auth_db.py status
```

이관 후 서버는 `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`, React는 개발·빌드 시 `VITE_AUTH_ACCOUNT_LIFECYCLE=true`로 선택합니다. v3는 schema 2를 요구하며 v2는 schema 1만 허용합니다. 기존 관리자 허용은 `admin_enabled`로 옮기고 새 `enabled`는 관리자 허용과 이메일 확인을 함께 반영합니다. 새 계정은 확인 전 로그인할 수 없으며, 확인·재설정이 관리자 차단을 해제하지 않습니다.

계정 작업은 같은 트랜잭션의 `account_reserve`로 peer 제한을 먼저 확인하고 허용된 요청만 PHC·token 생성과 `account_apply`를 수행합니다. 로그인은 사용자 잠금을 비밀번호 검증부터 커밋까지 유지하며, 재설정은 비밀번호 교체와 전체 사용자 세션 폐기를 함께 커밋합니다. [명세](../features/auth/account-session-v3.md)에 원자성과 실패 동작이 정의되어 있습니다.

계정 메일은 민감한 원문 token을 포함한 outbox입니다. [로컬 수신 도구](../tools/mail_capture.py)는 검사된 작업 전용 DB에서 새 mode 0600 파일로만 옮기며 외부 메일을 발송하지 않습니다. 수신 파일을 로그·이슈·CI artifact에 올리지 않습니다. 실제 계정 API·혼합 언어·로컬 링크 브라우저 흐름은 아래 하네스로 검증합니다. 스키마를 초기화하므로 다른 테스트와 DB를 공유하지 않습니다.

```sh
uv run --frozen --project tools python tests/account_conformance.py --browser
```

언어별 자체 v3 검사는 `AUTH_ACCOUNT_TEST_DATABASE_URL`의 별도 schema-2 DB를 사용하고 기존 `AUTH_TEST_DATABASE_URL`의 schema-1 DB와 분리합니다. 세부 [가입·확인·재설정 및 메일 절차](account-v3.md)를 따릅니다.

## 별도 소비 앱

[별도 예제](../examples/consumer-python-react/README.md)는 인증 소스를 복사하지 않습니다. [React 사용 안내](../clients/react/README.md)도 함께 확인할 수 있습니다.

- [Python 의존성](../examples/consumer-python-react/pyproject.toml)은 `feature-standards-python-auth`를 uv path dependency로 설치합니다. [wheel 설정](../implementations/python-fastapi/pyproject.toml)의 실제 import 패키지는 `feature_auth`이며 `create_app`과 `current_user`를 공개합니다.
- [보호 API](../examples/consumer-python-react/app.py)는 `Depends(current_user)`로 `/api/profile`을 보호합니다. 인증된 user dict를 받고 401·503은 공통 오류 계약을 사용합니다.
- [React 소비 코드](../examples/consumer-python-react/src/main.tsx)는 `@feature-standards/react-auth/api`에서 `authApi`와 `AuthSession`을 import합니다. [export 정의](../clients/react/package.json)는 `./api`를 가리킵니다.

의존성과 브라우저를 준비합니다.

```sh
uv sync --frozen --project examples/consumer-python-react
npm --prefix examples/consumer-python-react ci
npm --prefix examples/consumer-python-react run build
# 공통 클라이언트에서 설치한 Chromium을 공유한다
cd clients/react
npm ci
npx playwright install chromium
cd ../..
```

[소비 앱 harness](../tests/consumer_conformance.py)가 전용 DB를 명시적으로 migrate·seed하고 임시 Python API와 포트 5174의 Vite를 실행합니다. `FEATURE_STANDARDS_PG_BIN` 또는 전용 테스트 DB 설정은 공통 PG harness와 같습니다.

```sh
uv run --frozen --project tools python tests/consumer_conformance.py
```

수동으로 볼 때는 명시적 DB 준비 후 별도 터미널에서 다음을 실행합니다.

```sh
cd examples/consumer-python-react
AUTH_STORE=postgres AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5174 \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
cd examples/consumer-python-react
AUTH_API_TARGET=http://127.0.0.1:8000 npm run dev
```

브라우저 주소는 `http://127.0.0.1:5174`입니다. `AUTH_DATABASE_URL`은 서버 환경에 전달해야 합니다. 이 예제는 로컬 설치·import 사용을 보여주며 npm/PyPI 게시 상태를 뜻하지 않습니다.

## 검증과 근거 맵

[scenarios-v2.json](../features/auth/scenarios-v2.json)은 다음 실제 소스를 연결합니다. 각 행의 수는 논리 시나리오이며 하나의 메서드에 여러 assertion이 있을 수 있습니다.

| 범위 | 실제 근거 | 논리 시나리오 | 실행 방식 |
|---|---|---:|---|
| 공통 HTTP | [`AuthContract`](../tests/conformance.py), [v1의 19개 목록](../features/auth/scenarios.json) 재사용 | 19 | 네 백엔드에 각각 적용 |
| 혼합 언어 PG | [`SharedPostgresContract`](../tests/postgres_conformance.py) | 8 | 같은 DB를 연결한 네 언어 조합 |
| 같은 언어 두 인스턴스·재시작 | [`restart_checks()`](../tests/postgres_conformance.py) | 4 | 백엔드별 공유 조회·폐기와 순차 재시작 |
| 공통 React | [`auth.spec.ts`](../clients/react/tests/auth.spec.ts) | 8 | 네 백엔드에 각각 적용 |
| 별도 소비 앱 | [`consumer.spec.ts`](../examples/consumer-python-react/tests/consumer.spec.ts) | 3 | 설치한 Python 패키지와 React export |

정적 맵은 42개 논리 시나리오이며 백엔드별 반복을 펼치면 123개 실행 단위입니다. 공통 harness의 [Secure 쿠키 검사](../tests/conformance.py)는 별도로 각 백엔드에 적용됩니다. 이 수치는 실제 통과 횟수가 아닙니다. 브라우저의 정상 로그인·복원·로그아웃은 실제 서버를 호출하며 Unicode 제출·CSRF 거절·401·네트워크·429 UI 분기 일부는 요청 경계에서 응답을 주입합니다. DB 장애·PHC 오류는 별도의 혼합 언어 API 검사에서 확인합니다.

혼합 언어 8개는 교차 조회·폐기, 두 번째 사용자·토큰 해시·실제 Unicode 계정 로그인, 교차 세션 회전·CSRF, 공유 제한·동시 실패, 비활성 사용자·만료, 연결 절단·복구, 비정상 PHC를 다룹니다. 재시작 함수는 언어별 동시 두 인스턴스와 종료 후 재기동을 모두 확인합니다.

```sh
# 정적 계약·소스 연결 검사. 서버나 DB를 실행하지 않는다.
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v2.py --check

# PATH 또는 FEATURE_STANDARDS_PG_BIN의 initdb/pg_ctl로 임시 서버를 소유·종료
uv run --frozen --project tools python tests/postgres_conformance.py --browser
```

외부 전용 DB를 사용할 때는 `FEATURE_STANDARDS_TEST_DATABASE_URL`을 설정합니다. harness는 **`feature_auth` 스키마를 삭제·재생성**하므로 다른 테스트와 DB를 공유하거나 운영 데이터를 넣어서는 안 됩니다. fixture 검사기는 loopback·명시적 포트·`feature_standards_test` 이름과 제한된 URI query를 확인합니다. `PGHOSTADDR`, `PGSERVICE`를 포함한 값이 있는 `PG*` 환경 변수도 거절하므로 비워야 합니다.

개별 언어 테스트에는 `AUTH_TEST_DATABASE_URL`을 사용합니다. 공통 harness용 DB와 분리합니다. [CI 준비 도구](../tests/prepare_postgres.py)는 기준 DB와 언어별 DB를 명시적으로 migrate·seed하며 앱이 실행하는 로직은 아닙니다. 준비 후 구현별 자체 테스트 명령에 해당 DB를 전달하고, Rust의 실제 DB 검사는 `cargo test --locked -- --ignored`로 별도 실행합니다.

[CI](../.github/workflows/ci.yml)는 PostgreSQL 18.6 서비스를 제공하고 언어별 DB, v1·v2 회귀, v3 계정 API·브라우저, Rust TLS와 소비 앱을 검증하도록 정의되어 있습니다. [동일 템플릿](../ci/github-actions.yml)과 함께 유지합니다. 로컬 검증, 원격 커밋, 해당 SHA의 CI 성공, 패키지 게시, 실제 배포를 서로 다른 상태로 기록합니다.
