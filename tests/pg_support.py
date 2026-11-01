"""Task-owned database and TCP fault fixture. Never reset an unapproved database."""

from __future__ import annotations

import contextlib
import os
import re
import selectors
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

import psycopg
from conformance import free_port


def require_clean_pg_environment() -> None:
    if any(key.startswith("PG") and value for key, value in os.environ.items()):
        raise ValueError("Clear PostgreSQL environment for isolated database tests")


def assert_test_database(url: str) -> str:
    """Validate and return a canonical, explicitly routed test-only URI."""
    parts = urlsplit(url)
    name = unquote(parts.path[1:])
    if parts.scheme not in ("postgres", "postgresql") or not re.fullmatch(
        r"feature_standards_test[A-Za-z0-9_]*", name
    ):
        raise ValueError(
            "Destructive fixtures require a feature_standards_test database"
        )
    if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Database fixtures are restricted to loopback")
    if parts.fragment or not parts.port or not 0 < parts.port < 65536:
        raise ValueError("Test database URI needs an explicit loopback port")
    options = parse_qsl(parts.query, keep_blank_values=True)
    if options not in ([], [("sslmode", "disable")]):
        raise ValueError("Test database URI only permits sslmode=disable")
    # libpq environment routing is deliberately not inherited by destructive fixtures.
    require_clean_pg_environment()
    credentials = ""
    if parts.username is not None:
        credentials = quote(unquote(parts.username), safe="")
        if parts.password is not None:
            credentials += ":" + quote(unquote(parts.password), safe="")
        credentials += "@"
    host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
    return f"postgresql://{credentials}{host}:{parts.port}/{name}?sslmode=disable"


@contextlib.contextmanager
def database():
    # Check before initdb and the first administrative connection, not after yield.
    require_clean_pg_environment()
    configured = os.environ.get("FEATURE_STANDARDS_TEST_DATABASE_URL")
    if configured:
        yield assert_test_database(configured)
        return
    # Explicit override supports a portable server without installing an OS service.
    pg_bin = os.environ.get("FEATURE_STANDARDS_PG_BIN")
    initdb = str(Path(pg_bin) / "initdb") if pg_bin else shutil.which("initdb")
    pg_ctl = str(Path(pg_bin) / "pg_ctl") if pg_bin else shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        raise RuntimeError(
            "Provide FEATURE_STANDARDS_TEST_DATABASE_URL or PostgreSQL server binaries"
        )
    with tempfile.TemporaryDirectory(
        prefix="fs-pg-", dir="/private/tmp" if Path("/private/tmp").exists() else None
    ) as temp:
        base = Path(temp)
        port = free_port()
        subprocess.run(
            [
                initdb,
                "-D",
                str(base / "data"),
                "-A",
                "trust",
                "-U",
                "feature_test",
                "--encoding=UTF8",
                "--no-locale",
            ],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        control = [pg_ctl, "-D", str(base / "data")]
        subprocess.run(
            [
                *control,
                "-l",
                str(base / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {base}",
                "-w",
                "start",
            ],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        try:
            admin = (
                f"postgresql://feature_test@127.0.0.1:{port}/postgres?sslmode=disable"
            )
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute("CREATE DATABASE feature_standards_test")
            yield f"postgresql://feature_test@127.0.0.1:{port}/feature_standards_test?sslmode=disable"
        finally:
            subprocess.run(
                [*control, "-m", "fast", "-w", "stop"],
                stdout=subprocess.DEVNULL,
                check=True,
            )


class DatabaseGate:
    """A loopback TCP forwarder that can sever only this test's DB connections."""

    def __init__(self, url):
        parts = urlsplit(url)
        self.destination = (parts.hostname, parts.port or 5432)
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.2)
        credentials = (
            parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
        )
        self.url = urlunsplit(
            parts._replace(
                netloc=f"{credentials}127.0.0.1:{self.listener.getsockname()[1]}"
            )
        )
        self.enabled = threading.Event()
        self.enabled.set()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.connections = set()
        self.threads = []
        self.acceptor = threading.Thread(target=self._accept, daemon=True)
        self.acceptor.start()

    def _accept(self):
        while not self.stopping.is_set():
            try:
                incoming, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            thread = threading.Thread(
                target=self._forward, args=(incoming,), daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def _forward(self, incoming):
        outgoing = None
        try:
            if not self.enabled.is_set():
                return
            outgoing = socket.create_connection(self.destination, timeout=3)
            with self.lock:
                self.connections.update((incoming, outgoing))
            incoming.setblocking(False)
            outgoing.setblocking(False)
            with selectors.DefaultSelector() as selector:
                selector.register(incoming, selectors.EVENT_READ, outgoing)
                selector.register(outgoing, selectors.EVENT_READ, incoming)
                while self.enabled.is_set() and not self.stopping.is_set():
                    for key, _ in selector.select(0.2):
                        data = key.fileobj.recv(65536)
                        if not data:
                            return
                        # PostgreSQL fixture packets are small; finite writes avoid an idle stall.
                        target = key.data
                        target.setblocking(True)
                        target.settimeout(3)
                        target.sendall(data)
                        target.setblocking(False)
        except OSError:
            pass
        finally:
            with self.lock:
                self.connections.discard(incoming)
                if outgoing:
                    self.connections.discard(outgoing)
            incoming.close()
            if outgoing:
                outgoing.close()

    def disable(self):
        self.enabled.clear()
        with self.lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.stopping.set()
        self.disable()
        self.listener.close()
        self.acceptor.join(timeout=2)
        for thread in self.threads:
            thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
