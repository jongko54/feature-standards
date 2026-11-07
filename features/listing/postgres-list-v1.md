# PostgreSQL listing: postgres-list-v1

Status: experimental Python source profile. It is additive to `offset-list-v1`; it does not change that profile or claim equivalent database adapters in the other languages. Registry publication is tracked separately.

## Public boundary

`feature_standards.postgres_listing` provides `VisibilityScope(tenant_id, owner_id)` and immutable `PostgresListing(schema=..., table=(schema_name, table_name), columns={logical_field: database_column}, tenant_column=..., owner_column=...)`. Call `adapter.page(connection, raw_query, scope)` with an idle synchronous psycopg 3 connection. The caller owns and closes the connection. Install the Python core's optional `postgres` extra; normal core imports have no driver dependency.

The caller authenticates the session, loads current membership and policy from trusted server providers, and decides the permitted scope before constructing `VisibilityScope`. Both arguments are required. An owner ID restricts visibility to that tenant and owner; explicit `None` permits the whole tenant only after a matching tenant-wide policy grant. Missing/forged scopes and invalid identifiers fail closed. Browser headers, query parameters and request bodies are never sources for scope, relation, columns or schema. The adapter is a scoped data reader, not a membership or policy authority.

Relation/schema/column names use `[a-z_][a-z0-9_]{0,62}`. Logical public fields are exactly the union of the supplied `ListingSchema` sort/filter fields; every field maps to one distinct database column. Configuration is copied and frozen. SQL identifiers are composed with psycopg `Identifier`; every scope, filter, limit and offset value is bound separately. There is no raw SQL predicate, expression, join, client-selected table or client-selected projection API.

## Query and result

Reuse the complete strict raw-query rules and typed schema of `offset-list-v1`: maximum 2048 bytes/16 pairs, duplicate/unknown-key rejection, exact equality filters, limit 1..100 and offset 0..10000. Parse and validate the query before opening a database transaction. The database may contain more than 10000 matching rows; it is not materialized into the process.

The result remains `{items,total,limit,offset,nextOffset}`. `total` counts only rows satisfying the trusted visibility scope and all filters. Returned items contain only the explicitly configured public columns. String equality and ordering use explicit `COLLATE "C"` in a UTF-8 database, giving exact scalar ordering rather than the database's default locale. Descending non-ID sort still breaks ties by ID ascending; sorting by ID follows the requested direction. Out-of-range offsets return an empty list and unchanged total.

`nextOffset` is the next permitted offset, or null when no further rows match **or the next offset would exceed 10000**. This bounded navigation window can end before the complete database result set. For example, offset 10000/limit 100/total 12005 returns 100 rows and null nextOffset. This profile does not provide cursor traversal or unrestricted deep pagination.

## Database invariants and failures

The configured relation is a trusted ordinary PostgreSQL table in a UTF-8 database. Its ID column is globally unique and NOT NULL text/varchar matching `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`. Tenant IDs use the same grammar and are NOT NULL. Owner IDs are either null or use that grammar. String fields are NOT NULL text/varchar: 1..256 Unicode scalars, at most 1024 UTF-8 bytes, without ASCII controls U+0000..U+001F/U+007F. Integer fields are NOT NULL `smallint`, `integer` or `bigint` constrained to +/-9007199254740991. Boolean fields are NOT NULL `boolean`. Domains/custom equality types such as citext, arbitrary views and user-defined operators/functions are outside this profile.

The operator must enforce these invariants at writes with primary/unique keys, types, NOT NULL and CHECK constraints. The adapter validates each returned public row, but does not scan every unselected row to establish those invariants. This is deliberately different from the materialized v1 helper's all-referenced-row validation. See `tests/fixtures/core_listing.sql` for a constrained fixture; applications must provide their own explicit migration. The adapter never migrates or seeds a database.

Each call starts one `REPEATABLE READ READ ONLY` transaction and applies the identical visibility/filter predicate to count and page queries. They share one snapshot even if another transaction commits between them. Active or failed caller transactions are rejected before SQL; they are never committed, rolled back or silently nested by the adapter. Its own success/error transaction exits leave an available connection idle, without changing session isolation/access defaults. A connection must be exclusively checked out to this call; concurrent users of the same connection are unsupported.

Query errors expose only `INVALID_LIST_QUERY` (HTTP 400). Invalid schema, scope, connection transaction state or returned data expose fixed `INVALID_LIST_SCHEMA`, `INVALID_LIST_SCOPE`, `INVALID_LIST_TRANSACTION` or `INVALID_LIST_DATA` codes (generic HTTP 500). Missing optional driver, unavailable/closed connection and PostgreSQL execution failures expose only `LISTING_UNAVAILABLE` (generic HTTP 503). No raw query, database name, SQL, credentials or provider exception text belongs in an HTTP response. Responses should use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.

The transaction snapshot is scoped to a single call. Separate page requests can see inserts/deletes and offset movement. Exact COUNT and high offsets can be costly; operators provide appropriate visibility/sort/filter indexes, database timeouts, least-privilege read roles and service capacity. This profile is not a security audit, load benchmark, cursor/snapshot token or cross-language database conformance claim.

## Verification

```sh
PYTHONPATH=libraries/python uv run --frozen --project tools python -m unittest discover -s libraries/python/tests -p test_postgres_listing.py -v
FEATURE_STANDARDS_LISTING_PG_BIN=/path/to/postgresql/bin \
  uv run --frozen --project tools python tests/postgres_listing_conformance.py
```

Alternatively set `FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL` to an explicit loopback PostgreSQL URI with port, `sslmode=disable` and database name beginning `feature_standards_test`. The harness creates/drops only its random `core_listing_*` schema. Without that URI it creates and stops its own temporary cluster, with TCP disabled; it never uses `AUTH_DATABASE_URL` or modifies an existing service.

Demo/test connection factories reject inherited `PGHOSTADDR`, `PGSERVICE`, `PGSERVICEFILE` and `PGOPTIONS` variables before any connection/fixture I/O, including variables with empty values. For configured TCP connections they pass an explicit validated numeric hostaddr (`localhost` maps to `127.0.0.1`; `::1` remains `::1`) and empty options. The owned Unix-socket fixture uses an explicit socket path, empty hostaddr, test user and database. These parameters prevent environment address defaults from redirecting the validated target without modifying process-global environment state. The reusable adapter itself operates on a caller-owned connection and has no environment policy.

See PostgreSQL's [connection parameters](https://www.postgresql.org/docs/current/libpq-connect.html) and [environment defaults](https://www.postgresql.org/docs/current/libpq-envars.html) for the distinction between the host name and actual host address.

The real DB suite checks visibility before totals, parameterized attack strings, typed filters, Unicode/tie ordering, a 12005-row dataset, an interleaved committed writer, refusal of caller transactions, read-only enforcement and rollback/connection reuse. Local native boundary tests do not substitute for these database checks.

Transaction behavior follows [psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) and [PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html). SQL composition follows [psycopg Identifier](https://www.psycopg.org/psycopg3/docs/api/sql.html); collation behavior follows [PostgreSQL collation support](https://www.postgresql.org/docs/current/collation.html).
