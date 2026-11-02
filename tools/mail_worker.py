"""Leased PostgreSQL outbox delivery. SMTP acceptance is distinct from inbox delivery."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import ipaddress
import os
import signal
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from smtp_transport import (
    ERROR_CODES,
    DeliveryError,
    DeliveryMessage,
    SMTPSettings,
    SMTPTransport,
)

ROUTING_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGSERVICE",
    "PGSERVICEFILE",
)


def _clean_routing(values: Mapping[str, str]) -> None:
    if any(values.get(name) for name in ROUTING_ENV):
        raise ValueError(
            "Use an explicit AUTH_DATABASE_URL without PostgreSQL routing environment"
        )


def _database_url(value: str, demo: bool) -> str:
    try:
        parts = urlsplit(value)
        options = parse_qsl(parts.query, keep_blank_values=True)
        names = [name for name, _ in options]
        if (
            parts.scheme not in ("postgres", "postgresql")
            or not parts.hostname
            or not parts.path.startswith("/")
            or len(parts.path) <= 1
            or parts.fragment
            or parts.netloc.endswith(":")
            or parts.port is not None
            and not 1 <= parts.port <= 65535
            or len(names) != len(set(names))
            or any(
                name in names
                for name in (
                    "host",
                    "hostaddr",
                    "port",
                    "dbname",
                    "service",
                    "servicefile",
                )
            )
        ):
            raise ValueError
        mode = dict(options).get("sslmode")
        host = parts.hostname
        if mode == "disable":
            if host == "localhost":
                host = "127.0.0.1"
            if not demo or not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        elif mode != "verify-full":
            raise ValueError
        # Rebuild literal loopback routes so localhost resolution cannot escape demo.
        credentials = ""
        if parts.username is not None:
            credentials = quote(unquote(parts.username), safe="")
            if parts.password is not None:
                credentials += ":" + quote(unquote(parts.password), safe="")
            credentials += "@"
        authority = f"[{host}]" if ":" in host else host
        if parts.port:
            authority += f":{parts.port}"
        normalized = urlunsplit(
            ("postgresql", credentials + authority, parts.path, urlencode(options), "")
        )
        conninfo_to_dict(normalized)
        return normalized
    except (ValueError, psycopg.Error, UnicodeError):
        raise ValueError(
            "Database delivery requires verified TLS, or an explicit loopback mail demo"
        ) from None


def _integer(values, name, default, minimum, maximum):
    raw = values.get(name, str(default))
    if not raw.isascii() or not raw.isdecimal() or not minimum <= int(raw) <= maximum:
        raise ValueError(f"{name} is outside its supported integer range")
    return int(raw)


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str = field(repr=False)
    demo: bool = False
    max_attempts: int = 5
    batch_size: int = 20
    poll_seconds: int = 5
    lease_seconds: int = 330

    def __post_init__(self):
        if (
            not 1 <= self.max_attempts <= 20
            or not 1 <= self.batch_size <= 100
            or not 1 <= self.poll_seconds <= 60
            or self.lease_seconds < 300
        ):
            raise ValueError("Invalid mail worker settings")
        object.__setattr__(
            self, "database_url", _database_url(self.database_url, self.demo)
        )

    @classmethod
    def from_env(
        cls, smtp_timeout_seconds=10, mapping: Mapping[str, str] | None = None
    ):
        values = os.environ if mapping is None else mapping
        _clean_routing(values)
        raw_demo = values.get("AUTH_MAIL_DEMO", "false")
        if raw_demo not in ("true", "false") or not 1 <= smtp_timeout_seconds <= 30:
            raise ValueError("Invalid mail worker demo or timeout settings")
        minimum_lease = max(300, smtp_timeout_seconds * 30 + 30)
        return cls(
            values.get("AUTH_DATABASE_URL", ""),
            raw_demo == "true",
            _integer(values, "AUTH_MAIL_MAX_ATTEMPTS", 5, 1, 20),
            _integer(values, "AUTH_MAIL_BATCH_SIZE", 20, 1, 100),
            _integer(values, "AUTH_MAIL_POLL_SECONDS", 5, 1, 60),
            _integer(
                values, "AUTH_MAIL_LEASE_SECONDS", minimum_lease, minimum_lease, 86400
            ),
        )


class WorkerError(Exception):
    def __init__(self):
        super().__init__("Mail delivery storage operation failed")


@dataclass(frozen=True)
class Claim:
    outbox_id: int
    delivery_id: str
    claim_id: str
    attempts: int
    recipient: str = field(repr=False)
    kind: str
    token: str = field(repr=False)
    expires_at: datetime


@dataclass
class DeliveryStats:
    processed: int = 0
    accepted: int = 0
    delivered: int = 0
    retried: int = 0
    failed: int = 0
    cancelled: int = 0
    fenced: int = 0


class MailWorker:
    def __init__(
        self, settings: WorkerSettings, sender, connect: Callable | None = None
    ):
        self.settings = settings
        self.sender = sender
        self._connect = connect or psycopg.connect
        self.last_cancelled = 0
        self.last_failed = 0
        self._last_failure_state = None
        self._last_validation_cancelled = False
        self.ready()

    @contextlib.contextmanager
    def _connection(self):
        try:
            _clean_routing(os.environ)
            with self._connect(
                self.settings.database_url,
                connect_timeout=3,
                row_factory=dict_row,
                options="-c statement_timeout=10000 -c lock_timeout=5000",
            ) as connection:
                yield connection
        except psycopg.Error:
            raise WorkerError from None

    def ready(self):
        with self._connection() as conn:
            base = conn.execute(
                "SELECT version FROM feature_auth.schema_version"
            ).fetchall()
            addon = conn.execute(
                "SELECT version FROM feature_auth.mail_delivery_schema_version"
            ).fetchall()
            if base != [{"version": 2}] or addon != [{"version": 1}]:
                raise WorkerError

    def _locked(self, conn, outbox_id):
        parent = conn.execute(
            "SELECT * FROM feature_auth.mail_outbox WHERE id=%s FOR UPDATE",
            (outbox_id,),
        ).fetchone()
        if parent is None:
            return None, None
        delivery = conn.execute(
            "SELECT *,clock_timestamp() AS instant FROM feature_auth.mail_delivery WHERE outbox_id=%s FOR UPDATE",
            (outbox_id,),
        ).fetchone()
        return parent, delivery

    @staticmethod
    def _fenced(parent, delivery, claim):
        return bool(
            parent
            and delivery
            and delivery["state"] == "leased"
            and str(delivery["delivery_id"]) == claim.delivery_id
            and str(delivery["claim_id"]) == claim.claim_id
            and delivery["lease_until"] > delivery["instant"]
            and parent["token"] == claim.token
        )

    @staticmethod
    def _invalid(conn, parent):
        if parent["token"] is None or parent["delivered_at"] is not None:
            return "SUPERSEDED"
        current = conn.execute(
            "SELECT u.admin_enabled,u.email,u.email_verified_at,t.token_hash,t.expires_at,clock_timestamp() AS instant "
            "FROM feature_auth.users u LEFT JOIN feature_auth.account_tokens t "
            "ON t.user_id=u.id AND t.kind=%s WHERE u.id=%s",
            (parent["kind"], parent["user_id"]),
        ).fetchone()
        if current is None or current["email"] != parent["recipient"]:
            return "SUPERSEDED"
        if (
            parent["expires_at"] <= current["instant"]
            or current["expires_at"] is not None
            and current["expires_at"] <= current["instant"]
        ):
            return "EXPIRED"
        if not current["admin_enabled"]:
            return "DISABLED"
        if (
            parent["kind"] == "verify"
            and current["email_verified_at"] is not None
            or parent["kind"] == "reset"
            and current["email_verified_at"] is None
        ):
            return "SUPERSEDED"
        if (
            current["token_hash"] is None
            or bytes(current["token_hash"])
            != hashlib.sha256(parent["token"].encode()).digest()
        ):
            return "SUPERSEDED"
        return None

    @staticmethod
    def _terminal(conn, parent, state, code):
        conn.execute(
            "UPDATE feature_auth.mail_delivery SET state=%s,claim_id=NULL,lease_until=NULL,last_error_code=%s WHERE outbox_id=%s",
            (state, code, parent["id"]),
        )
        conn.execute(
            "UPDATE feature_auth.mail_outbox SET token=NULL WHERE id=%s",
            (parent["id"],),
        )

    def claim(self, scan_limit=None):
        self.last_cancelled = 0
        self.last_failed = 0
        for _ in range(scan_limit or self.settings.batch_size):
            result = None
            with self._connection() as conn:
                candidate = conn.execute(
                    "SELECT o.id FROM feature_auth.mail_outbox o JOIN feature_auth.mail_delivery d ON d.outbox_id=o.id "
                    "WHERE (d.state IN ('pending','retry') AND d.next_attempt_at<=clock_timestamp()) "
                    "OR (d.state='leased' AND d.lease_until<=clock_timestamp()) "
                    "ORDER BY d.next_attempt_at,o.id FOR UPDATE OF o SKIP LOCKED LIMIT 1"
                ).fetchone()
                if candidate is None:
                    return None
                parent, delivery = self._locked(conn, candidate["id"])
                if delivery is None:
                    continue
                due = (
                    delivery["state"] in ("pending", "retry")
                    and delivery["next_attempt_at"] <= delivery["instant"]
                )
                expired = (
                    delivery["state"] == "leased"
                    and delivery["lease_until"] <= delivery["instant"]
                )
                if not due and not expired:
                    continue
                invalid = self._invalid(conn, parent)
                if invalid:
                    self._terminal(conn, parent, "cancelled", invalid)
                    self.last_cancelled += 1
                elif delivery["attempts"] >= self.settings.max_attempts:
                    self._terminal(conn, parent, "failed", "ATTEMPTS_EXHAUSTED")
                    self.last_failed += 1
                else:
                    nonce = uuid4()
                    conn.execute(
                        "UPDATE feature_auth.mail_delivery SET state='leased',attempts=attempts+1,claim_id=%s, "
                        "lease_until=clock_timestamp()+%s*interval '1 second',last_error_code=NULL WHERE outbox_id=%s",
                        (nonce, self.settings.lease_seconds, parent["id"]),
                    )
                    result = Claim(
                        parent["id"],
                        str(delivery["delivery_id"]),
                        str(nonce),
                        delivery["attempts"] + 1,
                        parent["recipient"],
                        parent["kind"],
                        parent["token"],
                        parent["expires_at"],
                    )
            # A returned claim is visible only after this connection's COMMIT succeeds.
            if result is not None:
                return result
        return None

    def validate(self, claim):
        result = None
        cancelled = False
        with self._connection() as conn:
            parent, delivery = self._locked(conn, claim.outbox_id)
            if self._fenced(parent, delivery, claim):
                invalid = self._invalid(conn, parent)
                if invalid:
                    self._terminal(conn, parent, "cancelled", invalid)
                    cancelled = True
                else:
                    result = DeliveryMessage(
                        claim.delivery_id,
                        claim.recipient,
                        claim.kind,
                        claim.token,
                        claim.expires_at,
                    )
        self._last_validation_cancelled = cancelled
        return result

    def acknowledge(self, claim):
        acknowledged = False
        with self._connection() as conn:
            parent, delivery = self._locked(conn, claim.outbox_id)
            if self._fenced(parent, delivery, claim):
                conn.execute(
                    "UPDATE feature_auth.mail_outbox SET token=NULL,delivered_at=clock_timestamp() WHERE id=%s",
                    (claim.outbox_id,),
                )
                conn.execute(
                    "UPDATE feature_auth.mail_delivery SET state='delivered',claim_id=NULL,lease_until=NULL,last_error_code=NULL WHERE outbox_id=%s",
                    (claim.outbox_id,),
                )
                acknowledged = True
        return acknowledged

    def fail(self, claim, code, retryable):
        if code not in ERROR_CODES and code != "INTERNAL":
            code = "INTERNAL"
        changed = False
        state = None
        with self._connection() as conn:
            parent, delivery = self._locked(conn, claim.outbox_id)
            if self._fenced(parent, delivery, claim):
                invalid = self._invalid(conn, parent)
                if invalid:
                    self._terminal(conn, parent, "cancelled", invalid)
                    state = "cancelled"
                elif (
                    not retryable or delivery["attempts"] >= self.settings.max_attempts
                ):
                    self._terminal(conn, parent, "failed", code)
                    state = "failed"
                else:
                    delay = min(3600, 30 * 2 ** (delivery["attempts"] - 1))
                    conn.execute(
                        "UPDATE feature_auth.mail_delivery SET state='retry',claim_id=NULL,lease_until=NULL, "
                        "next_attempt_at=clock_timestamp()+%s*interval '1 second',last_error_code=%s WHERE outbox_id=%s",
                        (delay, code, claim.outbox_id),
                    )
                    state = "retry"
                changed = True
        self._last_failure_state = state
        return changed

    def _record_failure(self, stats, changed):
        if not changed:
            stats.fenced += 1
        elif self._last_failure_state == "retry":
            stats.retried += 1
        elif self._last_failure_state == "failed":
            stats.failed += 1
        else:
            stats.cancelled += 1

    def run_once(self, stop_event=None):
        stats = DeliveryStats()
        while stats.processed < self.settings.batch_size and not (
            stop_event and stop_event.is_set()
        ):
            claim = self.claim(self.settings.batch_size - stats.processed)
            stats.cancelled += self.last_cancelled
            stats.failed += self.last_failed
            stats.processed += self.last_cancelled + self.last_failed
            if claim is None:
                break
            stats.processed += 1
            message = self.validate(claim)
            if message is None:
                if self._last_validation_cancelled:
                    stats.cancelled += 1
                else:
                    stats.fenced += 1
                continue
            try:
                self.sender.send(message)
            except DeliveryError as error:
                changed = self.fail(claim, error.code, error.retryable)
                self._record_failure(stats, changed)
            except Exception:  # noqa: BLE001 -- untrusted transport boundary; never retain diagnostics.
                self._record_failure(stats, self.fail(claim, "INTERNAL", True))
            else:
                stats.accepted += 1
                if self.acknowledge(claim):
                    stats.delivered += 1
                else:
                    stats.fenced += 1
        return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Process one bounded batch and exit"
    )
    args = parser.parse_args()
    stop = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stop.set())
    try:
        smtp = SMTPSettings.from_env()
        settings = WorkerSettings.from_env(smtp.timeout_seconds)
        worker = MailWorker(settings, SMTPTransport(smtp))
    except (ValueError, WorkerError, OSError):
        print(
            "Mail worker configuration or storage is unavailable; private details are not displayed."
        )
        return 1
    while not stop.is_set():
        try:
            stats = worker.run_once(stop)
            print(
                f"Mail batch: accepted={stats.accepted} acknowledged={stats.delivered} retry={stats.retried} failed={stats.failed} cancelled={stats.cancelled} fenced={stats.fenced}",
                flush=True,
            )
        except WorkerError:
            print(
                "Mail worker storage failed; delivery acknowledgement may be uncertain.",
                flush=True,
            )
            if args.once:
                return 1
        if args.once:
            break
        stop.wait(settings.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
