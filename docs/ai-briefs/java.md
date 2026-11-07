# Java: session + permission + materialized listing

Scope: `browser-session-v1`, `rbac-v1`, `offset-list-v1` only. Preserve the target's existing authentication configuration/profile; do not reset it to fit this brief. Use the task's routes, fields, identities and grants, not copied demo fixtures.

All paths below are relative to the source checkout root. The catalog bundles documentation, not implementation files.

Follow the target's toolchain. When an external grader owns builds, write its build/start instructions and defer dependency installation to it; do not loop on offline setup.

Read in this order:
1. `examples/core-java/src/main/java/dev/featurestandards/examples/core/CoreController.java` — session-to-membership, policy and list flow.
2. `examples/core-java/src/main/java/dev/featurestandards/examples/core/CoreApplication.java` — shared service beans, auth filter registration and product headers.
3. `libraries/java/README.md` — look up only the core API details needed by that composition; avoid reading unrelated profiles.

Profile IDs are labels, not filenames. Exact contracts, when details are needed:
- `browser-session-v1`: `features/auth/specification.md`
- `rbac-v1`: `features/authorization/specification.md`
- `offset-list-v1`: `features/listing/specification.md`

| Public API | Role |
| --- | --- |
| `dev.featurestandards.auth.AuthService.create(config, memoryPassword, clock)` | Create the configured service for a new app; reuse the target's existing service when present. |
| `new AuthFilter(config, service)` | Keep auth HTTP handling on the same service; the example registers `/auth/*` and `/healthz`. |
| `auth.session(token)` | Resolve the actual `fs_session` cookie; null means unauthenticated. |
| `new AuthorizationPolicy(grants)`; `new Grant(role, permission, scope)` | Declare explicit grants in `dev.featurestandards.core.authorization`. |
| `new Principal(subjectId, tenantId, roles)`; `new Resource(tenantId, ownerId)` | Supply trusted current membership and resource attributes. |
| `policy.decide(principal, permission, resource).allowed()` | Enforce the Decision record's boolean. |
| `new Listing.Schema(sortFields, filterFields)`; `Listing.parseQuery(raw, schema)`; `Listing.page(rows, query, schema)` | Use `dev.featurestandards.core.listing.Listing` for strict typed, scoped materialized pagination. |

Integration sequence:
1. Add only the requested product GET mappings; retain the existing auth service/filter/profile. Follow `CoreApplication` for filter registration instead of routing product requests into an auth dispatcher.
2. Resolve the cookie through `auth.session`; retain its original `session.user().id()`, call current server membership, and require matching `Principal.subjectId()`.
3. Inject membership/resources through application construction (`MembershipProvider` and `DocumentProvider` in the example); construct the task's explicit grants/schema.
4. Require collection permission and apply per-record read permission before projecting public fields or computing any total, filter, sort or page.
5. Use `request.getQueryString()` unchanged, replacing null with `""`; call `Listing.parseQuery` and `Listing.page`. Item routes deny missing and inaccessible IDs identically.
6. Validate the target's own routes and failure cases. If this repository's implementation/example changed, also run the selected source check below; report what each check exercised.

Keep these boundaries:
- Providers reload server-owned membership/resources. Headers/body/query cannot grant roles, tenant or subject; no public provider-control endpoint exists.
- Tenant mismatch denies; owner scope requires the original authenticated subject. No implicit administrator, wildcard permission or hierarchy exists.
- Materialized listing accepts at most 10000 rows. Reuse shared semantics; do not replace this flow with a database listing profile.
- Keep responses generic: anonymous 401 `UNAUTHENTICATED`, denial 403 `FORBIDDEN`, provider failure 503 `AUTHORIZATION_UNAVAILABLE`, bad query 400 `INVALID_LIST_QUERY`, trusted schema/data failure 500 with its fixed code. Auth storage failures retain generic 503 `STORAGE_UNAVAILABLE`.
- The example's `/api/*` filter supplies `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`, including errors. Never echo inputs, tokens or provider diagnostics.
- `CoreController`/provider interfaces are example glue, not replacement authentication or core implementations; reuse the actual dependency classes.

Source check for changes to this repository's implementation/example (not target-app verification):
```sh
python3 tools/check_core_consumers.py --stack java
```
