"""FastAPI routes; authentication storage is injected through the service."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .core import (
    COOKIE_NAME,
    MAX_BODY_BYTES,
    AuthError,
    AuthService,
    AuthStore,
    Settings,
    normalize_email,
    valid_email,
)
from .service import build_service


def error_response(status: int, code: str, headers: dict | None = None) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    response_headers.update(headers or {})
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": code.replace("_", " ").lower()}},
        headers=response_headers,
    )


def require_origin(request: Request, settings: Settings) -> None:
    if request.headers.getlist("origin") != [settings.origin]:
        raise AuthError(403, "ORIGIN_DENIED")


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("Invalid JSON constant")


async def read_credentials(request: Request) -> tuple[str, str]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise AuthError(415, "UNSUPPORTED_MEDIA_TYPE")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise AuthError(413, "REQUEST_TOO_LARGE")
    try:
        data = json.loads(
            body.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant
        )
        if not isinstance(data, dict) or set(data) != {"email", "password"}:
            raise ValueError("Invalid object")
        if not isinstance(data["email"], str) or not isinstance(data["password"], str):
            raise ValueError("Invalid field type")
        email = normalize_email(data["email"])
        password = data["password"]
        if not valid_email(email) or not 1 <= len(password.encode("utf-8")) <= 1024:
            raise ValueError("Invalid field length")
        return email, password
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AuthError(400, "INVALID_REQUEST") from exc


def current_user(request: Request) -> dict[str, str]:
    """Return the current user, also usable as Depends(current_user)."""
    state: AuthService = request.app.state.auth
    session = state.get_session(request.cookies.get(COOKIE_NAME, ""))
    if session is None:
        raise AuthError(401, "UNAUTHENTICATED")
    return state.payload(session)["user"]


def create_app(
    *,
    settings: Settings | None = None,
    clock: Callable[[], float] = time.monotonic,
    store: AuthStore | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.auth = await run_in_threadpool(
            build_service, settings or Settings.from_env(), store, clock
        )
        try:
            yield
        finally:
            await run_in_threadpool(application.state.auth.store.close)

    application = FastAPI(
        title="Feature Standards Auth",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )

    @application.middleware("http")
    async def auth_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.exception_handler(AuthError)
    async def handle_auth_error(request: Request, error: AuthError):
        return error_response(error.status, error.code, error.headers)

    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, "HTTP_ERROR")
        return error_response(error.status_code, code, error.headers)

    @application.exception_handler(Exception)
    async def handle_internal_error(request: Request, error: Exception):
        return error_response(500, "INTERNAL_ERROR")

    @application.get("/healthz")
    def healthz(request: Request):
        state = request.app.state.auth
        state.store.health()
        return {"status": "ok", "profile": state.profile, "implementation": "python-fastapi"}

    @application.post("/auth/login")
    async def login(request: Request):
        state: AuthService = request.app.state.auth
        require_origin(request, state.settings)
        email, password = await read_credentials(request)
        token, session = await run_in_threadpool(
            state.authenticate,
            request.client.host if request.client else "unknown",
            email,
            password,
            request.cookies.get(COOKIE_NAME, ""),
        )
        response = JSONResponse(state.payload(session))
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=state.settings.session_ttl,
            path="/",
            secure=state.settings.secure_cookie,
            httponly=True,
            samesite="lax",
        )
        return response

    @application.get("/auth/me")
    def me(request: Request):
        state: AuthService = request.app.state.auth
        session = state.get_session(request.cookies.get(COOKIE_NAME, ""))
        if session is None:
            raise AuthError(401, "UNAUTHENTICATED")
        return state.payload(session)

    @application.post("/auth/logout")
    def logout(request: Request):
        state: AuthService = request.app.state.auth
        require_origin(request, state.settings)
        csrf_headers = request.headers.getlist("x-csrf-token")
        csrf = csrf_headers[0] if len(csrf_headers) == 1 else ""
        state.logout(request.cookies.get(COOKIE_NAME, ""), csrf)
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE_NAME,
            path="/",
            secure=state.settings.secure_cookie,
            httponly=True,
            samesite="lax",
        )
        return response

    return application
