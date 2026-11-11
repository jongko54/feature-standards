# Optional Rust SDK connection

If you choose the original SDKs, start with [the working consumer](../../examples/core-rust/src/lib.rs), [its manifest](../../examples/core-rust/Cargo.toml) and [the focused brief](../ai-briefs/rust.md). These are optional connection hints; the task defines the application's behavior and the implementation approach remains yours.

## Dependency and import boundary

The consumer uses Rust 1.93.1+, edition 2024 and these local source dependencies:

```toml
[dependencies]
feature-standards-auth = { path = "../../implementations/rust-axum" }
feature-standards-core = { path = "../../libraries/rust" }
```

The paths above are relative to `examples/core-rust/Cargo.toml`; another app can point to the supplied checkout. The [auth package](../../implementations/rust-axum/Cargo.toml) and [core package](../../libraries/rust/Cargo.toml) are distinct packages, both declaring 0.1.0. Their Rust import names use underscores:

```rust
use feature_standards_auth::{AuthService, Config, SessionUser, app_with_service, current_user};
use feature_standards_core::authorization::{Grant, Policy, Principal, Resource};
use feature_standards_core::listing::{ListingError, Schema, parse_query, page};
```

The auth crate publicly re-exports `AuthService`/`SessionUser` from its private `store` module; consumers import the public crate root. Core exports the public `authorization` and `listing` modules, rather than these types at its root. `cargo metadata` exposes `manifest_path` and package source; a path into the original checkout and a path into an app-local copied crate are different origins even when package names match.

## Read composition

`app_with_membership` and `app_with_documents` belong to the example crate, not the auth/core SDK. Their sequence applies to other business resources:

1. Reuse a shared `AuthService`. For a new app, `AuthService::from_config(&mut config).await` opens it once and consumes the memory password. `app_with_service(config, auth.clone())` supplies the auth router using the same store; merge it with the product router.
2. `current_user(&auth, &headers).await` returns the real `SessionUser` or `Err(Response)` with an SDK auth error. Its default message is the code. When the product requires another envelope, catch that response before returning it: map its known status to the corresponding fixed code (`401` to `UNAUTHENTICATED`, `503` to `STORAGE_UNAVAILABLE`, `500` to `INTERNAL_ERROR`) and build the product error with its required message and security headers. Preserve fail-closed status; this is response adaptation, not a replacement session implementation. Load current trusted membership from `&user` and compare its `Principal.subject_id` with the original `user.id`. Missing/mismatched membership denies; provider failure closes access.
3. `Policy::new(Vec<Grant>)` builds explicit grants. Collection access uses `policy.decide(Some(&principal), list_permission, &Resource { tenant_id: principal.tenant_id.clone(), owner_id: None }).allowed`.
4. Each row's read permission uses trusted tenant/owner attributes in `Resource`; `owner_id` is `Option<String>`. Keep allowed rows, then project public fields before totals or list processing.
5. `Schema::new(sort_fields, filter_fields)` takes typed `BTreeMap<String, String>` allowlists. Axum `RawQuery(raw)` preserves the input; call `parse_query(raw.as_deref().unwrap_or(""), &schema)` and `page(&visible, &query, &schema)` on scoped `serde_json::Value` records. Return its result with `Json` and handle every `Result`.
6. Item reads share the same membership/row policy; the example denies absent and inaccessible IDs alike. It maps `ListingError::InvalidQuery` to 400 and trusted data/schema failures to generic 500. Product response middleware applied after merging covers successes and errors with `no-store`/`nosniff`.

The task chooses routes, permission names, grants, schema fields and projections. Server-owned membership/resource providers supply current roles, tenant and owner; browser claims do not replace them. The demo document model is only an example.

`current_user` resolves identity only. Custom unsafe routes need separate Origin and session-CSRF enforcement. `AuthService::me(token).await` exposes `LoginSession.csrf_token`, but there is no dedicated non-destructive mutation-CSRF checker; `logout` also destroys the session.

API detail: [auth exports and HTTP adapter](../../implementations/rust-axum/src/lib.rs), [auth service](../../implementations/rust-axum/src/store.rs), [core exports](../../libraries/rust/src/lib.rs), [core API](../../libraries/rust/README.md), [common scope](README.md).
