#!/usr/bin/env python3
"""Run an installed Python/React consumer against a task-owned PostgreSQL DB."""

from __future__ import annotations

import contextlib
import http.client
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from conformance import Client, free_port, require_free_port, stop
from pg_support import database

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/consumer-python-react"
ORIGIN = "http://127.0.0.1:5174"
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate, seed_demo


@contextlib.contextmanager
def process(command, env, base):
    with tempfile.TemporaryFile(mode="w+") as log:
        child = subprocess.Popen(
            command,
            cwd=EXAMPLE,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    break
                try:
                    if Client(base).request("GET", "/healthz", origin=False)[0] == 200:
                        yield
                        return
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            log.seek(0)
            raise RuntimeError(
                f"Consumer process failed to start:\n{log.read()[-3000:]}"
            )
        finally:
            stop(child)


def main():
    require_free_port(5174)
    with database() as url:
        with psycopg.connect(url) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
        migrate(url)
        seed_demo(url)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update(
            AUTH_STORE="postgres",
            AUTH_DATABASE_URL=url,
            AUTH_HOST="127.0.0.1",
            AUTH_PORT=str(port),
            AUTH_DEMO="true",
            AUTH_COOKIE_SECURE="false",
            AUTH_ALLOWED_ORIGIN=ORIGIN,
            AUTH_SESSION_TTL_SECONDS="1800",
            AUTH_RATE_LIMIT_MAX="3",
            AUTH_RATE_LIMIT_WINDOW_SECONDS="60",
            AUTH_API_TARGET=base,
            BASE_URL=ORIGIN,
        )
        with (
            process(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "uvicorn",
                    "app:app",
                    "--no-proxy-headers",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env,
                base,
            ),
            process(["npm", "run", "dev"], env, ORIGIN),
        ):
            subprocess.run(["npm", "run", "test:e2e"], cwd=EXAMPLE, env=env, check=True)
    print("Separate installed-package consumer: PASS (3 browser scenarios)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
