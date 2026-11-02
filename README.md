# Feature Standards

**AI가 반복해서 구현하는 기능을 공통 명세·스택별 구현·동일한 검증 시나리오로 재사용합니다.**

첫 기능은 로그인·로그아웃·내 정보 조회를 제공하는 인증입니다. Python·Go·Java·Rust 서버는 같은 HTTP 동작을 구현하고, 하나의 React 클라이언트가 각 서버에 연결됩니다.

**0.3.0 계정 생명주기 확장**을 제공합니다. 기본 메모리 `browser-session-v1`, PostgreSQL `browser-session-v2`를 유지하며, `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`로 가입·이메일 확인·비밀번호 재설정을 제공하는 `browser-session-v3`를 선택합니다. 실제 로컬 실행 범위는 [v3 검증 기록](docs/validation-2026-11-02-accounts-v3.md), 커밋별 원격 결과는 [Actions](https://github.com/jongko54/feature-standards/actions)에서 확인합니다. 운영 보안 감사를 받은 제품은 아닙니다.

## 제공 범위

| 구성 | 역할 |
|---|---|
| [v1 명세](features/auth/specification.md) / [OpenAPI](features/auth/openapi.json) / [19개 시나리오](features/auth/scenarios.json) | 환경 설정 사용자 한 명과 프로세스 메모리 세션, 기본 프로필 |
| [v2 명세](features/auth/postgres-session-v2.md) / [OpenAPI](features/auth/openapi-v2.json) / [근거 맵](features/auth/scenarios-v2.json) | PostgreSQL 사용자·세션·실패 기록, 트랜잭션·장애 계약 |
| [v3 명세](features/auth/account-session-v3.md) / [OpenAPI](features/auth/openapi-v3.json) / [근거 맵](features/auth/scenarios-v3.json) | 가입·이메일 확인·비밀번호 재설정과 트랜잭션 outbox |
| [SMTP 전달 계약](features/auth/mail-delivery-v1.md) / [실행 안내](docs/smtp-delivery.md) / [근거 맵](features/auth/mail-scenarios.json) | 선택 워커, 검증된 TLS, 제한된 재시도와 fenced ACK |
| [PostgreSQL DDL](features/auth/postgres/001_initial.sql) / [명시적 DB 도구](tools/auth_db.py) | schema version 1 마이그레이션과 별도 데모 seed |
| [Python / FastAPI](implementations/python-fastapi) | `feature_auth` 설치 패키지, 앱 factory와 인증 dependency |
| [Go / net/http](implementations/go-net-http), [Java / Spring](implementations/java-spring), [Rust / Axum](implementations/rust-axum) | HTTP 어댑터와 서비스·저장소 경계 |
| [React / TypeScript](clients/react/README.md) | 공통 화면과 `@ugauga/feature-standards-react-auth/api` export |
| [별도 Python+React 소비 프로젝트](examples/consumer-python-react/README.md) | 인증 코드를 복사하지 않고 패키지를 가져오는 보호 API 예제 |
| [AI 적용 지침](skills/integrate-auth/SKILL.md) | 대상 프로젝트 조사·적용·검증 |
| [통합 manifest](feature-standards.json) / [AI 통합 안내](docs/ai-integration.md) | 5개 스택의 공개 API·프로필·의존성·소비 예제·검증 명령 |

v2의 구성은 [PostgreSQL 사용 안내](docs/postgres-v2.md), v3의 마이그레이션·메일·TLS·검증 범위는 [계정 사용 안내](docs/account-v3.md), 호환성 정책은 [버전 문서](docs/versioning.md)를 따릅니다.

## 빠르게 실행하기

선택한 서버의 도구만 준비하면 됩니다: Python 3.12 이상과 [uv](https://docs.astral.sh/uv/), Go 1.26 이상, Java 21 이상, 또는 Rust/Cargo 1.93.1 이상. React에는 Node.js 22.12 이상과 npm이 필요합니다. 전체 검증은 네 도구 체인이 모두 필요하며 브라우저 실행은 Node.js 24와 Chromium을 기준으로 합니다.

먼저 메모리 데모 서버 하나를 실행합니다. 공개 계정은 `demo@example.com` / `correct-horse-battery-staple`입니다.

```sh
# Python
cd implementations/python-fastapi
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
# 또는 Go
cd implementations/go-net-http
AUTH_DEMO=true AUTH_COOKIE_SECURE=false go run .
```

```sh
# 또는 Java
cd implementations/java-spring
./mvnw -q -DskipTests package
AUTH_DEMO=true AUTH_COOKIE_SECURE=false java -jar target/auth-server.jar
```

```sh
# 또는 Rust
cd implementations/rust-axum
cargo build --locked
AUTH_DEMO=true AUTH_COOKIE_SECURE=false target/debug/feature-standards-auth
```

다른 터미널에서 공통 화면을 실행하고 **http://127.0.0.1:5173** 을 엽니다.

```sh
cd clients/react
npm ci
npm run dev
```

Vite가 `/auth`를 서버로 프록시하므로 CORS 설정을 추가하지 않습니다. 다른 서버 포트는 `AUTH_API_TARGET=http://127.0.0.1:다른포트 npm run dev`로 선택합니다. `localhost`와 `127.0.0.1`을 혼용하면 Origin이 달라집니다.

### PostgreSQL로 실행하기

이미 만든 전용 로컬 DB의 PostgreSQL URI를 `AUTH_DATABASE_URL` 환경 변수에 설정한 뒤, 저장소 루트에서 명시적으로 준비합니다.

```sh
uv sync --frozen --project tools
uv run --frozen --project tools python tools/auth_db.py migrate
# 공개 계정 두 명이 필요한 로컬 데모에서만 실행
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

그다음 서버 실행에 `AUTH_STORE=postgres`와 설정한 `AUTH_DATABASE_URL`을 전달합니다. 예를 들어 Python은 다음과 같습니다.

```sh
cd implementations/python-fastapi
AUTH_STORE=postgres AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

앱은 **자동 DDL·seed·메모리 fallback을 하지 않습니다.** DB 모드의 `AUTH_DEMO=true`는 로컬 HTTP·쿠키 예외만 허용하며, 계정을 만들거나 비밀번호를 바꾸지 않습니다. `AUTH_USER_EMAIL`과 `AUTH_USER_PASSWORD`도 DB 모드에서는 사용하지 않습니다. seed는 기존 사용자와 비밀번호를 덮어쓰지 않습니다.

네 언어의 공통 로컬 URI는 명시적인 `sslmode=disable`을 사용합니다. Rust 원격 연결은 `sslmode=verify-full`로 인증서 체인과 hostname을 검증하며, 명시적 `sslrootcert` 또는 플랫폼 신뢰 루트를 사용합니다. 약한 모드와 TLS 거절 후 평문 재시도는 허용하지 않습니다. 실제 운영 DB의 인증·권한·용량 검토는 별도 범위입니다.

### 계정 생명주기 선택

v3는 schema 2를 사용합니다. 기존 schema 1 서버를 먼저 중단하고 백업·권한을 확인한 뒤 명시적으로 이관합니다. 새 DB도 같은 도구가 schema 1을 만든 후 2로 올립니다.

```sh
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
# 공개 테스트 계정이 필요한 로컬 DB에서만:
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

서버에 `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`와 `AUTH_DATABASE_URL`을 전달하고, React 개발 서버에 `VITE_AUTH_ACCOUNT_LIFECYCLE=true`를 지정합니다. 기본 false는 기존 화면과 프로필을 유지합니다. 신규 계정은 이메일 확인 전 로그인할 수 없고, 비밀번호 재설정은 모든 기존 세션을 원자적으로 폐기합니다. 관리자 비활성 상태는 확인·재설정으로 바뀌지 않습니다.

이메일은 DB outbox에 저장합니다. [선택 SMTP 워커](tools/mail_worker.py)는 별도 SMTP 설정으로 TLS 전달·재시도·claim/ACK를 처리합니다. 실제 제공자 계정과 발신 주소는 자동 설정하지 않으며, 현재 운영 외부 발송을 실행했다는 의미는 아닙니다. [로컬 수신 도구](tools/mail_capture.py)는 아직 SMTP가 소유하지 않은 테스트 메시지만 새 mode 0600 파일로 옮깁니다. outbox와 수신 파일의 원문 token은 민감한 bearer credential입니다. 자세한 migration·환경변수·운영 경계는 [SMTP 안내](docs/smtp-delivery.md)를 따릅니다.

## 다른 프로젝트에서 사용하기

AI와 도구는 루트 `feature-standards.json`에서 스택과 프로필을 선택합니다. 예를 들어 `uv run --frozen --project tools python tools/auth_catalog.py --stack go --profile browser-session-v1`은 필요한 명세·공개 API·예제·명령만 JSON으로 반환하며 명령을 실행하지 않습니다. `.agents/skills/integrate-auth`는 원본 스킬을 가리키므로 Codex가 저장소에서 자동 발견할 수 있습니다. 실제 모델 통합은 네 백엔드×두 조건 8/8 성공했으며, 시간·토큰 절감 효과는 입증하지 못했습니다. [실행 근거](docs/validation-ai-2026-11-03.md)와 [AI 통합 안내](docs/ai-integration.md)를 확인합니다.

| 스택 | 재사용 경계 | 별도 소비 프로젝트 |
|---|---|---|
| Python | wheel, `create_app`·`current_user` | [Python+React](examples/consumer-python-react/README.md) |
| Go | `auth` 패키지, `NewServer`·`CurrentUser` | [Go](examples/consumer-go/README.md) |
| Java | 일반 `library` classifier JAR, `AuthService`·`AuthFilter` | [Java](examples/consumer-java/README.md) |
| Rust | path crate, `AuthService::from_config`·`current_user` | [Rust](examples/consumer-rust/README.md) |
| React | `@ugauga/feature-standards-react-auth/api` | [Python+React](examples/consumer-python-react/README.md) |

독립 Go·Java·Rust 소비 검사는 메모리 v1의 보호 API·세션 폐기를 실제 실행합니다. 해당 예제의 PostgreSQL v2/v3·브라우저 검증을 대신하지 않습니다. 참조 서버들의 공통 v1/v2/v3 검사는 별도 CI 단계입니다. 서버 패키지는 로컬 소비 예제로 제공하며, React API는 [npm 0.1.0](https://www.npmjs.com/package/@ugauga/feature-standards-react-auth)에 공개했습니다. [배포·설치 검증 기록](docs/npm-release.md)을 확인합니다.

Python 배포 이름은 `feature-standards-python-auth`, import 이름은 `feature_auth`입니다. [Python 프로젝트](implementations/python-fastapi/pyproject.toml)는 실제 wheel 빌드 설정을 제공하고, [소비 예제](examples/consumer-python-react/pyproject.toml)는 uv path dependency로 설치합니다. 공개 경계는 `create_app()`과 `current_user(request)`입니다.

```python
from typing import Annotated
from fastapi import Depends
from feature_auth import create_app, current_user

app = create_app()


@app.get("/api/profile")
def profile(user: Annotated[dict[str, str], Depends(current_user)]):
    return {"user": user}
```

React 소비 앱은 공개 export를 사용합니다.

```sh
npm install @ugauga/feature-standards-react-auth
```

```ts
import { createAuthApi, type AuthSession } from '@ugauga/feature-standards-react-auth/api';

const auth = createAuthApi();
const session: AuthSession | null = await auth.me();
```

[별도 예제](examples/consumer-python-react/README.md)는 보호 API, 로그인·새로고침 복원·로그아웃, 두 번째 사용자 분리를 다룹니다. 체크아웃의 현재 소스를 검증하도록 React file dependency를 사용하며 npm 설치와는 별도입니다. Python wheel은 로컬 의존성으로 제공합니다. 실행 절차는 [v2 안내](docs/postgres-v2.md#별도-소비-앱)를 확인합니다.

## 같은 기준으로 검증하기

SMTP 확장의 실제 실행 범위는 [SMTP 검증 기록](docs/validation-smtp-2026-11-02.md)에 정리했습니다.

저장소 루트에서 실행합니다. 계약 검사는 스키마와 테스트 소스의 연결을 검증하며 서버 동작을 실행하지 않습니다.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v2.py --check
uv run --frozen --project tools python tools/generate_openapi_v3.py --check
uv run --frozen --project tools python -m unittest discover -s tests -p 'test_*.py' -v

uv run --frozen --project implementations/python-fastapi pytest implementations/python-fastapi/tests
go -C implementations/go-net-http test -race ./...
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml test
cargo test --locked --manifest-path implementations/rust-axum/Cargo.toml

python3 tests/conformance.py --backend all --browser
```

공통 브라우저 검사는 먼저 `clients/react`에서 `npm ci`, `npm test`, `npm run build`, `npx playwright install chromium`을 실행해야 합니다. 포트 5173이 비어 있어야 합니다. v1 API만 검사하려면 `--browser`를 빼고, 한 언어만 검사하려면 `--backend python|go|java|rust`를 선택합니다.

v2 전체 검사는 `initdb`·`pg_ctl`이 있는 PostgreSQL 서버 바이너리 또는 명시한 전용 테스트 DB를 사용합니다. 현재 로컬 검증 환경은 **PostgreSQL 18.6**입니다.

```sh
# PATH의 PostgreSQL 서버 바이너리로 전용 임시 DB를 시작·종료
uv run --frozen --project tools python tests/postgres_conformance.py --browser
uv run --frozen --project tools python tests/account_conformance.py --browser

# 별도 Python/React 예제 의존성 준비
uv sync --frozen --project examples/consumer-python-react
npm --prefix examples/consumer-python-react ci
npm --prefix examples/consumer-python-react run build
uv run --frozen --project tools python tests/consumer_conformance.py
```

서버 바이너리 경로를 직접 지정하려면 `FEATURE_STANDARDS_PG_BIN`을 사용합니다. 기존 전용 DB는 `FEATURE_STANDARDS_TEST_DATABASE_URL`로 선택할 수 있습니다. 두 harness는 해당 DB의 `feature_auth` 스키마를 초기화하므로 **loopback의 이름이 `feature_standards_test`로 시작하는 작업 전용 DB만** 사용해야 합니다. 자세한 자체 DB 검사와 근거 맵은 [v2 안내](docs/postgres-v2.md#검증과-근거-맵)를 따릅니다.

### GitHub Actions

[CI 워크플로](.github/workflows/ci.yml)와 [동일 템플릿](ci/github-actions.yml)은 PostgreSQL 18.6 서비스, 언어별 schema 1·2 분리 DB 자체 테스트, v1·v2·v3 API·브라우저, 계정 경합·SQL gateway, Rust TLS, 별도 소비 앱과 SMTP 전달·캡처 경합을 실행하도록 정의되어 있습니다. 메일 검사에는 worker/capture/integration DB를 각각 사용합니다. 워크플로를 바꾸면 두 파일을 함께 갱신합니다. 정의가 존재하는 상태와 [해당 커밋의 원격 실행 성공](https://github.com/jongko54/feature-standards/actions)은 구분해야 합니다.

## API와 적용 경계

| 요청 | 성공 | 대표 실패 |
|---|---|---|
| `POST /auth/login` | `200` + 세션 쿠키·사용자·CSRF 토큰 | `400`, `401`, `403`, `413`, `415`, `429`, v2 `503` |
| `GET /auth/me` | `200` + 사용자·CSRF 토큰 | `401`, v2 `503` |
| `POST /auth/logout` | 본문 없는 `204`, 서버 세션 삭제·쿠키 제거 | `403`, v2 `503` |
| `GET /healthz` | `200` + 선택한 프로필·구현 이름 | v2 저장소 실패 `503` |

상태 변경에는 정확한 Origin이 필요합니다. v2의 만료 전 저장 세션은 사용자의 enabled 여부와 무관하게 로그아웃 CSRF를 요구합니다. 잘못된 CSRF는 세션을 유지하며, DB 실패를 로그아웃 성공으로 표현하지 않습니다. 쿠키의 `Secure` 기본값은 활성화입니다.

메모리 상태는 재시작하면 사라지고, v2/v3는 같은 DB의 세션과 실패 기록을 공유합니다. reverse proxy 뒤에서는 peer IP가 프록시로 보입니다. 운영 적용에는 DB 권한·백업·용량, 신뢰 프록시, HTTPS, 비밀 관리·관측과 outbox 접근·암호화·보존 검토가 필요합니다. 역할 관리·MFA는 제공하지 않습니다. SMTP 어댑터의 DATA 수락과 DB ACK는 실제 수신함 도착과 구분합니다.

명세는 저장소의 실험적 규약이며 공인 국제 표준이 아닙니다. 기존 v1 검증 기록은 [2026-11-01 문서](docs/validation-2026-11-01.md), 참여 방법은 [CONTRIBUTING.md](CONTRIBUTING.md), 보안 범위는 [SECURITY.md](SECURITY.md), 선행 프로젝트는 [연구 문서](docs/research.md)를 확인합니다. 라이선스는 [MIT](LICENSE)입니다.
