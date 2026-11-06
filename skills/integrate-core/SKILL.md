---
name: integrate-core
description: Integrate the source authorization or listing contracts in Python, Go, Java, Rust or JavaScript/TypeScript.
---

# Integrate core features

Read the target project's instructions and dirty state. Preserve its auth and product behavior. Select one feature and stack from `features/catalog.json`; read only that catalog's selected specification, entrypoints and library README. New core packages are unpublished source APIs: use a path dependency or the checked-out source. Do not invent a registry version or silently use the authentication generator.

For authorization, preserve the target's real authenticated identity. Load current membership and resource attributes from trusted server services on each request. Never accept roles, subject or tenant from browser headers/body/query. Declare explicit role-permission-scope grants; deny by default, enforce tenant isolation, require subject ownership for owner scope, and fail closed when membership is unavailable. Client helpers control presentation only.

For listing, supply the original raw query (without `?`) and a server-owned schema allowlist before framework coercion. Apply authorization visibility before computing filtered totals. Validate IDs, all referenced data types and bounded sizes. Map INVALID_LIST_QUERY to 400 and trusted schema/data failures to generic 500 responses; do not echo raw inputs. Do not interpolate sorting/filter fields into SQL. The provided helper is for bounded materialized data, not an unbounded database adapter.

Import the public APIs from `libraries/<language>`; see `examples/core-python` for a real auth + permission + listing HTTP composition. Keep provider injections internal to application construction; do not expose testing bypass endpoints. Do not copy demo identities into an existing production account system.

Run the catalog's exact native checker command and the target application's own integration tests. For Python composition run `uv run --frozen --project examples/core-python python tests/core_consumer_conformance.py`. Report profile, source revision, changed integration points, actual commands and untested boundaries. Native vectors, TCP HTTP, browser verification, security audits, AI speed measurements and registry publication are separate evidence.
