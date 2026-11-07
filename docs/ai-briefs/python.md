# Python: session + permission + materialized listing

Scope: `browser-session-v1`, `rbac-v1`, `offset-list-v1` only. Preserve the target's existing authentication configuration/profile; do not reset it to fit this brief. Use the task's routes, fields, identities and grants, not copied demo fixtures.

All paths below are relative to the source checkout root. The catalog bundles documentation, not implementation files.

Follow the target's toolchain. When an external grader owns builds, write its build/start instructions and defer dependency installation to it; do not loop on offline setup.

Read in this order, limiting reads to the relevant APIs:
1. `examples/core-python/app.py` — route composition and trusted membership boundary.
2. `libraries/python/README.md` — look up only the authorization/listing API details needed by that composition.
3. `implementations/python-fastapi/feature_auth/http.py` — inspect only `create_app`/`current_user` signatures if still unclear; do not dump the full implementation.

Profile IDs are labels, not filenames. Exact contracts, when details are needed:
- `browser-session-v1`: `features/auth/specification.md`
- `rbac-v1`: `features/authorization/specification.md`
- `offset-list-v1`: `features/listing/specification.md`

| Public API | Role |
| --- | --- |
| `feature_auth.create_app(settings=...)` | Build the auth-enabled FastAPI app; retain its existing settings/store lifecycle. |
| `feature_auth.current_user(request)` / `Depends(current_user)` | Resolve the real current session user for a protected read. |
| `Grant(role, permission, scope)`; `Policy(grants)` | Declare explicit grants using `feature_standards.authorization`. |
| `Principal(subject_id, tenant_id, roles)`; `Resource(tenant_id, owner_id)` | Supply server-owned current membership and resource attributes. |
| `policy.decide(principal, permission, resource).allowed` | Check the decision's boolean; the Decision object itself is not the allow flag. |
| `ListingSchema(sort_fields, filter_fields)` | Declare allowed typed fields using `feature_standards.listing`. |
| `parse_query(raw_query, schema)`; `page(rows, query, schema)` | Parse the original query, then filter/sort/page already-authorized rows. |

Integration sequence:
1. Attach only the requested GET routes to the existing auth-enabled app; preserve `/auth/*`, cookies and logout behavior.
2. Resolve `current_user`; save its original `id`, pass `dict(user)` to the current membership provider, and require the returned subject to equal that saved ID.
3. Construct the task's explicit policy and typed listing schema; load resource tenant/owner from server data.
4. Require collection permission, then apply per-record read permission before public projection or any total, filtering, sorting or paging.
5. Decode `request.scope["query_string"]` as strict UTF-8, without `?`; call `parse_query` and `page`. For an item route, missing and inaccessible IDs both deny.
6. Validate the target's own routes and failure cases. If this repository's implementation/example changed, also run the selected source check below; report what each check exercised.

Keep these boundaries:
- Reload server-owned membership on every request. Headers/body/query cannot grant roles, tenant or subject; missing/mismatched membership denies.
- Tenant mismatch always denies; owner scope requires the original subject. A role named admin has no implicit grant.
- Materialized listing accepts at most 10000 rows. Reuse its parser/page semantics; do not substitute a database profile or reimplement query coercion.
- Keep errors generic: anonymous 401 `UNAUTHENTICATED`, denial 403 `FORBIDDEN`, provider failure 503 `AUTHORIZATION_UNAVAILABLE`, bad query 400 `INVALID_LIST_QUERY`, trusted schema/data failure 500 with its fixed code.
- Do not expose raw inputs, provider diagnostics or private resource fields. All product responses, including failures, need `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- Provider injection belongs to app construction (`create_core_app(membership=..., settings=...)` in the example), never a public test-control route.

Source check for changes to this repository's implementation/example (not target-app verification):
```sh
python3 tools/check_core_consumers.py --stack python
```
