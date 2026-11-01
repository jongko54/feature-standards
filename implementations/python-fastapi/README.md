# Python / FastAPI

[`browser-session-v1`](../../features/auth/specification.md)의 단일 프로세스 참조 구현이다. Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요하다. 의존성은 `uv.lock`에 고정한다.

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
uv run --locked ruff check app.py tests
uv run --locked ruff format --check app.py tests
```

저장소 루트의 공통 테스트는 `python3 tests/conformance.py --backend python`으로 실행한다.

자체 테스트는 로그인·세션 재발급·기존 쿠키 재사용·CSRF·origin·입력 경계·고정 만료·IP 제한·설정 검증을 다룬다. 테스트 시간은 주입한 monotonic clock으로 움직이며 실제 세션 로직을 검증한다. Argon2 검증은 테스트에서도 실제 라이브러리를 사용한다.

## 적용 범위

- 비밀번호는 시작 시 Argon2id로 해싱하고 세션 ID와 CSRF 토큰은 각각 독립적인 32바이트 난수에서 생성한다.
- 이메일은 계약에 지정한 ASCII 공백만 제거하고 ASCII 대문자만 소문자로 바꾼다. U+001C, NBSP, `İ` 같은 나머지 Unicode 문자는 요청과 환경 설정에서 동일하게 보존한다.
- 세션과 실패 기록은 메모리 저장이며, 각 요청에서 만료 레코드를 정리한다. 잠금으로 상태 갱신을 보호하고 비밀번호 검증도 직렬화한다.
- 개발 환경에서 여러 worker를 켜면 worker마다 세션이 달라진다. **이 구현은 worker 한 개에서만 실행한다.** 다중 인스턴스에는 공유 저장소와 전역 제한이 필요하다.
- 데모 외 실행은 `AUTH_USER_EMAIL`, `AUTH_USER_PASSWORD`, HTTPS `AUTH_ALLOWED_ORIGIN`, `AUTH_COOKIE_SECURE=true`를 요구한다. 이는 참조 구현의 단일 사용자 설정이며 회원 관리 기능을 제공하지 않는다.
- 이 서버를 직접 외부에 노출하기 전에 reverse proxy의 TLS, 요청 제한, 운영 세션 저장소, 감사 정책을 적용해야 한다. 프로필 적합성 테스트 통과는 운영 보안 감사 완료를 뜻하지 않는다.

## 참고

- [FastAPI lifespan 테스트](https://fastapi.tiangolo.com/advanced/testing-events/)
- [argon2-cffi PasswordHasher API](https://argon2-cffi.readthedocs.io/en/stable/api.html)
