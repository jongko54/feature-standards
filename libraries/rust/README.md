# Feature Standards Core — rust

Experimental 0.1.0 APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](https://github.com/jongko54/feature-standards/blob/main/docs/core-standards.md).

Install the published crate with `feature-standards-core = "=0.1.0"`. A source checkout can use a path dependency:

```toml
[dependencies]
feature-standards-core = { path = "/path/to/feature-standards/libraries/rust" }
```

Rust 1.93.1 or later, edition 2024. `authorization::{Policy, Grant, Principal, Resource}` provides native decisions; `listing::{Schema, parse_query, page}` uses serde_json records. Handle all Result errors. Do not confuse this crate with the separate `feature-standards-auth` authentication crate.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack rust --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; the Cargo archive also includes byte-identical package-local fixtures so its own tests remain runnable outside the checkout. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit or database adapter is implied. Check the repository release receipts for actual registry availability.
