# @ugauga/feature-standards-react-auth

React·브라우저 TypeScript 앱에서 사용하는 세션 인증 API 클라이언트다. 로그인·세션 복원·로그아웃과 가입·이메일 확인·비밀번호 재설정을 제공한다.

## 설치

```sh
npm install @ugauga/feature-standards-react-auth
```

ESM JavaScript와 TypeScript 선언을 제공한다. Node.js 도구 환경은 22.12 이상이다. 브라우저의 fetch·Response를 사용하며 런타임 npm 의존성은 없다.

## 로그인·복원·로그아웃

```ts
import {
  createAuthApi,
  ApiError,
  type AuthSession,
} from '@ugauga/feature-standards-react-auth/api';

const auth = createAuthApi();
const restored: AuthSession | null = await auth.me();

try {
  const session = await auth.login('user@example.com', password);
  // React state 등 메모리에 사용자와 CSRF token을 보관한다.
  await auth.logout(session.csrfToken);
} catch (error) {
  if (error instanceof ApiError) {
    console.error(error.status, error.code, error.retryAfter);
  }
}
```

루트 import `@ugauga/feature-standards-react-auth`도 같은 API를 export한다. 기본 인스턴스 `authApi`도 사용할 수 있다.

`me()`는 `401 UNAUTHENTICATED`일 때 null을 반환한다. 네트워크·다른 API 오류는 reject하므로 로그인 상태와 구분해서 처리한다. `logout()`은 서버가 세션을 폐기한 뒤에 완료되며 실패하면 reject한다.

`AuthSession`의 형태는 다음과 같다. 세션 ID는 서버가 발급한 HttpOnly 쿠키로만 전달된다.

```ts
interface AuthSession {
  user: { id: string; email: string };
  csrfToken: string;
}
```

## 계정 생명주기

서버가 `browser-session-v3`를 지원할 때 다음 메서드를 사용한다. 성공은 Promise<void>다.

```ts
await auth.register(email, password);
await auth.requestVerification(email);
await auth.confirmVerification(token);
await auth.requestPasswordReset(email);
await auth.confirmPasswordReset(token, newPassword);
```

| 메서드 | HTTP 경로 | 성공 |
|---|---|---|
| login | POST /auth/login | 200 + AuthSession |
| me | GET /auth/me | 200 + AuthSession, 비로그인 null |
| logout | POST /auth/logout | 204 |
| register | POST /auth/register | 202 |
| requestVerification | POST /auth/email-verification/request | 202 |
| confirmVerification | POST /auth/email-verification/confirm | 204 |
| requestPasswordReset | POST /auth/password-reset/request | 202 |
| confirmPasswordReset | POST /auth/password-reset/confirm | 204 |

## 서버와 앱 설정

앱과 같은 origin에서 위 경로를 제공하는 서버가 필요하다. 기본 요청은 상대 경로·credentials: same-origin·cache: no-store를 사용한다. POST의 JSON과 로그아웃 X-CSRF-Token을 구성하며 Origin은 브라우저가 전달한다. 서버에서 정확한 Origin·CSRF·쿠키·세션 폐기와 권한을 검증해야 한다.

인증 오류는 `{ error: { code: string } }` 형식이며 `ApiError.status`, `code`, `retryAfter`로 구분한다. Retry-After는 초 단위 정수로 해석한다. 테스트에는 `createAuthApi(fetcher)`로 fetch 구현을 주입할 수 있다.

React 화면은 이 API를 호출해 구성한다. 세션 ID·비밀번호·확인/reset token을 localStorage에 저장하지 않는다. 확인/reset 링크를 사용하는 앱은 fragment에서 token을 읽고 주소에서 제거한 뒤 명시적인 사용자 동작으로 confirm을 호출한다.

## 저장소에서 개발하기

[소스 저장소](https://github.com/jongko54/feature-standards)의 clients/react에서 참조 화면과 네 백엔드의 공통 검증을 제공한다. 참조 UI 실행·브라우저 검사·v3 설정은 저장소의 [개발 안내](https://github.com/jongko54/feature-standards/blob/main/clients/react/DEVELOPMENT.md)를 따른다.

```sh
npm ci
npm test
npm run build
npm run check:package
```

패키지 검사는 실제 tarball의 다섯 파일을 확인하고 별도 프로젝트에 설치해 ESM import·런타임 요청·TypeScript 선언을 검증한다. MIT 라이선스다.
