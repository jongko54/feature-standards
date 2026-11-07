# PostgreSQL listing source profile

`postgres-list-v1` is an experimental **Python-only source profile**. It adds a parameterized database adapter while the published core 0.1.0 and `offset-list-v1` materialized helper remain unchanged. Python core 0.2.0 is a source candidate; this document does not establish registry publication. See the [normative profile](../features/listing/postgres-list-v1.md).

## Integrate with current authorization

Use the optional driver dependency from the trusted checkout:

```sh
uv pip install './libraries/python[postgres]'
```

Construct `PostgresListing` with a server-owned table, typed logical-field/column allowlist and tenant/owner column names. The underlying table must enforce the profile's declared types, non-null fields, valid identifiers and unique IDs. The adapter validates returned rows; it does not scan unrelated rows to repair or certify a table. Database constraints and index design remain application responsibilities.

Authenticate with the existing session library, load current trusted membership and evaluate the collection/read permissions first. Derive a required `VisibilityScope(tenant_id, owner_id)` from that result. Passing `None` for `owner_id` explicitly opts into tenant-wide visibility; it must correspond to a server policy grant. Headers, query fields and request bodies cannot choose the scope, table or column map.

Pass an idle psycopg connection and the original raw query to `adapter.page(connection, raw_query, scope)`. Count and page run in a read-only repeatable-read transaction with identical scope/filter predicates. The caller retains connection ownership. An active caller transaction is rejected without rollback or commit of caller work. There is no cross-request snapshot guarantee.

The database can contain more than 10,000 rows. `limit` remains 1–100 and `offset` remains 0–10,000. `nextOffset` is null when the next offset would exceed that navigation bound, even if the exact `total` shows more rows. This profile does not provide cursor pagination or traversal of arbitrarily deep offsets.

## Errors and tests

Map `INVALID_LIST_QUERY` to 400. Return a generic 500 for trusted schema/scope/transaction/data errors and a generic 503 for `LISTING_UNAVAILABLE`; do not return driver messages, SQL, connection strings or row contents. The adapter neither applies migrations nor seeds data.

The [separate HTTP demo](../examples/core-python-postgres/README.md) composes authentication, current membership, authorization and database listing. Its fixture data and demo membership are for explicit local use.

```sh
PYTHONPATH=libraries/python uv run --frozen --project tools python -m unittest discover -s libraries/python/tests -p test_postgres_listing.py -v
uv run --frozen --project tools python tests/postgres_listing_conformance.py
```

Real database conformance requires either `FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL` for an explicitly isolated loopback test database or the test harness's task-owned local PostgreSQL process. It creates and removes only its random fixture schema. See the normative profile and HTTP demo README for setup requirements. The SQL fixture under `tests/fixtures` is not a production migration.

The demo/test factories reject inherited `PGHOSTADDR`, `PGSERVICE`, `PGSERVICEFILE` and `PGOPTIONS`, including empty values, and pin the validated connection destination explicitly. They do not modify the process-wide environment. This protects the fixture boundary; the reusable adapter accepts a caller-owned connection and leaves production connection configuration to that caller.
