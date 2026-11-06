# Feature Standards Core — python

Unpublished experimental 0.1.0 source APIs for `authorization/rbac-v1` and `listing/offset-list-v1`. Authentication remains in its existing package. These modules implement the [shared normative contracts](../../docs/core-standards.md).

```python
from feature_standards import Grant, Policy, Principal, Resource, ListingSchema, parse_query, page
policy = Policy([Grant("viewer", "documents:read", "owner")])
decision = policy.decide(Principal("user-1", "tenant-a", ("viewer",)), "documents:read", Resource("tenant-a", "user-1"))
schema = ListingSchema({"id": "string", "score": "integer"}, {"score": "integer"})
result = page([{"id": "a", "score": 1}], parse_query("limit=20&sort=-score", schema), schema)
```

Use `uv pip install ./libraries/python` from a checkout, or a local path dependency. Python >=3.12, no runtime dependencies. A separate real HTTP consumer is in `examples/core-python`.

Run both native feature suites from the repository root:

```sh
python3 tools/check_core_features.py --stack python --feature all
```

Each native test suite consumes `features/authorization/scenarios.json` and `features/listing/scenarios.json`; source-checkout tests intentionally use repository-relative fixture paths. Runtime consumers do not need those fixture files. Apply trusted current membership, server resource tenant/owner, deny-by-default policy, and authorization scoping before listing totals. Listing accepts only bounded materialized data, exact filters, and a strict raw query string. No production audit, database adapter or registry release is implied.
