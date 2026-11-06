# Three feature standards

The source catalog now contains **auth**, **authorization**, and **listing**. Authentication retains its published packages and three session profiles. Authorization (`rbac-v1`) and listing (`offset-list-v1`) are experimental 0.1.0 libraries. [The registry receipt](core-release-0.1.0.json) verifies Python, Rust and Go downloads and fresh consumers; Java and npm core are awaiting maintainer authentication. Main CLI 0.3.0 was published separately and captures the earlier source-only core context. Publication and API maturity remain separate.

| Feature | Responsibility | Shared implementations |
| --- | --- | --- |
| auth | Login, logout, sessions; optional PostgreSQL accounts | Existing FastAPI, Go, Spring, Axum and React |
| authorization | Explicit role permissions, tenant boundary, owner checks | Python, Go, Java, Rust, JS/TS |
| listing | Strict raw-query parsing, typed equality filters, stable sort and pagination | Python, Go, Java, Rust, JS/TS |

## Start with the contract

Select feature and stack, then read only the selected profile, public entrypoint and library guide. [The feature index](../features/catalog.json) is machine-readable. Each catalog gives exact source paths, profile identifiers, package publication state and executable argv arrays. [Core integration instructions](../skills/integrate-core/SKILL.md) describe the trust boundary. `scenarios.json` is consumed directly by every native implementation; it is executable behavior, not a claim about an AI model's internal reasoning or faster development.

```sh
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context --feature authorization --stack python
python3 tools/feature_catalog.py --check
python3 tools/check_core_features.py --feature all --stack all
```

Use the CLI command declared in its package.json if invoking from another checkout. `init` and the generated-application `check` workflow still support authentication only. The new core libraries are integrated directly from source; unsupported generation fails before creating files.

## Compose authentication and permissions

A verified session supplies a subject ID, not permissions. Load **current** roles and tenant from your own trusted membership service on every request, then load resource tenant/owner from server-owned data. Construct an immutable `Policy` from explicit grants. Tenant mismatch always denies; a role named admin has no implicit privileges. Empty roles, unknown permission and missing ownership deny. Membership failure must deny and return a generic service-unavailable error; request headers cannot grant roles.

The [Python HTTP consumer](../examples/core-python/README.md) imports the existing authentication library and both new core APIs. It uses real login/logout cookies. `GET /api/documents/{document_id}` checks owner permission; `GET /api/documents` scopes visible records **before** totals or pagination. Inaccessible and absent document IDs both return FORBIDDEN. There is no public policy-evaluation or fixture-control endpoint.

JS/TS permission helpers are useful for UI visibility. A browser result is advisory; enforce the same policy on the server. The new libraries do not add a React component dependency.

## Parse lists at the raw-query boundary

Pass the raw query string without `?`, before framework coercion. The profile rejects duplicate keys (including percent-encoded duplicates), malformed escapes/UTF-8, unknown fields and noncanonical numbers. Use an explicit schema allowlist, never SQL fragments. Scope the collection first, then validate referenced values, filter, compare Unicode scalar values, order with ID-ascending ties, and slice. Rows are materialized and bounded to 10,000.

The result is `{items,total,limit,offset,nextOffset}`. Offset pagination can shift under concurrent writes. A database adapter, cursor/snapshot semantics, policy-management UI, role hierarchy, wildcard grants and a production audit are outside these source profiles. This is not a claim of Google AIP pagination conformance.

## Verification boundaries

All five languages run the same authorization and listing vectors plus native boundary tests. The Python consumer additionally runs real TCP HTTP tests for session revocation, spoofed roles, tenant/owner denial, hidden totals and provider failure. Go/Java/Rust have native core tests; this task does not add separate HTTP consumers for them. Existing auth conformance and browser checks remain distinct from the new native checks. Registry publication and measured AI token/speed improvement require their own evidence.

References used to bound the design: [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [AIP-158](https://google.aip.dev/158), [AIP-160](https://google.aip.dev/160).
