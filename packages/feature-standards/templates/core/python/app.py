"""Compose SDK APIs with server-owned membership and bounded product records."""

import ipaddress
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from feature_auth import Settings, create_app, current_user
from feature_standards.authorization import Grant, Policy, Principal, Resource
from feature_standards.listing import ListingError, ListingSchema, page, parse_query

POLICY = Policy(
    [
        Grant("viewer", "documents:list", "tenant"),
        Grant("viewer", "documents:read", "owner"),
    ]
)
SCHEMA = ListingSchema(
    {"id": "string", "name": "string", "score": "integer", "active": "boolean"},
    {"name": "string", "score": "integer", "active": "boolean"},
)
# Product-owned fixtures, deliberately containing inaccessible records.
DOCUMENTS = (
    {
        "id": "own-b",
        "name": "Beta",
        "score": 2,
        "active": False,
        "tenantId": "tenant-a",
        "ownerId": "demo-user",
    },
    {
        "id": "other-owner",
        "name": "Private",
        "score": 10,
        "active": True,
        "tenantId": "tenant-a",
        "ownerId": "other-user",
    },
    {
        "id": "other-tenant",
        "name": "Secret",
        "score": 99,
        "active": True,
        "tenantId": "tenant-b",
        "ownerId": "demo-user",
    },
    {
        "id": "own-a",
        "name": "Alpha",
        "score": 2,
        "active": True,
        "tenantId": "tenant-a",
        "ownerId": "demo-user",
    },
)


def demo_membership(user: dict[str, str]) -> Principal | None:
    """Public fixture enabled only by explicit AUTH_DEMO=true."""
    if user["id"] == "demo-user":
        return Principal(user["id"], "tenant-a", ("viewer",))
    return None


def current_membership(user: dict[str, str]) -> Principal | None:
    """Replace with a trusted current membership lookup; unconfigured means deny."""
    return None


def current_documents() -> Sequence[Mapping[str, object]]:
    """Replace with a trusted bounded document source for your application."""
    return ()


def error(status: int, code: str):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": "Request could not be completed."}},
    )


def public_document(document):
    try:
        return {key: document[key] for key in ("id", "name", "score", "active")}
    except (KeyError, TypeError):
        raise ListingError("INVALID_LIST_DATA") from None


def resource_for(document):
    if (
        not isinstance(document, Mapping)
        or not isinstance(document.get("tenantId"), str)
        or not isinstance(document.get("ownerId"), str)
    ):
        raise ListingError("INVALID_LIST_DATA")
    return Resource(document["tenantId"], document["ownerId"])


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_core_app(
    *,
    membership: Callable[[dict[str, str]], Principal | None] | None = None,
    documents: Callable[[], Sequence[Mapping[str, object]]] | None = None,
    settings: Settings | None = None,
):
    config = settings or Settings.from_env()
    if config.store != "memory" or config.account_lifecycle:
        raise ValueError("This starter supports browser-session-v1 memory sessions only")
    if config.demo and not loopback(os.environ.get("AUTH_HOST", "127.0.0.1")):
        raise ValueError("Explicit demo requires a loopback AUTH_HOST")
    # Only explicit demo mode enables public fixture membership and resources.
    membership_provider = membership or (
        demo_membership if config.demo else current_membership
    )
    document_provider = documents or (
        (lambda: DOCUMENTS) if config.demo else current_documents
    )
    application = create_app(settings=config)

    @application.middleware("http")
    async def product_headers(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.method != "GET":
                response = error(405, "METHOD_NOT_ALLOWED")
                response.headers["Allow"] = "GET"
            else:
                response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        else:
            response = await call_next(request)
        return response

    def principal_for(user):
        subject = user["id"]
        try:
            principal = membership_provider(dict(user))
        except Exception:  # noqa: BLE001 -- Provider failure must deny without exposing internals.
            return None, error(503, "AUTHORIZATION_UNAVAILABLE")
        # Missing membership denies; the authenticated session alone grants nothing.
        if not isinstance(principal, Principal) or principal.subject_id != subject:
            return None, error(403, "FORBIDDEN")
        return principal, None

    def trusted_documents():
        try:
            rows = document_provider()
            if not isinstance(rows, (list, tuple)):
                raise ListingError("INVALID_LIST_DATA")
            return rows
        except Exception:  # noqa: BLE001 -- Product-source details stay private.
            raise ListingError("INVALID_LIST_DATA") from None

    @application.get("/api/profile")
    def profile(user: Annotated[dict[str, str], Depends(current_user)]):
        return {"user": user}

    @application.get("/api/documents")
    def list_documents(
        request: Request, user: Annotated[dict[str, str], Depends(current_user)]
    ):
        principal, failure = principal_for(user)
        if failure is not None:
            return failure
        if not POLICY.decide(
            principal, "documents:list", Resource(principal.tenant_id)
        ).allowed:
            return error(403, "FORBIDDEN")
        try:
            # Scope before totals, filtering, sorting, or pagination.
            visible = [
                public_document(document)
                for document in trusted_documents()
                if POLICY.decide(
                    principal,
                    "documents:read",
                    resource_for(document),
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
    def document(
        document_id: str, user: Annotated[dict[str, str], Depends(current_user)]
    ):
        principal, failure = principal_for(user)
        if failure is not None:
            return failure
        try:
            found = None
            for item in trusted_documents():
                if not isinstance(item, Mapping):
                    raise ListingError("INVALID_LIST_DATA")
                if item.get("id") == document_id:
                    found = item
                    break
            if found is None or not POLICY.decide(
                principal, "documents:read", resource_for(found)
            ).allowed:
                return error(403, "FORBIDDEN")
            return public_document(found)
        except ListingError:
            return error(500, "INVALID_LIST_DATA")

    return application


app = create_core_app()
