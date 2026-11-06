# Three reusable feature standards

## Goal and scope

Implement source-available standards for `auth`, `authorization`, and `listing`, with reusable implementations in Python, Go, Java, Rust, and browser JavaScript/TypeScript. Preserve the existing authentication HTTP contracts, schemas, libraries, generator, and default CLI behavior. New APIs are unpublished; do not change existing registry release claims or publish new packages in this task.

The new standards are framework-independent libraries under `libraries/{python,go,java,rust,typescript}`. A separate Python HTTP consumer composes them with the existing FastAPI authentication library. The common scenario files are executed by native tests in every implementation. Existing authentication consumers remain unchanged.

## Architecture and ownership

- Parent: contracts/scenarios/catalog manifests, common package skeletons, HTTP consumer and grader, CI, integration docs and final verification.
- Authorization agent: new authorization modules and their tests only in the five common-library projects.
- Listing agent: new listing modules and their tests only in the five common-library projects.
- Catalog agent: main npm package list/context/snapshot/tests, generic catalog checker and its tests; auth init/check stay explicitly auth-only.
- Parent owns shared Python `__init__.py`, Rust `lib.rs`, TypeScript `index.mjs`/declarations, all package/build metadata. Agents must not commit, push, publish, edit each other's files, or alter authentication implementation files.

## Shared catalog

Keep `feature-standards.json` and `tools/auth_catalog.py` as the authentication catalog. Add `features/catalog.json` referencing that file and `features/{authorization,listing}/catalog.json`. Each catalog uses profiles/stacks/entrypoints/check argv and truthful `published: false` metadata for the new core libraries. Defaults: auth/browser-session-v1, authorization/rbac-v1, listing/offset-list-v1. Include only implemented stacks; React identifies browser JS/TS helpers, never a server authorization boundary.

New source packages: Python `feature-standards-core` / `feature_standards`, Go module `github.com/jongko54/feature-standards/libraries/go`, Java `io.github.jongko54:feature-standards-core:0.1.0`, Rust crate `feature-standards-core`, npm `@ugauga/feature-standards-core`. All start at unpublished 0.1.0. Main CLI source version becomes 0.3.0 without publication.

## Authorization contract: rbac-v1

- Server-owned principal `{subjectId, tenantId, roles}`; nullable principal means anonymous. Server-owned resource `{tenantId, ownerId}`; owner may be absent/null for collection scope.
- Immutable policy snapshot constructed from at most 256 grants `{role, permission, scope}`. Scopes are exactly `tenant` or `owner`; no wildcards, hierarchy, implicit administrator, deny overrides, or policy management API.
- Policy validates every grant, rejects duplicate `(role,permission)` pairs (including identical duplicates), and copies caller-owned input. Invalid policy construction is `INVALID_AUTHORIZATION_POLICY`.
- Identifier grammar: subject/tenant/non-null owner `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`; role `[a-z][a-z0-9_-]{0,63}`; permission `[a-z][a-z0-9_.:-]{0,63}`. Principal roles: at most 16 unique values. Empty roles are valid and deny. Empty policy is valid and denies.
- `Policy.decide(principal, permission, resource)` returns `{allowed,code}`. Null principal returns false/UNAUTHENTICATED. Invalid principal, permission or resource returns false/FORBIDDEN. Unknown roles/permissions deny unless another explicit matching role grants access.
- Tenant mismatch always denies, even for roles named admin. `owner` additionally requires non-null matching ownerId; `tenant` permits a matching tenant with optional owner. Success is true/ALLOWED; all other authenticated decisions are false/FORBIDDEN.
- HTTP consumer authenticates with the real existing session, then loads current membership and resources from server-owned providers on each request. No role/tenant/subject from headers/query/body is trusted. Membership failure is generic 503 AUTHORIZATION_UNAVAILABLE. GET-only product examples avoid inventing a mutation-CSRF helper. List visibility is filtered with the same policy before pagination or totals.
- Browser helpers may assist presentation only. Native server policy remains authoritative.

## Listing contract: offset-list-v1

- Strict raw query input, no initial `?`. Maximum 2048 UTF-8 bytes and 16 `&`-separated pairs. Standard form encoding (`+` means space), exactly one decoded value per key. Reject malformed percent escapes, invalid UTF-8/surrogates, ASCII control characters (U+0000..U+001F and U+007F), duplicate/unknown keys, empty pairs or missing `=`. Percent-decode before key duplicate/allowlist checks.
- `limit` default 20, range 1..100; `offset` default 0, range 0..10000. Canonical ASCII decimal only: 0 or a nonzero leading digit followed by digits. Empty values, signs, whitespace, leading zeros and overflow reject. `limit=0` rejects.
- `sort` is one schema-allowlisted field, optionally prefixed with `-`; default `id`. No comma expressions. IDs use the identifier grammar above, are unique, and always break non-ID sort ties ascending, including for descending primary sort.
- `filter.<field>` supports exact equality on server-allowlisted fields only. Schema is `{sortFields:{field:type},filterFields:{field:type}}`, types `string`, `integer`, `boolean`. `id` must be sortable string. At most 16 fields per map, field grammar `[a-z][a-z0-9_]{0,31}`; overlapping map entries must agree. Invalid schema is INVALID_LIST_SCHEMA.
- Integer filters use canonical signed decimal (no plus, leading zeros, or -0), within JavaScript safe integer bounds +/-9007199254740991. Boolean filters are exactly true/false. String filters are nonempty valid Unicode, at most 256 Unicode scalars and 1024 UTF-8 bytes, with no ASCII control characters. Equality does not case-fold or normalize Unicode.
- Reusable page helper accepts a materialized collection of maps/objects, at most 10000 rows. Every row needs a unique valid string id. Referenced sort/filter values must match declared types and bounds; missing/null/invalid referenced values are INVALID_LIST_DATA. Other record fields are passed through unchanged.
- String sorting compares Unicode scalar values, not locale or UTF-16 code units. Integer and boolean ordering are natural, false before true. Filter, then stable ordering, then slicing. Return `{items,total,limit,offset,nextOffset}`; nextOffset is null at the end. Out-of-range offset returns an empty page, unchanged filtered total, and null nextOffset.
- Query failures are INVALID_LIST_QUERY (HTTP 400), trusted schema/data failures are generic HTTP 500 with their fixed code and no raw input echoed. Native core errors expose only those codes.
- Callers apply tenant/authorization visibility before invoking page helper. No SQL interpolation, database adapter, cursor encoding, cross-request snapshot guarantee, or streaming/unbounded collection claim. AIP-158 is a reference; this strict offset profile does not claim AIP conformance.

## Milestones and checks

1. Freeze contracts and shared scenarios; create common package skeletons. Record meaningful failing tests for absent APIs before implementing them.
2. Implement each new feature in all five native library projects with shared vector tests and focused edge cases. Confirm immutable policies, fail-closed decisions, parser bounds, Unicode scalar ordering, duplicate IDs, and stable pagination.
3. Add source feature index, catalog checker, and backward-compatible main CLI contexts. Preserve all existing auth context and init/check tests. New init requests fail before importing code or creating directories.
4. Compose real auth + server-owned membership + authorization + listing in a separate Python HTTP example. Verify anonymous/forged/revoked sessions, own/other/cross-tenant resources, role spoofing, hidden-row totals, bad queries, and provider failure. No production DB/SMTP is used by these new checks.
5. Run native unit/vector tests, common feature checker, actual HTTP consumer, TypeScript declarations, snapshot and packed npm checks, authentication regression and the project-required existing checks where affected. Preserve unrelated user state. Changes to CI must retain exact template parity.
6. Independently review the combined security and contract boundaries after implementation, resolve material findings, then record actual checks and limits. No further package publication is part of this task.

## References

- OWASP Authorization Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- Google AIP-158 pagination: https://google.aip.dev/158
- Google AIP-160 filtering: https://google.aip.dev/160 (a general filter language is out of scope here)
