# Authentication + authorization + listing consumer

A separate FastAPI project importing three reusable source libraries. No auth code is copied. Python core 0.1.0 is published on PyPI; this source conformance example intentionally resolves both local packages from this checkout. See [the registry receipt](../../docs/core-release-0.1.0.json) for independent public-download and fresh-consumer checks.

```sh
uv sync --frozen --project examples/core-python
AUTH_DEMO=true AUTH_COOKIE_SECURE=false AUTH_STORE=memory AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 uv run --frozen --project examples/core-python uvicorn app:app --app-dir examples/core-python --no-proxy-headers --host 127.0.0.1 --port 8010
uv run --frozen --project examples/core-python python tests/core_consumer_conformance.py
```

Local demo login: `POST /auth/login` with the existing demo email/password and exact Origin. Keep the returned HttpOnly `fs_session` cookie for `GET /api/documents` or `/api/documents/own-a`. Logout uses the existing session CSRF contract. The product routes are GET-only.

`create_core_app(membership=..., settings=...)` accepts a trusted server-owned membership provider. The example provider maps the real authenticated demo-user to tenant-a/viewer; replace it with your application's current membership lookup. The policy grants tenant collection access and owner-only document read. Fixtures include inaccessible rows so list totals prove visibility is applied before paging. No role header or public provider-control route exists. The HTTP test changes its private provider in process while serving actual TCP requests, proving revocation and failure behavior.

Production membership persistence, database pagination, additional native HTTP examples, policy management and a dedicated React UI are not included. The five core libraries themselves run the same shared vectors. See [the contract guide](../../docs/core-standards.md).
