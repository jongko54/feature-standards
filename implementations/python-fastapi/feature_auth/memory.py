"""The original process-local v1 adapter."""

from __future__ import annotations

import hmac
import math
import secrets
import threading
from collections.abc import Callable
from dataclasses import replace

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .core import AuthError, FailureWindow, Session, Settings


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

    def health(self) -> None:
        pass

    def close(self) -> None:
        self.sessions.clear()
        self.failures.clear()

    def payload(self, session: Session) -> dict:
        return {
            "user": session.user or {"id": "demo-user", "email": self.settings.email},
            "csrfToken": session.csrf,
        }
