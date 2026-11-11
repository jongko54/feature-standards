# Optional Python SDK connection

If you choose the original SDKs, start with [the working consumer](../../examples/core-python/app.py), [its manifest](../../examples/core-python/pyproject.toml) and [the focused brief](../ai-briefs/python.md). These are optional connection hints; the task defines the application's behavior and the implementation approach remains yours.

## Dependency and import boundary

Python 3.12+. The consumer declares `feature-standards-python-auth`, `feature-standards-core` and `uvicorn`. Its source mapping is:

```toml
[tool.uv.sources]
feature-standards-python-auth = { path = "../../implementations/python-fastapi" }
feature-standards-core = { path = "../../libraries/python" }
```

Those relative paths are from `examples/core-python/pyproject.toml`; a different app can point to the supplied checkout's corresponding directories. The [auth manifest](../../implementations/python-fastapi/pyproject.toml) and [core manifest](../../libraries/python/pyproject.toml) both currently declare 0.2.0. The historical published core 0.1.0 and this 0.2.0 source candidate are distinct.

```python
from feature_auth import Settings, create_app, current_user
from feature_standards.authorization import Grant, Policy, Principal, Resource
from feature_standards.listing import ListingError, ListingSchema, parse_query, page
```

`feature_auth` is the auth import name; `feature_standards` is the separate core package. An app-local `feature_auth.py`, `feature_auth/`, `feature_standards.py` or `feature_standards/` can shadow an installed dependency. Inspecting the loaded modules' `__file__` distinguishes the checkout/package from a local copy; the distribution name alone does not.

## Read composition

The consumer's `create_core_app` is example glue, not a package export. Its sequence is reusable with other routes, fields and permissions:

1. For a new auth-enabled app, `create_app(settings=..., store=...)` owns the auth lifespan. Product reads use `Depends(current_user)` on that same app/service, preserving an existing app's auth configuration.
2. Save `user["id"]`; pass `dict(user)` to the server's current membership lookup. Accept its `Principal(subject_id, tenant_id, roles)` only when the subject still matches. Missing/mismatched membership denies; provider failure closes access.
3. `Policy([Grant(role, permission, scope), ...])` declares explicit grants. A collection check uses `policy.decide(principal, list_permission, Resource(principal.tenant_id)).allowed`.
4. Each row's read check uses its trusted tenant/owner: `Resource(row_tenant, row_owner)`. Keep allowed rows, then project the task's public fields. This happens before totals or list processing.
5. `ListingSchema(sort_fields, filter_fields)` takes typed server-owned allowlists. Decode `request.scope["query_string"]` as strict UTF-8, without `?`; use `query = parse_query(raw, schema)` followed by `page(visible, query, schema)`. Return that result as JSON.
6. Item reads use the same session/membership and row permission; the example treats absent and inaccessible IDs alike. It maps invalid query/UTF-8 to 400, trusted listing failures to generic 500, and applies `no-store`/`nosniff` to all product responses. `current_user` raises the public `AuthError`; the SDK's installed exception handler uses its own fixed auth message. If the product requires a different envelope, register an application handler for product paths and retain the SDK handler for auth paths.

For example, after `app = create_app(...)`, an application requiring the fixed product message can adapt that public exception:

```python
from feature_auth import AuthError
from fastapi.responses import JSONResponse

sdk_auth_error = app.exception_handlers[AuthError]

@app.exception_handler(AuthError)
async def product_auth_error(request, error):
    if not request.url.path.startswith("/api/"):
        return await sdk_auth_error(request, error)
    headers = {**(error.headers or {}), "Cache-Control": "no-store",
               "X-Content-Type-Options": "nosniff"}
    return JSONResponse({"error": {"code": error.code,
                        "message": "Request could not be completed."}},
                        status_code=error.status, headers=headers)
```

Membership and resource attributes come from server services, rather than browser roles/tenant/subject claims. Permission names, grants, schema fields and projections are application choices; the example's document fixtures need not be reused.

`current_user` resolves identity only. Custom unsafe routes do not automatically receive Origin or CSRF enforcement. The auth service exposes `get_session(token)` and its session's `csrf`, but no dedicated non-destructive mutation-CSRF checker; `logout` also destroys the session.

API detail: [auth exports](../../implementations/python-fastapi/feature_auth/__init__.py), [auth HTTP adapter](../../implementations/python-fastapi/feature_auth/http.py), [core API](../../libraries/python/README.md), [common scope](README.md).
