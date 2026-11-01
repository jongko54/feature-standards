# Python / FastAPI

[`browser-session-v1`](../../features/auth/specification.md) 메모리 모드와 [`browser-session-v2`](../../features/auth/postgres-session-v2.md) PostgreSQL 모드를 제공한다. Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요하다. 의존성은 `uv.lock`에 고정한다.

## 실행

저장소 루트에서:

```sh
cd implementations/python-fastapi
uv sync --locked
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 \
uv run --locked uvicorn app:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

데모 계정은 `demo@example.com` / `correct-horse-battery-staple`이다. React 개발 서버는 `/auth` 요청을 이 서버로 프록시한다. API만 호출할 때도 로그인과 로그아웃에 위 `Origin` 헤더가 필요하다.

uvicorn의 `--host`, `--port`는 `AUTH_HOST`, `AUTH_PORT`에 자동 연결되지 않는다. 실행 도구가 환경 변수를 설정한다면 해당 값을 CLI 인자로도 전달한다. `--no-proxy-headers`로 TCP peer 기반 제한을 유지한다. 클라이언트가 보낸 `X-Forwarded-For` 헤더를 신뢰해서는 안 된다.

## 검증

이 디렉터리에서:

```sh
uv run --locked pytest -q
uv run --locked ruff check app.py feature_auth tests
uv run --locked ruff format --check app.py feature_auth tests
```

저장소 루트의 공통 테스트는 `python3 tests/conformance.py --backend python`으로 실행한다.

자체 테스트는 로그인·세션 재발급·기존 쿠키 재사용·CSRF·origin·입력 경계·고정 만료·IP 제한·설정 검증을 다룬다. 테스트 시간은 주입한 monotonic clock으로 움직이며 실제 세션 로직을 검증한다. Argon2 검증은 테스트에서도 실제 라이브러리를 사용한다.

## 적용 범위

- 메모리 모드의 비밀번호는 시작 시 Argon2id로 해싱하고 세션 ID와 CSRF 토큰은 각각 독립적인 32바이트 난수에서 생성한다.
- 이메일은 계약에 지정한 ASCII 공백만 제거하고 ASCII 대문자만 소문자로 바꾼다. U+001C, NBSP, `İ` 같은 나머지 Unicode 문자는 요청과 환경 설정에서 동일하게 보존한다.
- 기본 `AUTH_STORE=memory`의 세션과 실패 기록은 메모리 저장이며, 각 요청에서 만료 레코드를 정리한다. 잠금으로 상태 갱신을 보호하고 비밀번호 검증도 직렬화한다.
- 메모리 모드는 worker 한 개에서 실행한다. PostgreSQL 모드는 사용자·세션·실패 기록을 같은 DB에 공유하므로 여러 worker와 다른 언어 서버가 같은 상태를 관찰한다.
- 메모리 모드의 데모 외 실행은 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS `AUTH_ALLOWED_ORIGIN`, `AUTH_COOKIE_SECURE=true`를 요구한다. 이는 참조 구현의 단일 사용자 설정이며 회원 관리 기능을 제공하지 않는다.
- 이 서버를 직접 외부에 노출하기 전에 reverse proxy의 TLS, 요청 제한, 운영 세션 저장소, 감사 정책을 적용해야 한다. 프로필 적합성 테스트 통과는 운영 보안 감사 완료를 뜻하지 않는다.

## PostgreSQL 모드

앱 시작 전에 루트의 `tools/auth_db.py migrate`로 기준 DDL을 적용한다. 로컬 데모 계정은 별도의 `seed-demo --confirm-demo` 명령으로만 넣는다. 앱은 DDL·seed를 실행하지 않는다.

```sh
AUTH_STORE=postgres AUTH_DATABASE_URL='postgresql://user@127.0.0.1/feature_standards_test?sslmode=disable' \
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

DB 모드는 `AUTH_USER_EMAIL`과 `AUTH_USER_PASSWORD`를 사용하지 않는다. 시작 시 schema version 1과 연결 가능 여부를 확인한다. 런타임 DB 장애는 `503 STORAGE_UNAVAILABLE`이며 새 쿠키를 발급하지 않는다. DB URL과 연결 오류 원문을 응답·로그에 출력하지 않는다.

`core.AuthStore`의 원자적 인증 작업을 `AuthService`가 사용하고, `memory.AuthState`와 `postgres.PostgresStore`가 같은 경계에 연결된다. FastAPI 라우트는 SQL이나 저장소 구현을 참조하지 않는다. PostgreSQL은 psycopg 3을 사용하며 각 작업이 연결·트랜잭션을 소유한다. peer advisory lock, DB 시각, SHA-256 토큰 해시, 엄격한 PHC 형식과 커밋 후 응답을 적용한다.

실제 DB 자체 검사는 seed된 전용 loopback DB에서만 실행한다. 세션과 실패 기록을 초기화하므로 테스트 DB 이름은 `feature_standards_test`로 시작해야 한다.

```sh
AUTH_TEST_DATABASE_URL='postgresql://user@127.0.0.1/feature_standards_test?sslmode=disable' \
uv run --frozen pytest -q
```

## 다른 Python 프로젝트에서 사용

패키지 이름은 `feature-standards-python-auth`이고 import 이름은 `feature_auth`이다. uv path dependency 또는 빌드한 wheel을 설치한 후 다음처럼 사용한다. `create_app()`은 앱 lifespan 시작 시 환경 설정을 읽는다. `app:app` 실행과 기존 v1 import는 계속 지원한다.

```python
from typing import Annotated
from fastapi import Depends
from feature_auth import create_app, current_user

app = create_app()


@app.get("/private")
def private(user: Annotated[dict, Depends(current_user)]):
    return {"user": user}
```

`current_user(request)`를 직접 호출할 수도 있다. 인증된 사용자 dict를 반환하며 인증 실패는 `401 UNAUTHENTICATED`, 저장소 실패는 `503 STORAGE_UNAVAILABLE`로 변환한다. 어댑터 주입은 `create_app(settings=..., store=...)`를 사용한다. 동일 서비스를 붙인 별도 FastAPI 앱에서는 이 패키지의 오류 처리와 lifespan도 통합해야 하므로 제공 factory 사용을 기본으로 한다.

## 참고

- [FastAPI lifespan 테스트](https://fastapi.tiangolo.com/advanced/testing-events/)
- [argon2-cffi PasswordHasher API](https://argon2-cffi.readthedocs.io/en/stable/api.html)

- [psycopg 트랜잭션과 연결 context](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
