# @ugauga/feature-standards-react-auth

A typed session authentication API client for React and browser TypeScript applications. Supports login, session restoration, logout, registration, email verification, and password reset.

Part of [Feature Standards](https://github.com/jongko54/feature-standards) by [jongko54](https://github.com/jongko54).

## Installation

```sh
npm install @ugauga/feature-standards-react-auth
```

The package includes ESM JavaScript and TypeScript declarations, with no runtime npm dependencies. It uses the browser's fetch and Response APIs. Node.js tooling requires version 22.12 or later.

## Login, restore, and log out

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
  // Keep the user and CSRF token in application memory, such as React state.
  await auth.logout(session.csrfToken);
} catch (error) {
  if (error instanceof ApiError) {
    console.error(error.status, error.code, error.retryAfter);
  }
}
```

The root import, `@ugauga/feature-standards-react-auth`, exports the same API. A default client instance, `authApi`, is also available.

`me()` returns null only for `401 UNAUTHENTICATED`. Network failures and other API errors reject the promise, so callers can distinguish them from a signed-out state. `logout()` resolves after the server confirms session revocation and rejects on failure.

An `AuthSession` has the following shape. The session ID itself is carried only by a server-issued HttpOnly cookie.

```ts
interface AuthSession {
  user: { id: string; email: string };
  csrfToken: string;
}
```

## Account lifecycle

Use these methods when your server supports `browser-session-v3`. Each resolves to void on success.

```ts
await auth.register(email, password);
await auth.requestVerification(email);
await auth.confirmVerification(token);
await auth.requestPasswordReset(email);
await auth.confirmPasswordReset(token, newPassword);
```

| Method | HTTP endpoint | Success |
|---|---|---|
| login | POST /auth/login | 200 with AuthSession |
| me | GET /auth/me | 200 with AuthSession; null when unauthenticated |
| logout | POST /auth/logout | 204 |
| register | POST /auth/register | 202 |
| requestVerification | POST /auth/email-verification/request | 202 |
| confirmVerification | POST /auth/email-verification/confirm | 204 |
| requestPasswordReset | POST /auth/password-reset/request | 202 |
| confirmPasswordReset | POST /auth/password-reset/confirm | 204 |

## Server and application setup

The companion [Create Feature Auth CLI](https://github.com/jongko54/feature-standards/blob/main/docs/create-feature-auth.md) scaffolds a thin Python, Go, Java, or Rust server that reuses the same authentication contracts. It requires an explicit source checkout. Its temporary `--check` validates memory v1; PostgreSQL and account profiles require explicit database preparation. See the repository release receipts for the CLI's current npm publication status.

Your application needs a server on the same origin that implements the endpoints above. Requests use relative paths, `credentials: 'same-origin'`, and `cache: 'no-store'`. The client sends JSON for account operations and login, and an `X-CSRF-Token` header for logout. The browser supplies Origin. The server must enforce Origin, CSRF, cookie policy, session revocation, and authorization.

API errors use the shape `{ error: { code: string } }`. Inspect `ApiError.status`, `code`, and `retryAfter` to handle them. Retry-After is interpreted as an integer number of seconds. You can inject a fetch implementation with `createAuthApi(fetcher)` for testing.

Use the client from your React components and keep authentication state in memory. Do not store session IDs, passwords, or verification/reset tokens in localStorage. Applications that handle verification/reset links should read the token from the URL fragment, remove it from the address, and call the confirmation method after an explicit user action.

## Repository development

The [source repository](https://github.com/jongko54/feature-standards) includes a reference UI under clients/react and shared conformance tests for four backends. See the repository's [development guide](https://github.com/jongko54/feature-standards/blob/main/clients/react/DEVELOPMENT.md) for the UI, browser tests, and v3 configuration. Supporting guides currently include Korean documentation.

```sh
npm ci
npm test
npm run build
npm run check:package
```

The package check inspects the five-file tarball, installs it in a separate project, and verifies ESM imports, runtime requests, and TypeScript declarations. Licensed under MIT.
