"""Use existing session auth and trusted membership before a scoped DB listing."""

import os
from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from feature_auth import Settings, create_app, current_user
from feature_standards.authorization import Grant, Policy, Principal, Resource
from feature_standards.listing import ListingError, ListingSchema, parse_query
from feature_standards.postgres_listing import PostgresListing, VisibilityScope
from psycopg.conninfo import conninfo_to_dict

POLICY = Policy(
    [
        Grant("viewer", "documents:list", "tenant"),
        Grant("viewer", "documents:read", "owner"),
        Grant("editor", "documents:list", "tenant"),
        Grant("editor", "documents:read", "tenant"),
    ]
)
SCHEMA = ListingSchema(
    {"id": "string", "name": "string", "score": "integer", "active": "boolean"},
    {"name": "string", "score": "integer", "active": "boolean"},
)
_UNSAFE_LIBPQ_ENV = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")


def demo_membership(user):
    """Demo only: replace with your server-owned current membership lookup."""
    return (
        Principal(user["id"], "tenant-a", ("viewer",))
        if user["id"] == "demo-user"
        else None
    )


def connect_database():
    """Demo default: only an explicitly designated loopback test database."""
    if any(name in os.environ for name in _UNSAFE_LIBPQ_ENV):
        raise ListingError("LISTING_UNAVAILABLE")
    uri = os.environ.get("FEATURE_STANDARDS_LISTING_DATABASE_URL")
    if not uri:
        raise ListingError("LISTING_UNAVAILABLE")
    try:
        fields = conninfo_to_dict(uri)
    except psycopg.Error:
        raise ListingError("LISTING_UNAVAILABLE") from None
    if (
        fields.get("host") not in ("127.0.0.1", "localhost", "::1")
        or not fields.get("port", "").isdigit()
        or not 1 <= int(fields.get("port", "0")) <= 65535
        or not fields.get("dbname", "").startswith("feature_standards_test")
        or fields.get("sslmode") != "disable"
        or any(key in fields for key in ("hostaddr", "service", "options"))
    ):
        raise ListingError("LISTING_UNAVAILABLE")
    address = "127.0.0.1" if fields["host"] == "localhost" else fields["host"]
    # Explicit parameters override libpq defaults even if the environment changes
    # after validation. Host remains available for password-file identity.
    return psycopg.connect(uri, hostaddr=address, options="")


def error(status, code):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": "Request could not be completed."}},
    )


def create_postgres_core_app(
    *,
    settings: Settings | None = None,
    membership: Callable = demo_membership,
    connect: Callable = connect_database,
    store: PostgresListing | None = None,
):
    application = create_app(settings=settings)
    store = store or PostgresListing(
        schema=SCHEMA,
        table=(
            os.environ.get("FEATURE_STANDARDS_LISTING_SCHEMA", "public"),
            os.environ.get("FEATURE_STANDARDS_LISTING_TABLE", "documents"),
        ),
        columns={"id": "id", "name": "name", "score": "score", "active": "active"},
        tenant_column="tenant_id",
        owner_column="owner_id",
    )

    @application.middleware("http")
    async def product_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.get("/api/documents")
    def documents(
        request: Request, user: Annotated[dict[str, str], Depends(current_user)]
    ):
        authenticated_subject = user["id"]
        try:
            principal = membership(dict(user))
        except Exception:  # noqa: BLE001 -- An unavailable trusted provider must deny.
            return error(503, "AUTHORIZATION_UNAVAILABLE")
        if (
            not isinstance(principal, Principal)
            or principal.subject_id != authenticated_subject
        ):
            return error(403, "FORBIDDEN")
        resource = Resource(principal.tenant_id)
        if not POLICY.decide(principal, "documents:list", resource).allowed:
            return error(403, "FORBIDDEN")
        if POLICY.decide(principal, "documents:read", resource).allowed:
            scope = VisibilityScope(principal.tenant_id, None)
        elif POLICY.decide(
            principal,
            "documents:read",
            Resource(principal.tenant_id, principal.subject_id),
        ).allowed:
            scope = VisibilityScope(principal.tenant_id, principal.subject_id)
        else:
            return error(403, "FORBIDDEN")
        try:
            raw = request.scope["query_string"].decode("utf-8", "strict")
            # Bad queries do not open a DB connection, even during an outage.
            parse_query(raw, store.schema)
            with connect() as connection:
                return store.page(connection, raw, scope)
        except UnicodeError:
            return error(400, "INVALID_LIST_QUERY")
        except ListingError as exc:
            status = (
                400
                if exc.code == "INVALID_LIST_QUERY"
                else 503
                if exc.code == "LISTING_UNAVAILABLE"
                else 500
            )
            return error(status, exc.code)
        except psycopg.Error:
            return error(503, "LISTING_UNAVAILABLE")

    return application


app = create_postgres_core_app()
