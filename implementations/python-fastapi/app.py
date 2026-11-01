"""browser-session-v1의 단일 프로세스 FastAPI 참조 서버."""

from __future__ import annotations

import hmac
import ipaddress
import json
import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

COOKIE_NAME = "fs_session"
MAX_BODY_BYTES = 4096
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "correct-horse-battery-staple"
ASCII_EMAIL_WHITESPACE = "\t\n\v\f\r "
ASCII_EMAIL_LOWERCASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def normalize_email(email: str) -> str:
    """Unicode 테이블과 무관하게 계약의 ASCII 정규화만 수행한다."""
    return email.strip(ASCII_EMAIL_WHITESPACE).translate(ASCII_EMAIL_LOWERCASE)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default).lower())
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    if not raw.isascii() or not raw.isdecimal() or int(raw) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(raw)


def valid_email(email: str) -> bool:
    return "@" in email and 0 < len(email.encode("utf-8")) <= 254


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    demo: bool
    email: str
    password: str = field(repr=False)
    origin: str = "http://127.0.0.1:5173"
    secure_cookie: bool = True
    session_ttl: int = 1800
    rate_limit_max: int = 5
    rate_limit_window: int = 60

    @classmethod
    def from_env(cls) -> Settings:
        demo = env_bool("AUTH_DEMO", False)
        origin = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173")
        secure = env_bool("AUTH_COOKIE_SECURE", True)
        parsed = urlsplit(origin)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("AUTH_ALLOWED_ORIGIN has an invalid port") from exc
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"{parsed.scheme}://{parsed.netloc}"
            or "*" in origin
            or any(char.isspace() for char in origin)
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("AUTH_ALLOWED_ORIGIN must be an exact HTTP(S) origin")
        if not demo and parsed.scheme != "https":
            raise ValueError("Non-demo mode requires an HTTPS origin")
        if not secure and not (demo and is_loopback(parsed.hostname)):
            raise ValueError("Insecure cookies require demo mode with a loopback origin")
        email = DEMO_EMAIL if demo else normalize_email(os.environ.get("AUTH_USER_EMAIL", ""))
        password = DEMO_PASSWORD if demo else os.environ.get("AUTH_USER_PASSWORD", "")
        try:
            valid_credentials = valid_email(email) and 1 <= len(password.encode("utf-8")) <= 1024
        except UnicodeError:
            valid_credentials = False
        if not valid_credentials:
            raise ValueError("A valid AUTH_USER_EMAIL and AUTH_USER_PASSWORD are required")
        env_positive_int("AUTH_PORT", 8000)
        if int(os.environ.get("AUTH_PORT", "8000")) > 65535:
            raise ValueError("AUTH_PORT must be at most 65535")
        return cls(
            demo=demo,
            email=email,
            password=password,
            origin=origin,
            secure_cookie=secure,
            session_ttl=env_positive_int("AUTH_SESSION_TTL_SECONDS", 1800),
            rate_limit_max=env_positive_int("AUTH_RATE_LIMIT_MAX", 5),
            rate_limit_window=env_positive_int("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60),
        )


@dataclass(frozen=True)
class Session:
    csrf: str
    expires_at: float


@dataclass
class FailureWindow:
    count: int
    expires_at: float


class AuthError(Exception):
    def __init__(self, status: int, code: str, headers: dict[str, str] | None = None):
        self.status = status
        self.code = code
        self.headers = headers


class AuthState:
    def __init__(self, settings: Settings, clock: Callable[[], float]):
        self.clock = clock
        self.hasher = PasswordHasher()
        self.password_hash = self.hasher.hash(settings.password)
        self.settings = replace(settings, password="")
        self.sessions: dict[str, Session] = {}
        self.failures: dict[str, FailureWindow] = {}
        self.lock = threading.RLock()

    def _prune(self, now: float) -> None:
        self.sessions = {
            token: session for token, session in self.sessions.items() if session.expires_at > now
        }
        self.failures = {
            peer: window for peer, window in self.failures.items() if window.expires_at > now
        }

    def authenticate(
        self, peer: str, email: str, password: str, old_token: str
    ) -> tuple[str, Session]:
        # 해싱을 직렬화해 병렬 로그인 메모리 폭증과 실패 횟수 경합 우회를 막는다.
        with self.lock:
            now = self.clock()
            self._prune(now)
            failure = self.failures.get(peer)
            if failure is not None and failure.count >= self.settings.rate_limit_max:
                retry_after = max(1, math.ceil(failure.expires_at - now))
                raise AuthError(429, "RATE_LIMITED", {"Retry-After": str(retry_after)})
            try:
                password_matches = self.hasher.verify(self.password_hash, password)
            except VerifyMismatchError:
                password_matches = False
            email_matches = hmac.compare_digest(email.encode(), self.settings.email.encode())
            if not password_matches or not email_matches:
                if failure is None:
                    self.failures[peer] = FailureWindow(1, now + self.settings.rate_limit_window)
                else:
                    failure.count += 1
                raise AuthError(401, "INVALID_CREDENTIALS")
            self.failures.pop(peer, None)
            self.sessions.pop(old_token, None)
            token = secrets.token_urlsafe(32)
            session = Session(secrets.token_urlsafe(32), self.clock() + self.settings.session_ttl)
            self.sessions[token] = session
            return token, session

    def get_session(self, token: str) -> Session | None:
        with self.lock:
            self._prune(self.clock())
            return self.sessions.get(token)

    def logout(self, token: str, csrf: str) -> None:
        with self.lock:
            self._prune(self.clock())
            session = self.sessions.get(token)
            if session is not None:
                if not hmac.compare_digest(csrf.encode("utf-8"), session.csrf.encode("utf-8")):
                    raise AuthError(403, "CSRF_INVALID")
                del self.sessions[token]

    def payload(self, session: Session) -> dict:
        return {
            "user": {"id": "demo-user", "email": self.settings.email},
            "csrfToken": session.csrf,
        }


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


def create_app(
    *, settings: Settings | None = None, clock: Callable[[], float] = time.monotonic
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.auth = AuthState(settings or Settings.from_env(), clock)
        yield
        application.state.auth.sessions.clear()
        application.state.auth.failures.clear()

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
    def healthz():
        return {"status": "ok", "profile": "browser-session-v1", "implementation": "python-fastapi"}

    @application.post("/auth/login")
    async def login(request: Request):
        state: AuthState = request.app.state.auth
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
        state: AuthState = request.app.state.auth
        session = state.get_session(request.cookies.get(COOKIE_NAME, ""))
        if session is None:
            raise AuthError(401, "UNAUTHENTICATED")
        return state.payload(session)

    @application.post("/auth/logout")
    def logout(request: Request):
        state: AuthState = request.app.state.auth
        require_origin(request, state.settings)
        state.logout(request.cookies.get(COOKIE_NAME, ""), request.headers.get("x-csrf-token", ""))
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


app = create_app()
