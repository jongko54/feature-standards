#!/usr/bin/env python3
"""Exercise the built preview against task-owned memory auth and real Chromium."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import tempfile
import time

from conformance import EMAIL, PASSWORD, ROOT, Client, require_free_port, server, stop

ORIGIN = "http://127.0.0.1:4173"


def main() -> None:
    require_free_port(4173)
    fixture = {
        "AUTH_ALLOWED_ORIGIN": ORIGIN,
        "AUTH_USER_EMAIL": EMAIL,
        "AUTH_USER_PASSWORD": PASSWORD,
        "AUTH_RATE_LIMIT_MAX": "20",
    }
    with server("python", ttl=1800, rate_window=60, extra_env=fixture) as backend:
        environment = {
            **os.environ,
            "AUTH_API_TARGET": backend,
            "BASE_URL": ORIGIN,
            "VITE_AUTH_ACCOUNT_LIFECYCLE": "false",
        }
        with tempfile.TemporaryFile(mode="w+") as log:
            child = subprocess.Popen(
                ["npm", "run", "preview"],
                cwd=ROOT / "clients/react",
                env=environment,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError("Preview stopped before readiness")
                    try:
                        ready = Client(ORIGIN).request("GET", "/healthz", origin=False)
                        if ready[0] == 200:
                            break
                    except (OSError, http.client.HTTPException):
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Preview did not become ready")
                subprocess.run(
                    ["npm", "run", "test:e2e"],
                    cwd=ROOT / "clients/react",
                    env=environment,
                    check=True,
                )
            finally:
                stop(child)
    print(json.dumps({"mode": "preview", "port": 4173, "backend": "python", "actualBrowser": True, "passed": True}))


if __name__ == "__main__":
    main()
