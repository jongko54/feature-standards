# Core integration hardening

The user requested agent-assisted implementation after the three-feature beta assessment. Preserve released packages, existing auth profiles and `offset-list-v1` behavior. Implement and verify source changes; registry publication is a separate operation.

## Outcomes and ownership

1. **Python PostgreSQL listing** — additive `postgres-list-v1` source profile. Reuse strict raw-query parsing, parameterize values and identifiers, require explicit trusted tenant/owner visibility, and execute count/page in one read-only repeatable-read transaction. Support database collections larger than the materialized helper's 10,000-row bound without changing that helper. Define typed/not-null/unique-ID table constraints and scope/data/storage errors. Test real PostgreSQL isolation, injection inputs, large collections, concurrent count/page changes and transaction ownership. The PostgreSQL agent owns the adapter, its tests/fixture and profile specification; parent owns catalog/OpenAPI/scenario registration and optional HTTP wiring.
2. **Three-feature HTTP consumers** — Go, Java and Rust examples reuse existing auth/core public APIs. Match Python's document routes and fixtures. Every request loads current trusted membership; revoke/failure/mismatched subject must deny. Scope records before totals. Real socket tests cover login/logout, forged sessions/headers, tenant/owner isolation, raw query errors and generic failure responses. Two independent agents own the new example directories; parent owns shared checker and CI.
3. **Current catalog AI evaluation** — compare manual documentation entry with explicit routing through the verified published `feature-standards@0.3.2` catalog. Both conditions use identical frozen implementation source and the same available catalog bytes. Evaluate real generated HTTP integrations of auth + authorization + listing with independent checks, including a grader-owned membership fixture for revocation/failure. Preserve existing auth-v1 evaluator behavior. Record fixed requested model, observed model if reported, source/catalog/runner/task hashes, actual timing, token completeness, failures and cache limitations. Run a bounded paired smoke; do not claim statistical improvement from a small sample.
4. **Integration** — register Python-only DB support explicitly rather than claiming all five stacks implement it. Route the Go/Java/Rust core catalog to actual HTTP examples. Update source versions and package snapshots consistently while preserving immutable release receipts. Run native/profile/consumer/tool tests, packed CLI checks, lint and full remote CI for the integrated source.

## Boundaries

- No replacement of authentication, automatic production migration, real outbound mail, policy-management API, cursor pagination or deployment to a user's application.
- PostgreSQL fixtures use only task-owned temporary local databases/schemas. Existing auth databases and release worktrees are preserved.
- SQL scope comes from the authenticated server-side membership/policy result. Request headers/query/body cannot choose tenant, owner, relation or SQL fragments.
- Published core 0.1.0 and CLI 0.3.2 receipts stay historical. New source APIs are not marked published until a matching registry receipt exists.
- Agents have disjoint file ownership and do not change Git refs, commit or publish. Parent integrates and performs requested remote repository work.

## Verification

- Adapter configuration tests plus real PostgreSQL conformance, including >10,000 rows and a coordinated concurrent insert between count/page.
- Existing 76 core vectors across five native stacks, then real HTTP composition in Python, Go, Java and Rust.
- Evaluator deterministic positive/negative controls and existing auth evaluator regressions before actual model smoke. Fake CLI runs validate the harness only.
- Catalog/schema/profile-subset and unsupported-selection tests; snapshot file whitelist, installed bin, Node exports and every supported context from the real packed artifact.
- Full source CI with PostgreSQL/browser/generated consumers; keep tests, publication and production readiness as separate evidence.

## Progress

- Initial repository was clean at `f25e45f`; existing release worktrees preserved.
- PostgreSQL adapter, Go/Java consumers and Rust consumer assigned to independent agents. After the Rust consumer finished, that agent implemented the evaluator. Parent owns routing, integration and independent verification.
- Implemented Python optional DB adapter/profile and HTTP+DB demo; parent independently ran 16 DB and 11 HTTP+DB tests successfully, plus the five-stack native suite.
- Added Go/Java/Rust real HTTP consumers and exercised all four backend consumer suites. Mutable membership-provider identity rewriting and duplicated Java product headers have regression fixes.
- Independent review found libpq environment defaults could bypass loopback guards; no-I/O regressions, strict environment rejection and explicit destination pins now pass, with focused independent recheck.
- Source catalog has 26 supported contexts and Python-only database bindings. CLI 0.4.0 candidate adds opt-in compact routing; 21 CLI tests and packed offline installation/exports pass. A clean 6036df6 snapshot measurement records 52.96–65.68% smaller routing JSON (median 58.50%), not model tokens or integration speed.
- Actual eight-call catalog smoke completed on fixed published 0.3.2/source 752e4e4: original 7/8, including one Python catalog cache guard failure before HTTP grading. Original runner bytes are retained in commit 6036df6. Corrected pair ordering, core-only cache treatment and valid Python/Java import forms pass 49 auth/core/replay-boundary tests and independent review.
- Uniform artifact-only replay used no new model calls and passed 5/8 strict complete checks. Python catalog needed an omitted offline cache; both Go apps passed 143 HTTP checks but changed generated bytes, with cause unknown. Exact original results, traces, references and generated sources were preserved across all eight trials. Public sanitized original/replay records keep these outcomes separate; no general efficiency improvement is established and compact mode remains unbenchmarked by actual model calls.
- All implementation and local integration work is ready for repository push and final remote CI. New registry publication remains outside this source-hardening operation.
- Broad local Python harness: 164 tests, 33 legacy database-environment skips. Changed-file/required CI lint is green; an extra whole-library style scan found six pre-existing style findings in untouched authorization files, outside the changed lint scope.
