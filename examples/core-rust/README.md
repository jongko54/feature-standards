# Authentication + authorization + listing: Rust HTTP consumer

This source example imports `feature-standards-auth` and `feature-standards-core` through Cargo path dependencies. It composes real cookie sessions with `rbac-v1` and `offset-list-v1`; it contains no copied password hashing, session store or core feature implementation. Rust 1.93.1 is required. This consumer is `publish = false`; library registry publication is recorded separately in the repository release receipts.

From the repository root:

```sh
cargo build --locked --manifest-path examples/core-rust/Cargo.toml
AUTH_DEMO=true AUTH_COOKIE_SECURE=false PORT=8013 \
  cargo run --locked --manifest-path examples/core-rust/Cargo.toml
```

The executable requires explicit demo mode and always binds `127.0.0.1`. `PORT` overrides `AUTH_PORT`; the default is `8013`. The allowed Origin defaults to `http://127.0.0.1:5173`. The public demo fixture is `demo@example.com` / `correct-horse-battery-staple`. Keep the HttpOnly `fs_session` cookie from `POST /auth/login`; `/auth/logout` requires the returned session CSRF token. The existing authentication library owns all `/auth/*` behavior.

## Product routes and trusted providers

- `GET /api/documents` authenticates the real session, loads current membership, requires `documents:list`, restricts records by `documents:read`, then validates the original raw query and computes filtered totals/order/page. The sort allowlist is `id`, `name`, `score`, `active`; filters allow `name`, `score`, `active` with their declared types.
- `GET /api/documents/{id}` requires the same current membership and owner/tenant permission. Missing and inaccessible IDs both return `403 FORBIDDEN`.
- All `/api` responses include `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Query failures return `400 INVALID_LIST_QUERY`; malformed trusted product data returns `500 INVALID_LIST_DATA`; membership lookup failure returns generic `503 AUTHORIZATION_UNAVAILABLE`.

The immutable demo policy explicitly grants viewer tenant-level `documents:list` and owner-only `documents:read`. Fixtures deliberately include another owner's record and another tenant's record. Those records cannot affect the visible collection's totals. Role, tenant and subject headers or query parameters never grant access.

`app(Config)` builds the fixture consumer. `app_with_membership(Config, MembershipProvider)` injects a server-owned lookup called on every request with the authenticated `SessionUser`. Return a matching `Principal`, `None` for no membership, or `Err(MembershipUnavailable)` for provider failure; a principal whose subject differs from the real session is denied. Production code must replace the demo lookup with its current membership service. `app_with_documents` additionally accepts an immutable server-owned document snapshot during construction. No HTTP route can change providers, roles, data or policies.

The product routes are GET-only. New mutation routes need their own Origin, CSRF and permission enforcement. This example does not add a database listing adapter, policy-management API, persistent membership store or browser UI. Core listing remains bounded materialized pagination; native vector tests and TCP tests are different evidence from production deployment or a security audit.

## Verification

```sh
cargo test --locked --manifest-path examples/core-rust/Cargo.toml
cargo fmt --all --manifest-path examples/core-rust/Cargo.toml -- --check
cargo clippy --locked --manifest-path examples/core-rust/Cargo.toml --all-targets -- -D warnings
```

Eight HTTP integration tests serve real loopback TCP listeners bound to port zero for their entire lifetime. They cover anonymous/forged sessions, real login and CSRF logout, rejection of copied old cookies, tenant/owner isolation, hidden totals, strict typed query parsing, stable ties/pagination, current membership revocation/recovery, spoofed headers, missing/mismatched membership, provider failure, malformed trusted data and private error headers. Two executable tests check explicit demo mode and port validation. No external services, production database or real SMTP recipient is used.

The router uses Axum's [raw query extractor](https://docs.rs/axum/0.8.9/axum/extract/struct.RawQuery.html) before coercion and [response middleware](https://docs.rs/axum/0.8.9/axum/middleware/fn.from_fn.html) for product headers.
