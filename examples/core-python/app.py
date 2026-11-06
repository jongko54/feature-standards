"""Compose public auth and core APIs. Membership never comes from the request."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from feature_auth import Settings, create_app, current_user
from feature_standards.authorization import Grant, Policy, Principal, Resource
from feature_standards.listing import ListingError, ListingSchema, page, parse_query

POLICY = Policy([
    Grant("viewer", "documents:list", "tenant"),
    Grant("viewer", "documents:read", "owner"),
])
SCHEMA = ListingSchema(
    {"id": "string", "name": "string", "score": "integer", "active": "boolean"},
    {"name": "string", "score": "integer", "active": "boolean"},
)
# Product-owned fixtures, deliberately containing inaccessible records.
DOCUMENTS = (
    {"id": "own-b", "name": "Beta", "score": 2, "active": False, "tenantId": "tenant-a", "ownerId": "demo-user"},
    {"id": "other-owner", "name": "Private", "score": 10, "active": True, "tenantId": "tenant-a", "ownerId": "other-user"},
    {"id": "other-tenant", "name": "Secret", "score": 99, "active": True, "tenantId": "tenant-b", "ownerId": "demo-user"},
    {"id": "own-a", "name": "Alpha", "score": 2, "active": True, "tenantId": "tenant-a", "ownerId": "demo-user"},
)


def demo_membership(user: dict[str, str]) -> Principal | None:
    """Replace this server-owned provider with your current membership lookup."""
    if user["id"] == "demo-user":
        return Principal(user["id"], "tenant-a", ("viewer",))
    return None


def error(status: int, code: str):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": "Request could not be completed."}},
    )


def public_document(document):
    try:
        return {key: document[key] for key in ("id", "name", "score", "active")}
    except KeyError:
        raise ListingError("INVALID_LIST_DATA") from None


def create_core_app(
    *,
    membership: Callable[[dict[str, str]], Principal | None] = demo_membership,
    settings: Settings | None = None,
):
    application = create_app(settings=settings)

    @application.middleware("http")
    async def product_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def principal_for(user):
        try:
            principal = membership(user)
        except Exception:  # noqa: BLE001 -- Provider failure must deny without exposing internals.
            return None, error(503, "AUTHORIZATION_UNAVAILABLE")
        # Missing membership denies; the authenticated session alone grants nothing.
        if not isinstance(principal, Principal) or principal.subject_id != user["id"]:
            return None, error(403, "FORBIDDEN")
        return principal, None

    @application.get("/api/documents")
    def documents(request: Request, user: Annotated[dict[str, str], Depends(current_user)]):
        principal, failure = principal_for(user)
        if failure is not None:
            return failure
        if not POLICY.decide(principal, "documents:list", Resource(principal.tenant_id)).allowed:
            return error(403, "FORBIDDEN")
        try:
            # Scope before totals, filtering, sorting, or pagination.
            visible = [
                public_document(document) for document in DOCUMENTS
                if POLICY.decide(
                    principal, "documents:read", Resource(document["tenantId"], document["ownerId"])
                ).allowed
            ]
            raw = request.scope["query_string"].decode("utf-8", "strict")
            query = parse_query(raw, SCHEMA)
            return page(visible, query, SCHEMA)
        except UnicodeError:
            return error(400, "INVALID_LIST_QUERY")
        except ListingError as exc:
            return error(400 if exc.code == "INVALID_LIST_QUERY" else 500, exc.code)

    @application.get("/api/documents/{document_id}")
    def document(document_id: str, user: Annotated[dict[str, str], Depends(current_user)]):
        principal, failure = principal_for(user)
        if failure is not None:
            return failure
        found = next((item for item in DOCUMENTS if item["id"] == document_id), None)
        if found is None or not POLICY.decide(
            principal, "documents:read", Resource(found["tenantId"], found["ownerId"])
        ).allowed:
            return error(403, "FORBIDDEN")
        try:
            return public_document(found)
        except ListingError:
            return error(500, "INVALID_LIST_DATA")

    return application


app = create_core_app()
