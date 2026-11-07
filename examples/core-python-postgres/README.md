# PostgreSQL auth + authorization + listing consumer

This source example uses the existing Python session-auth library and experimental Python core `0.2.0` with its optional `postgres` extra. The new adapter/profile is a source candidate; the published core `0.1.0` package does not contain it. It is separate from the bounded materialized `offset-list-v1` profile.

```sh
uv sync --frozen --project examples/core-python-postgres
FEATURE_STANDARDS_LISTING_DATABASE_URL='postgresql://YOUR_TEST_READ_ROLE@127.0.0.1:5432/feature_standards_test_documents?sslmode=disable' \
  AUTH_DEMO=true AUTH_COOKIE_SECURE=false AUTH_STORE=memory \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 \
  uv run --frozen --project examples/core-python-postgres uvicorn app:app \
  --app-dir examples/core-python-postgres --no-proxy-headers --host 127.0.0.1 --port 8014
```

The default demo connection factory requires an explicit loopback host/port, database name beginning `feature_standards_test`, and `sslmode=disable`. It rejects remote hosts and never falls back to `AUTH_DATABASE_URL`. The default relation is `public.documents`; override the trusted `FEATURE_STANDARDS_LISTING_SCHEMA` and `FEATURE_STANDARDS_LISTING_TABLE` at server configuration time. No database migration, table creation, seeding or SMTP delivery runs at application startup or during requests. Provide your own explicit table migration with the invariants in [postgres-list-v1](../../features/listing/postgres-list-v1.md). The constrained test table in `tests/fixtures/core_listing.sql` is an example for an isolated test schema, not an automatic production migration.

The demo factory and database test harness deliberately reject inherited `PGHOSTADDR`, `PGSERVICE`, `PGSERVICEFILE` or `PGOPTIONS` variables, including empty values, before connection or fixture setup. A loopback hostname alone cannot constrain libpq's inherited address/service defaults. They explicitly pin the validated numeric `hostaddr` (`localhost` maps to `127.0.0.1`) and empty connection options; the owned Unix-socket fixture pins its socket path, empty hostaddr, user and database. No process-global environment variables are rewritten. This strict guard belongs to the demo/test connection factories; the reusable adapter accepts the caller's connection without reading these variables.

`create_postgres_core_app(settings=..., membership=..., connect=..., store=...)` accepts internal application-construction providers. The connection factory returns a fresh idle connection exclusively owned by that request; the application closes it. There is no public policy, role, provider-control or fixture endpoint. The demo membership maps only the existing authenticated demo user to tenant-a/viewer. For a product integration, supply your real current membership provider, auth settings and an explicitly configured least-privilege connection factory with appropriate TLS rather than copying the demo provider.

The product route is `GET /api/documents`. Authenticate with `POST /auth/login`, the exact configured Origin and the existing demo credentials; keep its HttpOnly session cookie. A viewer's explicit read grant produces `VisibilityScope(tenant, authenticated_subject)`. An editor's explicit tenant grant produces `VisibilityScope(tenant, None)`. The adapter scopes both count and page SQL before computing totals. Role/tenant/subject headers or query keys cannot create these grants. Browser authorization is never authoritative.

The DB can contain more than 10000 rows, but the raw query preserves limit<=100 and offset<=10000. `nextOffset` becomes null when its next offset would exceed 10000, even if the complete filtered total is larger. Separate requests do not share a snapshot; this is not cursor pagination. A request uses a read-only repeatable-read snapshot for its own count/page pair.

Run the real TCP HTTP tests with a task-owned local PostgreSQL prefix, or an explicit safe listing test URI:

```sh
FEATURE_STANDARDS_LISTING_PG_BIN=/path/to/postgresql/bin \
  uv run --frozen --project examples/core-python-postgres \
  python -m unittest discover -s examples/core-python-postgres -p test_app.py -v
```

Tests create only a random temporary schema/cluster and exercise real login/logout, current membership revocation, tenant/owner scoping before totals, malicious input and sanitized provider/database failure. They do not contact an external SMTP service or a product database.
