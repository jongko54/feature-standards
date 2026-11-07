# Rust: session + permission + materialized listing

Scope: `browser-session-v1`, `rbac-v1`, `offset-list-v1` only. Preserve the target's existing authentication configuration/profile; do not reset it to fit this brief. Use the task's routes, fields, identities and grants, not copied demo fixtures.

All paths below are relative to the source checkout root. The catalog bundles documentation, not implementation files.

Follow the target's toolchain. When an external grader owns builds, write its build/start instructions and defer dependency installation to it; do not loop on offline setup.

Read in this order, limiting reads to the named APIs:
1. `examples/core-rust/src/lib.rs` — shared auth service, injected providers and product router.
2. `libraries/rust/README.md` — look up only the authorization/listing API details needed by that composition.
3. `implementations/rust-axum/src/lib.rs` — inspect only `AuthService::from_config`/`current_user`/`app_with_service` signatures if still unclear; do not dump the full implementation.

Profile IDs are labels, not filenames. Exact contracts, when details are needed:
- `browser-session-v1`: `features/auth/specification.md`
- `rbac-v1`: `features/authorization/specification.md`
- `offset-list-v1`: `features/listing/specification.md`

| Public API | Role |
| --- | --- |
| `feature_standards_auth::AuthService::from_config(&mut config).await` | Initialize the selected auth service once for a new app; reuse an existing service when present. |
| `feature_standards_auth::app_with_service(config, auth)` | Build auth routes around that same service; cloned AuthService shares its store. |
| `feature_standards_auth::current_user(&auth, &headers).await` | Resolve the real session as `SessionUser`, or propagate its fail-closed response. |
| `authorization::{Grant, Principal, Resource}`; `Policy::new(grants)` | Use `feature_standards_core` types and explicit grants; handle the constructor Result. |
| `policy.decide(Some(&principal), permission, &resource).allowed` | Enforce the boolean decision. `Resource.owner_id` is `Option<String>`. |
| `listing::Schema::new(sort_fields, filter_fields)` | Declare typed `BTreeMap<String, String>` allowlists; handle errors. |
| `listing::parse_query(raw, &schema)`; `listing::page(&rows, &query, &schema)` | Parse raw query and page already-authorized `serde_json::Value` records. |

Integration sequence:
1. Add requested GET routes on a product router; merge with auth routes backed by the same service, as the example does. Do not initialize a second store or consume the memory configuration password twice.
2. Resolve `current_user`, retain the original `SessionUser.id`, pass `&SessionUser` to current membership lookup, and require matching returned `Principal.subject_id`.
3. Inject providers during app construction; build the task's explicit policy/schema and server-owned resource attributes.
4. Require collection permission and apply per-record read permission before public projection or totals, filtering, sorting or paging.
5. Use Axum `RawQuery`; pass `raw.as_deref().unwrap_or("")` to `parse_query`, then `page`. Item routes deny missing and inaccessible IDs identically.
6. Validate the target's own routes and failure cases. If this repository's implementation/example changed, also run the selected source check below; report what each check exercised.

Keep these boundaries:
- Example-crate `app_with_membership` and `app_with_documents` inject internal `MembershipProvider`/data; they are not auth/core crate exports. No HTTP route may replace roles, policies or providers.
- Headers/body/query cannot grant roles, tenant or subject. Missing/mismatched membership denies; provider errors fail closed. Tenant mismatch denies and owner scope requires the original subject.
- No implicit administrator, wildcard permission or role hierarchy exists. Do not copy demo membership into a real account system.
- Materialized listing accepts at most 10000 rows. Handle all Results; do not replace its parser/page semantics with framework coercion or another listing profile.
- Return generic errors: anonymous 401 `UNAUTHENTICATED`, denial 403 `FORBIDDEN`, provider failure 503 `AUTHORIZATION_UNAVAILABLE`, bad query 400 `INVALID_LIST_QUERY`, trusted schema/data failure 500 with its fixed code.
- Apply product-header middleware after merging routers: `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` also cover failures. Never echo raw inputs, cookies or provider diagnostics.

Source check for changes to this repository's implementation/example (not target-app verification):
```sh
python3 tools/check_core_consumers.py --stack rust
```
