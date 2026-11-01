"""PostgreSQL adapter. Transactions complete before values reach the HTTP layer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
from contextlib import contextmanager

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .core import AuthError, Session, Settings

PHC = re.compile(r"^\$argon2id\$v=19\$m=65536,t=3,p=4\$([A-Za-z0-9+/]{22})\$([A-Za-z0-9+/]{43})$")


def valid_phc(value: str) -> bool:
    match = PHC.fullmatch(value)
    if not match:
        return False
    try:
        salt, digest = (
            base64.b64decode(part + "=" * (-len(part) % 4), validate=True)
            for part in match.groups()
        )
        return (
            len(salt) == 16
            and len(digest) == 32
            and base64.b64encode(salt).decode().rstrip("=") == match[1]
            and base64.b64encode(digest).decode().rstrip("=") == match[2]
        )
    except ValueError:
        return False


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class PostgresStore:
    def __init__(self, settings: Settings):
        if not settings.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("AUTH_DATABASE_URL must be a PostgreSQL URI")
        self._url = settings.database_url
        self.ttl = settings.session_ttl
        self.limit = settings.rate_limit_max
        self.window = settings.rate_limit_window
        self.hasher = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4, salt_len=16, hash_len=32
        )
        self._dummy = self.hasher.hash(secrets.token_urlsafe(32))
        try:
            self.health()
        except AuthError:
            raise ValueError(
                "PostgreSQL authentication storage is unavailable or incompatible"
            ) from None

    @contextmanager
    def _connection(self):
        try:
            # Each operation owns its connection and transaction; no thread shares one.
            with psycopg.connect(
                self._url,
                connect_timeout=3,
                options="-c statement_timeout=10000 -c lock_timeout=8000",
            ) as conn:
                yield conn
        except psycopg.Error:
            raise AuthError(503, "STORAGE_UNAVAILABLE") from None

    def health(self) -> None:
        with self._connection() as conn:
            rows = conn.execute("SELECT version FROM feature_auth.schema_version").fetchall()
            if rows != [(1,)]:
                raise AuthError(503, "STORAGE_UNAVAILABLE")

    def close(self) -> None:
        pass

    def authenticate(self, peer: str, email: str, password: str, old_token: str):
        outcome = None
        result = None
        with self._connection() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(20261102, hashtext(host(CAST(%s AS inet))))", (peer,)
            )
            now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            conn.execute(
                "DELETE FROM feature_auth.login_attempts "
                "WHERE peer = CAST(%s AS inet) AND expires_at <= %s",
                (peer, now),
            )
            attempt = conn.execute(
                "SELECT failures, expires_at FROM feature_auth.login_attempts "
                "WHERE peer = CAST(%s AS inet)",
                (peer,),
            ).fetchone()
            if attempt and attempt[0] >= self.limit:
                retry = max(1, math.ceil((attempt[1] - now).total_seconds()))
                outcome = AuthError(429, "RATE_LIMITED", {"Retry-After": str(retry)})
            else:
                user = conn.execute(
                    "SELECT id, email, password_hash, enabled "
                    "FROM feature_auth.users WHERE email = %s",
                    (email,),
                ).fetchone()
                encoded = user[2] if user else self._dummy
                if not valid_phc(encoded):
                    raise AuthError(503, "STORAGE_UNAVAILABLE")
                try:
                    matches = self.hasher.verify(encoded, password)
                except VerifyMismatchError:
                    matches = False
                except (InvalidHashError, VerificationError):
                    raise AuthError(503, "STORAGE_UNAVAILABLE") from None
                if not matches or not user or not user[3]:
                    conn.execute(
                        """INSERT INTO feature_auth.login_attempts(peer, failures, expires_at)
                        VALUES (CAST(%s AS inet), 1, %s + %s * interval '1 second')
                        ON CONFLICT (peer) DO UPDATE
                        SET failures = feature_auth.login_attempts.failures + 1""",
                        (peer, now, self.window),
                    )
                    outcome = AuthError(401, "INVALID_CREDENTIALS")
                else:
                    conn.execute(
                        "DELETE FROM feature_auth.login_attempts WHERE peer = CAST(%s AS inet)",
                        (peer,),
                    )
                    conn.execute(
                        "DELETE FROM feature_auth.sessions WHERE token_hash = %s",
                        (token_hash(old_token),),
                    )
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    # Read DB time after hashing so TTL begins at session creation.
                    expires = conn.execute(
                        """INSERT INTO feature_auth.sessions
                        (token_hash,user_id,csrf_token,created_at,expires_at)
                        SELECT %s,%s,%s,t,t + %s * interval '1 second'
                        FROM (SELECT clock_timestamp() AS t) AS clock
                        RETURNING expires_at""",
                        (token_hash(token), user[0], csrf, self.ttl),
                    ).fetchone()[0]
                    result = (
                        token,
                        Session(csrf, expires.timestamp(), {"id": user[0], "email": user[1]}),
                    )
        # Raising inside the transaction would roll back the failed-attempt counter.
        if outcome:
            raise outcome
        return result

    def get_session(self, token: str) -> Session | None:
        with self._connection() as conn:
            row = conn.execute(
                """SELECT s.csrf_token,s.expires_at,u.id,u.email
                FROM feature_auth.sessions s JOIN feature_auth.users u ON u.id=s.user_id
                WHERE s.token_hash=%s AND s.expires_at > clock_timestamp() AND u.enabled""",
                (token_hash(token),),
            ).fetchone()
            if row:
                return Session(row[0], row[1].timestamp(), {"id": row[2], "email": row[3]})
        return None

    def logout(self, token: str, csrf: str) -> None:
        with self._connection() as conn:
            digest = token_hash(token)
            row = conn.execute(
                "SELECT csrf_token,expires_at FROM feature_auth.sessions "
                "WHERE token_hash=%s FOR UPDATE",
                (digest,),
            ).fetchone()
            now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            if (
                row
                and row[1] > now
                and not hmac.compare_digest(csrf.encode("utf-8"), row[0].encode("utf-8"))
            ):
                raise AuthError(403, "CSRF_INVALID")
            conn.execute("DELETE FROM feature_auth.sessions WHERE token_hash=%s", (digest,))
