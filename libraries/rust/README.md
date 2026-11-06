# Feature Standards Core — rust

Unpublished experimental 0.1.0 source APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](../../docs/core-standards.md).

Use a path dependency:

```toml
[dependencies]
feature-standards-core = { path = "/path/to/feature-standards/libraries/rust" }
```

Rust 1.93.1 or later, edition 2024. `authorization::{Policy, Grant, Principal, Resource}` provides native decisions; `listing::{Schema, parse_query, page}` uses serde_json records. Handle all Result errors. This source crate has `publish = false`; do not confuse it with the published `feature-standards-auth` crate.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack rust --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit, database adapter or registry release is implied.
