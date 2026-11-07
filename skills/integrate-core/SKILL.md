---
name: integrate-core
description: Integrate the authorization or listing contracts in Python, Go, Java, Rust or JavaScript/TypeScript.
---

# Integrate core features

Read the target project's instructions and dirty state. Preserve its auth and product behavior. Select one feature and stack from `features/catalog.json`; read only that catalog's selected specification, entrypoints and library README. Check the selected package publication field and `docs/core-release-0.1.0.json`. If a matching public download and fresh registry consumer are recorded, use that pinned registry version in the target project. Otherwise use a path dependency or the checked-out source. Do not infer publication from a package name or enabled publish metadata, invent a registry version, or silently use the authentication generator.

When the trusted source CLI is 0.4.0 or later, `context --compact` provides API/consumer/rule reading paths first. Read those before expanding the full command inventory; retrieve the selected contract and checks when the integration requires them. Published CLI 0.3.2 has only the full context format. Do not assume it accepts the new flag or automatically upgrade a target application's dependencies.

For authorization, preserve the target's real authenticated identity. Load current membership and resource attributes from trusted server services on each request. Never accept roles, subject or tenant from browser headers/body/query. Declare explicit role-permission-scope grants; deny by default, enforce tenant isolation, require subject ownership for owner scope, and fail closed when membership is unavailable. Client helpers control presentation only.

For listing, supply the original raw query (without `?`) and a server-owned schema allowlist before framework coercion. Apply authorization visibility before computing filtered totals. Validate IDs, all referenced data types and bounded sizes. Map INVALID_LIST_QUERY to 400 and trusted schema/data failures to generic 500 responses; do not echo raw inputs. Do not interpolate sorting/filter fields into SQL. The provided helper is for bounded materialized data, not an unbounded database adapter.

If database listing is requested, select `postgres-list-v1` only for Python in the current source candidate. Read `docs/postgres-listing.md` and its profile-specific entrypoints/consumer; the historical 0.1.0 publication receipt does not publish the 0.2.0 source adapter. Require explicit trusted tenant/owner visibility, an idle exclusively owned connection and the declared typed table constraints. Count/page share a request-local read-only repeatable-read transaction; offset navigation is capped at 10,000 and does not supply a cursor. Do not run fixture SQL or migrations against an existing application database without its explicit scope.

Import the public APIs from `libraries/<language>`; see `examples/core-python`, `examples/core-go`, `examples/core-java` or `examples/core-rust` for real auth + permission + materialized listing HTTP composition. Preserve the original authenticated subject and pass a copy to mutable membership providers; a provider cannot redefine the session identity. Keep provider injections internal to application construction; do not expose testing bypass endpoints. Do not copy demo identities into an existing production account system.

Run the catalog's exact native checker command and the target application's own integration tests. For Python composition run `uv run --frozen --project examples/core-python python tests/core_consumer_conformance.py`. Report profile, source revision, changed integration points, actual commands and untested boundaries. Native vectors, TCP HTTP, browser verification, security audits, AI speed measurements and registry publication are separate evidence.

Use `python3 tools/check_core_consumers.py --stack <backend>` for the selected real HTTP suite. Database-profile checks additionally require their isolated fixture environment. Source consumers, installed archives and public registry consumers are different evidence; report which one ran.
