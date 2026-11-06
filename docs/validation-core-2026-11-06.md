# Authorization and listing source validation — 2026-11-06

This change extends the source catalog from authentication to three features. Base revision: `cfa80d600d1a00bba787bd4e1a31b39db2c7b385`. These are local execution results for the new source changes; remote CI, package publication and production deployment are separate states.

## Implemented behavior

- `authorization/rbac-v1`: immutable explicit grants, deny by default, current server-owned principals, tenant isolation and owner checks. No implicit administrator or wildcard permission.
- `listing/offset-list-v1`: bounded strict raw-query parser, typed equality filters, Unicode scalar ordering, ID-ascending ties, scoped totals and offset pages.
- Both features have framework-independent Python, Go, Java, Rust and JS/TS libraries. The browser authorization helper is advisory.
- A separate Python consumer imports the existing real authentication API and both core libraries. Product routes obtain membership on each request and scope visible records before counting or paging.
- The source main CLI is 0.3.0 and selects 25 combinations: 15 existing auth combinations and 10 new core combinations. Existing auth `init/check` behavior is preserved. New core generation is explicitly unsupported and fails before side effects.

## Executed checks

| Check | Observed result |
| --- | --- |
| `tools/check_core_features.py --feature all --stack all` | All five native stacks passed; each executes 26 authorization + 50 listing shared vectors (380 vector executions) |
| Current Python core suite after review fix | 16 native tests passed, including the shared vectors |
| Go core `go test -race ./...` | Both feature packages passed, 6 native test functions including shared vectors |
| Java core Maven suite | 5 tests passed, zero errors/failures/skips, shared vectors included |
| Rust core Cargo suite | 5 tests passed, shared vectors included; fmt and clippy `-D warnings` passed |
| JS core Node suite | 33 tests passed, shared vectors included |
| Core public TypeScript declarations | Strict NodeNext type check passed, including expected invalid-call diagnostics |
| Separate Python HTTP consumer | 10 real TCP tests passed against installed local libraries |
| Main npm suite | 18 tests passed, retaining existing auth contexts and workflow checks |
| Main npm packed/bootstrap checks | Fresh installed CLI/exports, 25 contexts, offline package install and workflow fixtures passed; runtime source is not bundled |
| Source feature catalogs | Three features / 25 contexts valid; original auth catalog unchanged and valid |
| OpenAPI contracts | Original three auth profiles and both new consumer contracts validated; auth generator drift checks passed |
| Repository Python harness suite | 148 tests: 115 passed, 33 skipped because dedicated DB fixture configuration was absent |
| Existing Python auth native suite | 87 passed, 12 dedicated database tests skipped |
| Existing Go auth native suite | `go test -race ./...` passed |
| Existing Java auth native suite | 88 tests: 71 passed, 17 fixture-dependent tests skipped, zero errors/failures |
| Existing Rust auth native suite | 27 passed across library/reuse suites, 3 dedicated PostgreSQL/TLS cases ignored |
| Existing auth HTTP and browser matrix | 19 HTTP + 8 Chromium scenarios for each of four backends: 76 HTTP and 32 browser passes; four Secure-cookie checks passed |
| Existing React client | 8 API tests passed and production build passed |
| New integration skill | Frontmatter/naming validation passed; its guidance was also included in the independent review |
| Formatting and source hygiene | Relevant Python lint, Rust fmt/clippy, workflow-template parity and whitespace checks passed |

The native checker runs real tests, while the catalog checker only validates metadata and never executes catalog commands. Shared-vector loops are counted separately from native test function counts above.

## Independent review and regression evidence

A read-only agent reviewed the combined permission, parsing, HTTP, catalog and CI boundaries. Two findings were fixed:

1. Python's `math.isfinite` could raise `OverflowError` before rejecting an enormous native integer. A failing regression was recorded, bounds validation moved before float conversion, and the same input now returns `INVALID_LIST_DATA`.
2. The HTTP example projected missing document fields before the listing error boundary. A real TCP regression first observed `INTERNAL_ERROR` instead of `INVALID_LIST_DATA`. Missing public fields now become the fixed data error on both list and single-document routes. The reviewer independently reran that regression successfully and reported no remaining findings.

This review is not a production security audit.

## Limits and unchanged release state

No new registry publication or production deployment was performed. Existing auth packages remain separate; the new core package coordinates and main CLI 0.3.0 are source-only. The core crate disables publication and the JS package is private.

Go, Java and Rust have native library conformance in this change; only Python adds the combined real HTTP consumer. No new React product UI, database pagination adapter, cursor/snapshot consistency, policy-management API, MFA or AI speed/token benchmark is claimed.

PostgreSQL/account/SMTP schema and implementations were unchanged; their full dedicated database matrices were not rerun locally for this extension. Existing CI retains them. A pre-existing Cargo cache cleanup permission warning did not affect test exits; no global cache permissions were changed.
