# 별도 Python + React 소비 앱

For the independent Python, Go, Java and Rust PostgreSQL v2/v3 matrix, see
[Independent PostgreSQL consumer profiles](PROFILE_TESTS.md).

인증 코드를 복사하지 않고 두 의존성을 가져오는 예제다. Python은 `pyproject.toml`의 path source에서 `feature-standards-python-auth` wheel을 설치하고 `create_app`, `current_user`를 import한다. React는 현재 checkout의 npm file dependency에서 `@ugauga/feature-standards-react-auth/api`를 import한다. 공개 npm 버전은 `npm install @ugauga/feature-standards-react-auth@0.1.0`으로 설치할 수 있다. 이 예제는 현재 소스를 검증하도록 file dependency를 유지하며, 저장소 밖으로 옮길 때 Python 경로와 React 패키지 출처를 맞춘다. [배포 검증 기록](../../docs/npm-release.md)을 참고한다.

`/api/profile`은 이 프로젝트가 추가한 보호 API다. `Depends(current_user)`가 공통 저장소의 세션을 검증하고 인증된 사용자만 반환한다. 앱에서 사용자를 seed하거나 별도 세션 저장소를 만들지 않는다.

## 자동 검증

저장소 루트에서 실행한다. Python 3.12+, uv, Node.js 22.12+, PostgreSQL 서버 바이너리 또는 전용 테스트 DB가 필요하다.

```sh
uv sync --frozen --project tools
uv sync --frozen --project examples/consumer-python-react
npm --prefix examples/consumer-python-react ci
npm --prefix examples/consumer-python-react run build
npm --prefix examples/consumer-python-react exec -- playwright install chromium
uv run --frozen --project tools python tests/consumer_conformance.py
```

하네스는 PostgreSQL 서버 바이너리로 임시 DB를 만들고 종료한다. 별도 경로는 `FEATURE_STANDARDS_PG_BIN`으로 지정한다. 기존 작업 전용 DB를 쓰려면 `FEATURE_STANDARDS_TEST_DATABASE_URL`을 지정한다. 이 경우 해당 DB의 `feature_auth` 스키마를 재생성하므로 데이터가 없는 테스트 DB만 사용한다. 이름은 `feature_standards_test`로 시작하는 ASCII 이름, 주소는 loopback, 포트는 명시해야 한다. URI query는 `sslmode=disable`만 허용하고 `PG*` 환경 변수는 비워야 한다.

검증은 비인증 접근 거절, 로그인·새로고침·보호 API·로그아웃 후 원본 쿠키 거절, 두 번째 사용자 프로필의 세 시나리오를 실제 Chromium에서 실행한다. 포트 5174는 비어 있어야 한다.

## 수동 실행

먼저 작업용 PostgreSQL DB를 준비하고 저장소 루트에서 아래 명시적 도구로 스키마와 공개 데모 계정을 만든다. `AUTH_DATABASE_URL`은 로컬 환경에 설정하며 파일을 커밋하지 않는다.

```sh
uv run --frozen --project tools python tools/auth_db.py migrate
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

그다음 이 디렉터리의 두 터미널에서 실행한다. 서버 터미널에도 같은 `AUTH_DATABASE_URL`이 필요하다.

```sh
AUTH_STORE=postgres AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5174 \
uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
AUTH_API_TARGET=http://127.0.0.1:8000 npm run dev
```

`http://127.0.0.1:5174`에서 공개 데모 계정 `demo@example.com` / `correct-horse-battery-staple`, 또는 `other@example.com` / `other-correct-horse-password`를 사용한다. Vite 프록시는 개발용이며 운영에서는 HTTPS와 같은 origin의 reverse proxy를 설정해야 한다.
