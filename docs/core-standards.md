# Three feature standards

The catalog contains **auth**, **authorization**, and **listing**. Authentication retains its published packages and three session profiles. Authorization (`rbac-v1`) and listing (`offset-list-v1`) are experimental 0.1.0 libraries. [The registry receipt](core-release-0.1.0.json) records each ecosystem's public download and fresh consumer checks. Main CLI releases capture publication evidence at build time; consult the receipt bundled with the selected version. Publication and API maturity remain separate.

The current source adds Python core **0.2.0** and catalog **0.4.0** candidates, including the Python-only [`postgres-list-v1`](postgres-listing.md) database adapter. These candidate versions are not established as published by the 0.1.0 receipt. The source catalog has **26 supported contexts**; the published 0.3.2 catalog retains its historical 25. Each stack's `profiles` list identifies the combinations it actually supports.

| Feature | Responsibility | Shared implementations |
| --- | --- | --- |
| auth | Login, logout, sessions; optional PostgreSQL accounts | Existing FastAPI, Go, Spring, Axum and React |
| authorization | Explicit role permissions, tenant boundary, owner checks | Python, Go, Java, Rust, JS/TS |
| listing | Strict raw-query parsing, typed equality filters, stable sort and pagination | Python, Go, Java, Rust, JS/TS |
| listing / postgres-list-v1 | Parameterized scoped database count/page in one read-only snapshot | Python source candidate only |

## Start with the contract

Select feature and stack, then read only the selected profile, public entrypoint and library guide. [The feature index](../features/catalog.json) is machine-readable. Each catalog gives exact source paths, profile identifiers, package publication state and executable argv arrays. [Core integration instructions](../skills/integrate-core/SKILL.md) describe the trust boundary. `scenarios.json` is consumed directly by every native implementation; it is executable behavior, not a claim about an AI model's internal reasoning or faster development.

```sh
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context --feature authorization --stack python
python3 tools/feature_catalog.py --check
python3 tools/check_core_features.py --feature all --stack all
```

Use the CLI command declared in its package.json if invoking from another checkout. `init` and the generated-application `check` workflow still support authentication only. Integrate core APIs through their pinned registry packages when the matching receipt verifies publication, or use a local path for checkout development. Unsupported generation fails before creating files.

## Compose authentication and permissions

A verified session supplies a subject ID, not permissions. Load **current** roles and tenant from your own trusted membership service on every request, then load resource tenant/owner from server-owned data. Construct an immutable `Policy` from explicit grants. Tenant mismatch always denies; a role named admin has no implicit privileges. Empty roles, unknown permission and missing ownership deny. Membership failure must deny and return a generic service-unavailable error; request headers cannot grant roles.

The [Python HTTP consumer](../examples/core-python/README.md) imports the existing authentication library and both new core APIs. It uses real login/logout cookies. `GET /api/documents/{document_id}` checks owner permission; `GET /api/documents` scopes visible records **before** totals or pagination. Inaccessible and absent document IDs both return FORBIDDEN. There is no public policy-evaluation or fixture-control endpoint.

[Go](../examples/core-go/README.md), [Java](../examples/core-java/README.md) and [Rust](../examples/core-rust/README.md) provide the same real HTTP composition with internal membership injection. The examples load membership on every request, preserve the original authenticated subject and reject a provider attempting to change it. Fixtures and runnable entrypoints require explicit local demo use. Run `python3 tools/check_core_consumers.py --stack all` for the four backend HTTP suites. These examples do not add a production membership database or policy-management service.

JS/TS permission helpers are useful for UI visibility. A browser result is advisory; enforce the same policy on the server. The new libraries do not add a React component dependency.

## Parse lists at the raw-query boundary

Pass the raw query string without `?`, before framework coercion. The profile rejects duplicate keys (including percent-encoded duplicates), malformed escapes/UTF-8, unknown fields and noncanonical numbers. Use an explicit schema allowlist, never SQL fragments. Scope the collection first, then validate referenced values, filter, compare Unicode scalar values, order with ID-ascending ties, and slice. Rows are materialized and bounded to 10,000.

The result is `{items,total,limit,offset,nextOffset}`. Offset pagination can shift under concurrent writes. A database adapter, cursor/snapshot semantics, policy-management UI, role hierarchy, wildcard grants and a production audit are outside these source profiles. This is not a claim of Google AIP pagination conformance.

The separate PostgreSQL source profile supports larger database collections without changing materialized v1. It requires explicit server-owned visibility and typed table constraints; count/page share a request-local repeatable-read snapshot. Offset navigation remains bounded at 10,000, with `nextOffset: null` at that navigation boundary even if `total` is larger. Cursor traversal and cross-request snapshots are not included. See the [adapter guide](postgres-listing.md) and [DB HTTP demo](../examples/core-python-postgres/README.md).

## Verification boundaries

All five languages run the same 76 materialized authorization/listing vectors plus native boundary tests. The four backend consumers run real TCP HTTP tests for session revocation, spoofed roles, tenant/owner denial, hidden totals and provider failure. PostgreSQL has its own Python-only boundary/database test map and a real HTTP+DB composition. Existing auth browser checks remain distinct from these core HTTP checks. Registry publication and measured AI token/speed improvement require their own evidence.

References used to bound the design: [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [AIP-158](https://google.aip.dev/158), [AIP-160](https://google.aip.dev/160).
