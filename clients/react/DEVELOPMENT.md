# React 인증 참조 클라이언트

같은 `browser-session-v1`, PostgreSQL `browser-session-v2` 또는 선택적 [계정 생명주기 v3](../../features/auth/account-session-v3.md)를 제공하는 Python·Go·Java·Rust 서버에 연결하는 React/TypeScript 화면이다. 기본 로그인·복원·상태 확인·로그아웃 화면을 유지하며, v3 선택 시 가입·이메일 확인·비밀번호 재설정 화면을 추가한다. 세션 ID는 HttpOnly 쿠키로만 전달하고 CSRF·계정 token은 React 메모리에만 둔다. 브라우저 저장소에는 토큰을 저장하지 않는다.

## 로컬 실행

Node.js 22.12 이상이 필요하다. 먼저 원하는 서버를 데모 모드로 시작한다. 서버의 `AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173`, `AUTH_DEMO=true`, `AUTH_COOKIE_SECURE=false` 설정이 필요하다.

```sh
npm ci
AUTH_API_TARGET=http://127.0.0.1:8000 npm run dev
```

`http://127.0.0.1:5173`으로 접속한다. Vite는 `/auth`와 `/healthz`를 선택한 서버로 프록시한다. `Origin`은 원래 브라우저 주소로 유지한다. 서버만 교체하면 동일한 UI를 사용할 수 있다.

데모 계정은 `demo@example.com` / `correct-horse-battery-staple`이다. v1은 명시적 데모 모드에서 제공하며, v2는 별도 seed 도구로 직접 생성해야 한다. v2 앱은 데모 모드에서도 DB 계정을 자동 생성하지 않는다.

## 계정 화면 v3 선택

먼저 [v3 실행 안내](../../docs/account-v3.md)에 따라 전용 DB를 schema 2로 명시적으로 이관하고 서버에 `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`를 설정한다. 클라이언트의 flag는 Vite 개발 서버 또는 빌드 시 지정한다. 기본 false는 기존 화면을 유지한다.

```sh
VITE_AUTH_ACCOUNT_LIFECYCLE=true AUTH_API_TARGET=http://127.0.0.1:8000 npm run dev
# 같은 계정 화면을 포함한 정적 산출물:
VITE_AUTH_ACCOUNT_LIFECYCLE=true npm run build
```

가입은 일반 접수 응답을 표시하며 자동 로그인하지 않는다. 새 계정은 이메일 확인 후 로그인할 수 있다. 로컬 메일은 저장소 루트의 [수신 도구](../../tools/mail_capture.py)로 전용 테스트 DB에서 새 mode 0600 파일에만 기록한다. 실제 외부 메일과 공개 HTTP 수신함은 제공하지 않는다. DB outbox와 수신 파일의 원문 token은 민감한 capability이며 로그·이슈·CI artifact에 올리지 않는다.

확인·재설정 링크는 URL fragment로 token을 전달한다. 화면이 메모리로 읽은 뒤 주소에서 제거하고, 페이지 로드만으로 확인하지 않는다. 사용자 버튼이 POST를 보내며 재설정 성공은 모든 기존 서버 세션을 폐기한다. 로컬 캡처 실행과 수신 파일 사용은 [메일 수신 안내](../../docs/account-v3.md#로컬-메일-수신)를 따른다.

## 다른 프로젝트에서 가져오기

`package.json`에서 `@ugauga/feature-standards-react-auth`를 이 디렉터리의 file dependency로 지정하고 `@ugauga/feature-standards-react-auth/api`에서 `authApi`, `createAuthApi`, `AuthSession`, `ApiError`를 import할 수 있다. API 모듈은 React 화면과 분리되어 있다. 실제 별도 프로젝트 통합은 [소비 앱 예제](../../examples/consumer-python-react/README.md)를 참고한다. 공개 npm 배포본은 `npm install @ugauga/feature-standards-react-auth@0.1.0`으로 설치하며, file dependency는 이 checkout의 현재 소스를 검증하는 용도다. [배포 기록](../../docs/npm-release.md)에 실제 registry 설치 결과가 있다.

## 검증

```sh
npm test
npm run build
npx playwright install chromium
# 위의 서버와 Vite를 실행한 상태에서:
BASE_URL=http://127.0.0.1:5173 npm run test:e2e
```

단위 테스트는 API 요청 규격과 성공·오류 응답 해석을 검증한다. 브라우저 테스트는 실제 서버에서 로그인·쿠키·복원·로그아웃·잘못된 비밀번호를 검증하고, 네트워크/CSRF/만료/429 응답을 경계에서 주입해 UI의 실패 처리를 확인한다. 실제 서버의 만료·CSRF·rate limit 검증은 루트 공통 적합성 테스트가 담당한다.

v3의 [계정 브라우저 설정](playwright.accounts.config.ts)은 `account-tests`를 실행한다. 단독 실행에는 v3 서버·flag가 켜진 Vite와 `FEATURE_STANDARDS_TEST_DATABASE_URL`의 같은 전용 DB가 필요하다.

```sh
BASE_URL=http://127.0.0.1:5173 npx playwright test --config playwright.accounts.config.ts
```

저장소 루트에서 하네스가 서버·클라이언트·작업 전용 DB를 관리하도록 실행할 수도 있다. 이 하네스는 스키마를 초기화하므로 운영 DB에는 실행하지 않는다. 실제 가입→로컬 수신 링크→확인→로그인→재설정→이전 세션 거절 흐름을 네 서버에 적용하며 결과는 해당 실행 기록으로 확인한다.

```sh
uv run --frozen --project tools python tests/account_conformance.py --browser
```

## 동작과 적용 경계

- 초기 `401 UNAUTHENTICATED`는 정상 비로그인 상태로 처리한다. 네트워크 실패는 별도로 표시한다.
- 로그아웃 API가 성공하기 전에는 로그인 상태를 지우지 않는다. 실패하면 사용자 정보가 유지된다.
- 새로고침 시 `/auth/me`로 세션과 CSRF 토큰을 복원한다. `세션 상태 확인`은 만료 상태를 반영하며 서버 세션 수명을 연장하지 않는다.
- 이메일 입력은 `type="text"`와 `inputMode="email"`을 사용한다. 브라우저의 ASCII 중심 이메일 검증으로 계약이 허용하는 Unicode 이메일을 차단하지 않고, 최종 형식·바이트 길이는 서버가 검증한다.
- Vite 프록시는 개발용이다. 빌드 결과를 배포할 때에는 `/auth`를 동일 origin의 서버로 전달하는 reverse proxy와 HTTPS가 필요하다.
- `npm run preview`는 4173 포트를 사용한다. 미리보기에서 인증하려면 서버의 허용 origin도 정확히 `http://127.0.0.1:4173`으로 맞춘다.
- 인증 계약과 상태 처리를 보존하면서 CSS와 화면 문구를 바꿀 수 있다. 로그인 여부만으로 서버 권한 검사를 대체하지 않는다.
