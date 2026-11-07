# Go authentication + authorization + listing consumer

This separate Go application imports the real session-authentication library and the framework-independent core module. It exposes `GET /api/documents` and `GET /api/documents/{id}`. Authentication is never copied into the application.

From the repository root:

```sh
cd examples/core-go
go test -race ./...
AUTH_DEMO=true AUTH_STORE=memory AUTH_ACCOUNT_LIFECYCLE=false AUTH_COOKIE_SECURE=false AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 PORT=8011 go run .
```

The runnable demo binds `127.0.0.1` and requires explicit memory-demo configuration. `PORT` overrides `AUTH_PORT`. Login uses `POST /auth/login` with the existing demo credentials and exact Origin, then the HttpOnly `fs_session` cookie protects both product routes. Logout uses the existing Origin and session-CSRF contract. The product routes are GET-only.

`newHandler` receives an internal membership provider. Replace `demoMembership` with your server-owned current membership lookup when adapting the example. Membership is reloaded on every request; a valid session alone does not grant roles. The provider receives a defensive identity copy, and its returned subject must match the original authenticated session ID. Missing or mismatched membership denies access, and provider failure returns generic `503 AUTHORIZATION_UNAVAILABLE`. Request role/tenant/subject headers cannot grant access. Fixtures contain another owner's and another tenant's rows; authorization scopes the collection before totals, typed filtering, stable sorting or pagination. Responses project only `id`, `name`, `score` and `active` and use no-store/nosniff headers.

The checked-in `go.mod` pins authentication and core modules to `v0.1.0` and uses local `replace` directives to verify the current source libraries. These tests demonstrate source composition, separately from the registry publication receipts. A consuming application can remove both checkout replacements to use the published `github.com/jongko54/feature-standards/implementations/go-net-http@v0.1.0` and `github.com/jongko54/feature-standards/libraries/go@v0.1.0` modules.

Tests start a real loopback HTTP listener on an owned ephemeral port. They exercise cookie login/logout and old-cookie rejection, owner/tenant denial, hidden totals, typed filters and stable ties, strict query failures, spoofed headers, live membership revocation, provider failure, mismatched identities and generic trusted-data errors. Internal test providers are injected during construction; there is no HTTP test-control endpoint.

This example uses bounded materialized records. It does not add a database pagination adapter, policy administration, a UI, or production security certification. See [the shared contracts](../../docs/core-standards.md).
