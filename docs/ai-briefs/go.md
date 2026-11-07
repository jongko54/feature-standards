# Go: session + permission + materialized listing

Scope: `browser-session-v1`, `rbac-v1`, `offset-list-v1` only. Preserve the target's existing authentication configuration/profile; do not reset it to fit this brief. Use the task's routes, fields, identities and grants, not copied demo fixtures.

All paths below are relative to the source checkout root. The catalog bundles documentation, not implementation files.

Follow the target's toolchain. When an external grader owns builds, write its build/start instructions and defer dependency installation to it; do not loop on offline setup.

Read in this order, limiting reads to the named APIs:
1. `examples/core-go/main.go` — shared auth server, mux routes and membership injection.
2. `libraries/go/README.md` — look up only the authorization/listing API details needed by that composition.
3. `implementations/go-net-http/auth/server.go` — inspect only `NewServer`/`CurrentUser`/`Close` signatures if still unclear; do not dump the full implementation.

Profile IDs are labels, not filenames. Exact contracts, when details are needed:
- `browser-session-v1`: `features/auth/specification.md`
- `rbac-v1`: `features/authorization/specification.md`
- `offset-list-v1`: `features/listing/specification.md`

| Public API | Role |
| --- | --- |
| `auth.NewServer(config)`; `server.Close()` | Construct/close one configured auth server, or reuse the application's existing one. |
| `server.CurrentUser(w, r)` | Return the current user and success flag; on false, stop because the auth error response is already written. |
| `authorization.NewPolicy([]authorization.Grant{...})` | Build explicit immutable grants; handle its error. |
| `authorization.Principal`; `authorization.Resource` | Carry server-owned subject/tenant/roles and resource tenant/optional owner. |
| `policy.Decide(principal, permission, resource).Allowed` | Enforce the boolean decision; `OwnerID` is a `*string`. |
| `listing.NewSchema(sortFields, filterFields)` | Declare typed allowlists; handle its error. |
| `listing.ParseQuery(raw, schema)`; `listing.Page(rows, query, schema)` | Parse the raw query and page scoped `[]map[string]any`; handle every error. |

Integration sequence:
1. Reuse the same auth server for `/auth/` and protected reads; add requested GET handlers to the application's mux, as the example does.
2. Call `CurrentUser`; save the original `user["id"]`, pass a copied map to current membership lookup, and require a matching returned `SubjectID`.
3. Build the task's explicit policy/schema; keep resource tenant/owner and public-field projection server-owned.
4. Require collection permission, then filter by per-record read permission before totals, filtering, sorting or paging.
5. Pass `r.URL.RawQuery` directly to `listing.ParseQuery`, then call `listing.Page` on visible rows. Item routes deny absent and inaccessible IDs identically.
6. Validate the target's own routes and failure cases. If this repository's implementation/example changed, also run the selected source check below; report what each check exercised.

Keep these boundaries:
- `newHandler` and `handlerWithDocuments` are example-local construction helpers, not auth/core library exports. Inject real current membership internally; never expose a provider-control endpoint.
- Headers/body/query cannot grant roles, tenant or subject. Missing/mismatched membership denies; provider errors fail closed. Tenant mismatch denies and owner scope requires the original subject.
- No implicit administrator, wildcard permission or role hierarchy exists. Do not copy demo membership into a real account system.
- Materialized listing accepts at most 10000 rows; use the shared parser/page rather than framework query coercion or a different listing profile.
- Return generic errors: anonymous 401 `UNAUTHENTICATED`, denial 403 `FORBIDDEN`, provider failure 503 `AUTHORIZATION_UNAVAILABLE`, bad query 400 `INVALID_LIST_QUERY`, trusted schema/data failures 500 with fixed codes.
- Put `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` around all product responses, including auth/provider/query failures. Never echo raw inputs or private provider details.

Source check for changes to this repository's implementation/example (not target-app verification):
```sh
python3 tools/check_core_consumers.py --stack go
```
