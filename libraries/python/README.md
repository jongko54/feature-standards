# Feature Standards Core — python

Experimental 0.1.0 APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](https://github.com/jongko54/feature-standards/blob/main/docs/core-standards.md).

```python
from feature_standards import Grant, Policy, Principal, Resource, ListingSchema, parse_query, page
policy = Policy([Grant("viewer", "documents:read", "owner")])
decision = policy.decide(Principal("user-1", "tenant-a", ("viewer",)), "documents:read", Resource("tenant-a", "user-1"))
schema = ListingSchema({"id": "string", "score": "integer"}, {"score": "integer"})
result = page([{"id": "a", "score": 1}], parse_query("limit=20&sort=-score", schema), schema)
```

Install the published package with `pip install feature-standards-core==0.1.0`. For checkout development, use `uv pip install ./libraries/python` or a local path dependency. Python >=3.12, no runtime dependencies. A separate real HTTP consumer is in `examples/core-python`.

This checkout is a **0.2.0 source candidate**. It adds an optional Python-only PostgreSQL adapter under `feature_standards.postgres_listing`; the published 0.1.0 wheel does not contain it. Install the candidate from source with `uv pip install './libraries/python[postgres]'`. Normal core imports remain driver-free. `PostgresListing` requires a trusted typed relation and explicit `VisibilityScope(tenant_id, owner_id)`; pass an idle psycopg connection and the original raw query to `page`. See [the database profile guide](../../docs/postgres-listing.md) for constraints, scope, navigation bounds and errors. This source version is not marked published without a matching registry receipt.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack python --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit or database adapter is implied. Check the repository release receipts for actual registry availability.
