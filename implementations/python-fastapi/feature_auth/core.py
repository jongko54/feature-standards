"""Shared configuration, storage protocol and authentication service."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field, replace
from typing import Protocol
from urllib.parse import urlsplit

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
    store: str = "memory"
    database_url: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        store = os.environ.get("AUTH_STORE", "memory")
        if store not in ("memory", "postgres"):
            raise ValueError("AUTH_STORE must be memory or postgres")
        database_url = os.environ.get("AUTH_DATABASE_URL", "") if store == "postgres" else ""
        if store == "postgres" and not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("AUTH_DATABASE_URL must be a PostgreSQL URI")
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
        email, password = "", ""
        if store == "memory":
            email = DEMO_EMAIL if demo else normalize_email(os.environ.get("AUTH_USER_EMAIL", ""))
            password = DEMO_PASSWORD if demo else os.environ.get("AUTH_USER_PASSWORD", "")
        try:
            valid_credentials = valid_email(email) and 1 <= len(password.encode("utf-8")) <= 1024
        except UnicodeError:
            valid_credentials = False
        if store == "memory" and not valid_credentials:
            raise ValueError("A valid AUTH_USER_EMAIL and AUTH_USER_PASSWORD are required")
        env_positive_int("AUTH_PORT", 8000)
        if int(os.environ.get("AUTH_PORT", "8000")) > 65535:
            raise ValueError("AUTH_PORT must be at most 65535")
        return cls(
            store=store,
            database_url=database_url,
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
    user: dict[str, str] | None = None


@dataclass
class FailureWindow:
    count: int
    expires_at: float


class AuthError(Exception):
    def __init__(self, status: int, code: str, headers: dict[str, str] | None = None):
        self.status = status
        self.code = code
        self.headers = headers


class AuthStore(Protocol):
    """Atomic authentication operations; HTTP adapters never handle SQL."""

    def authenticate(
        self, peer: str, email: str, password: str, old_token: str
    ) -> tuple[str, Session]: ...
    def get_session(self, token: str) -> Session | None: ...
    def logout(self, token: str, csrf: str) -> None: ...
    def health(self) -> None: ...
    def close(self) -> None: ...


class AuthService:
    def __init__(self, settings: Settings, store: AuthStore):
        self.settings = replace(settings, password="", database_url="")
        self.store = store
        self.profile = (
            "browser-session-v2" if settings.store == "postgres" else "browser-session-v1"
        )

    def authenticate(self, peer: str, email: str, password: str, old_token: str):
        return self.store.authenticate(peer, email, password, old_token)

    def get_session(self, token: str):
        return self.store.get_session(token)

    def logout(self, token: str, csrf: str):
        return self.store.logout(token, csrf)

    def payload(self, session: Session) -> dict:
        return {
            "user": session.user or {"id": "demo-user", "email": self.settings.email},
            "csrfToken": session.csrf,
        }
