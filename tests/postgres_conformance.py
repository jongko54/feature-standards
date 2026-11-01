#!/usr/bin/env python3
"""Shared PostgreSQL tests across language, process, restart and consumer boundaries."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

import psycopg
from conformance import (
    BACKENDS,
    PASSWORD,
    BackendBuilds,
    Client,
    run_browser,
    run_contract,
    run_secure_cookie_check,
    server,
)
from pg_support import DatabaseGate, assert_test_database, database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate, seed_demo


class SharedPostgresContract(unittest.TestCase):
    url = ""
    bases: ClassVar[dict[str, str]] = {}
    gate = None

    def setUp(self):
        self.gate.enabled.set()
        with psycopg.connect(self.url) as conn:
            conn.execute("TRUNCATE feature_auth.sessions,feature_auth.login_attempts")
            conn.execute("UPDATE feature_auth.users SET enabled=true")

    def query(self, statement, params=()):
        with psycopg.connect(self.url) as conn:
            return conn.execute(statement, params).fetchall()

    def test_01_cross_language_login_lookup_logout(self):
        client = Client(self.bases["python"])
        response = client.login()
        self.assertEqual(response[0], 200)
        payload = json.loads(response[2])
        for backend, base in self.bases.items():
            with self.subTest(reader=backend):
                reader = Client(base)
                reader.cookie = client.cookie
                result = reader.request("GET", "/auth/me")
                self.assertEqual(result[0], 200)
                self.assertEqual(json.loads(result[2]), payload)
        logout = Client(self.bases["java"])
        logout.cookie = client.cookie
        self.assertEqual(
            logout.request(
                "POST", "/auth/logout", headers={"X-CSRF-Token": payload["csrfToken"]}
            )[0],
            204,
        )
        for base in self.bases.values():
            reader = Client(base)
            reader.cookie = client.cookie
            self.assertEqual(reader.request("GET", "/auth/me")[0], 401)

    def test_02_all_issuers_use_shared_users_and_hashed_tokens(self):
        for backend, base in self.bases.items():
            with self.subTest(issuer=backend):
                client = Client(base)
                response = client.login(
                    email="other@example.com", password="other-correct-horse-password"
                )
                self.assertEqual(response[0], 200)
                self.assertEqual(
                    json.loads(response[2])["user"],
                    {"id": "other-user", "email": "other@example.com"},
                )
                token = client.cookie.split("=", 1)[1]
                digest = hashlib.sha256(token.encode()).digest()
                self.assertEqual(
                    self.query(
                        "SELECT user_id FROM feature_auth.sessions WHERE token_hash=%s",
                        (digest,),
                    ),
                    [("other-user",)],
                )
                reader = Client(self.bases["go"])
                reader.cookie = client.cookie
                self.assertEqual(
                    json.loads(reader.request("GET", "/auth/me")[2])["user"]["id"],
                    "other-user",
                )
        self.assertEqual(self.query("SELECT count(*) FROM feature_auth.users"), [(2,)])
        self.query(
            "INSERT INTO feature_auth.users(id,email,password_hash) "
            "SELECT 'unicode-user','한@example.com',password_hash FROM feature_auth.users "
            "WHERE id='demo-user' RETURNING id"
        )
        try:
            for backend, base in self.bases.items():
                with self.subTest(unicode_issuer=backend):
                    response = Client(base).login(email="  한@EXAMPLE.COM  ")
                    self.assertEqual(response[0], 200)
                    self.assertEqual(
                        json.loads(response[2])["user"],
                        {"id": "unicode-user", "email": "한@example.com"},
                    )
        finally:
            self.query(
                "DELETE FROM feature_auth.users WHERE id='unicode-user' RETURNING id"
            )

    def test_03_cross_language_rotation_and_csrf(self):
        first = Client(self.bases["rust"])
        payload = json.loads(first.login()[2])
        rotator = Client(self.bases["java"])
        rotator.cookie = first.cookie
        new = rotator.login()
        self.assertEqual(new[0], 200)
        self.assertNotEqual(rotator.cookie, first.cookie)
        self.assertEqual(first.request("GET", "/auth/me")[0], 401)
        reader = Client(self.bases["python"])
        reader.cookie = rotator.cookie
        self.assertEqual(
            reader.request(
                "POST", "/auth/logout", headers={"X-CSRF-Token": payload["csrfToken"]}
            )[0],
            403,
        )
        self.assertEqual(reader.request("GET", "/auth/me")[0], 200)

    def test_04_failure_limit_is_shared_and_resets(self):
        for backend in ("python", "go", "java"):
            self.assertEqual(
                Client(self.bases[backend]).login(password="incorrect")[0], 401
            )
        blocked = Client(self.bases["rust"]).login()
        self.assertEqual(blocked[0], 429)
        self.assertGreater(int(blocked[1]["retry-after"]), 0)
        self.query(
            "UPDATE feature_auth.login_attempts SET expires_at=clock_timestamp()-interval '1 second' RETURNING peer"
        )
        self.assertEqual(Client(self.bases["rust"]).login()[0], 200)
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.login_attempts"), [(0,)]
        )

    def test_05_concurrent_failures_are_atomic(self):
        def attempt(base):
            return Client(base).login(password="incorrect")[0]

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(attempt, self.bases.values()))
        self.assertEqual(sorted(statuses), [401, 401, 401, 429])
        self.assertEqual(
            self.query("SELECT failures FROM feature_auth.login_attempts"), [(3,)]
        )

    def test_06_disabled_users_and_expired_sessions(self):
        client = Client(self.bases["python"])
        logged_in = client.login()
        self.assertEqual(logged_in[0], 200)
        csrf = json.loads(logged_in[2])["csrfToken"]
        self.query(
            "UPDATE feature_auth.users SET enabled=false WHERE id='demo-user' RETURNING id"
        )
        for base in self.bases.values():
            reader = Client(base)
            reader.cookie = client.cookie
            self.assertEqual(reader.request("GET", "/auth/me")[0], 401)
            self.assertEqual(reader.login()[0], 401)
            self.assertEqual(reader.request("POST", "/auth/logout")[0], 403)
            # Keep this account-state scenario separate from rate limiting.
            self.query("DELETE FROM feature_auth.login_attempts RETURNING peer")
        self.assertEqual(
            client.request("POST", "/auth/logout", headers={"X-CSRF-Token": csrf})[0],
            204,
        )
        self.query("UPDATE feature_auth.users SET enabled=true RETURNING id")
        self.assertEqual(client.login()[0], 200)
        self.query(
            "UPDATE feature_auth.sessions SET expires_at=created_at+interval '1 microsecond' RETURNING user_id"
        )
        self.assertEqual(client.request("GET", "/auth/me")[0], 401)

    def test_07_database_disconnect_fails_closed_and_recovers(self):
        cookies = {}
        for backend, base in self.bases.items():
            client = Client(base)
            result = client.login()
            self.assertEqual(result[0], 200)
            cookies[backend] = (client.cookie, json.loads(result[2])["csrfToken"])
        self.gate.disable()
        try:
            for backend, base in self.bases.items():
                client = Client(base)
                client.cookie, csrf = cookies[backend]
                for method, path, body, headers in [
                    ("GET", "/healthz", None, {}),
                    ("GET", "/auth/me", None, {}),
                    (
                        "POST",
                        "/auth/login",
                        {"email": "demo@example.com", "password": PASSWORD},
                        {},
                    ),
                    ("POST", "/auth/logout", None, {"X-CSRF-Token": csrf}),
                ]:
                    with self.subTest(backend=backend, path=path):
                        response = client.request(method, path, body, headers=headers)
                        self.assertEqual(response[0], 503)
                        self.assertEqual(
                            json.loads(response[2])["error"]["code"],
                            "STORAGE_UNAVAILABLE",
                        )
                        self.assertNotIn("set-cookie", response[1])
                        self.assertNotIn(self.url.encode(), response[2])
                        self.assertEqual(response[1]["cache-control"], "no-store")
                        self.assertEqual(
                            response[1]["x-content-type-options"], "nosniff"
                        )
        finally:
            self.gate.enabled.set()
        for backend, base in self.bases.items():
            client = Client(base)
            client.cookie = cookies[backend][0]
            deadline = time.monotonic() + 8
            while True:
                response = client.request("GET", "/auth/me")
                if response[0] == 200 or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
            self.assertEqual(response[0], 200)

    def test_08_corrupt_hash_is_storage_failure_without_lockout(self):
        original = self.query(
            "SELECT password_hash FROM feature_auth.users WHERE id='demo-user'"
        )[0][0]
        try:
            self.query(
                "UPDATE feature_auth.users SET password_hash='invalid-stored-hash' WHERE id='demo-user' RETURNING id"
            )
            for backend, base in self.bases.items():
                with self.subTest(backend=backend):
                    response = Client(base).login()
                    self.assertEqual(response[0], 503)
                    self.assertEqual(
                        json.loads(response[2])["error"]["code"], "STORAGE_UNAVAILABLE"
                    )
            self.assertEqual(
                self.query("SELECT count(*) FROM feature_auth.login_attempts"), [(0,)]
            )
        finally:
            self.query(
                "UPDATE feature_auth.users SET password_hash=%s WHERE id='demo-user' RETURNING id",
                (original,),
            )


def restart_checks(url, env, builds):
    for backend in BACKENDS:
        with server(
            backend, ttl=1800, rate_window=60, builds=builds, extra_env=env
        ) as base:
            client = Client(base)
            login = client.login()
            assert login[0] == 200
            cookie, payload = client.cookie, json.loads(login[2])
            with server(
                backend, ttl=1800, rate_window=60, builds=builds, extra_env=env
            ) as peer_base:
                peer = Client(peer_base)
                peer.cookie = cookie
                assert json.loads(peer.request("GET", "/auth/me")[2]) == payload
                assert (
                    peer.request(
                        "POST",
                        "/auth/logout",
                        headers={"X-CSRF-Token": payload["csrfToken"]},
                    )[0]
                    == 204
                )
                assert client.request("GET", "/auth/me")[0] == 401
            login = client.login()
            assert login[0] == 200
            cookie, payload = client.cookie, json.loads(login[2])
            print(f"[{backend}] two-instance session/revocation: PASS", flush=True)
        with server(
            backend, ttl=1800, rate_window=60, builds=builds, extra_env=env
        ) as base:
            restarted = Client(base)
            restarted.cookie = cookie
            response = restarted.request("GET", "/auth/me")
            assert response[0] == 200 and json.loads(response[2]) == payload
            assert (
                json.loads(restarted.request("GET", "/healthz")[2])["profile"]
                == "browser-session-v2"
            )
        print(f"[{backend}] restart persistence: PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    passed = True
    with (
        database() as url,
        tempfile.TemporaryDirectory(prefix="feature-standards-v2-build-") as output,
    ):
        assert_test_database(url)
        with psycopg.connect(url) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
        migrate(url)
        seed_demo(url)
        # Idempotent seed must preserve passwords and accounts.
        with psycopg.connect(url) as conn:
            before = conn.execute(
                "SELECT id,password_hash FROM feature_auth.users ORDER BY id"
            ).fetchall()
        migrate(url)
        seed_demo(url)
        with psycopg.connect(url) as conn:
            assert (
                conn.execute(
                    "SELECT id,password_hash FROM feature_auth.users ORDER BY id"
                ).fetchall()
                == before
            )
        builds = BackendBuilds(output)
        with DatabaseGate(url) as gate:
            env = {"AUTH_STORE": "postgres", "AUTH_DATABASE_URL": gate.url}
            for backend in BACKENDS:
                print(f"\n=== {backend}: browser-session-v2 ===", flush=True)
                with server(backend, builds=builds, extra_env=env) as base:
                    passed = run_contract(base) and passed
                run_secure_cookie_check(backend, builds=builds, extra_env=env)
                if args.browser:
                    run_browser(backend, builds=builds, extra_env=env)
            with contextlib.ExitStack() as stack:
                SharedPostgresContract.url = url
                SharedPostgresContract.gate = gate
                SharedPostgresContract.bases = {
                    backend: stack.enter_context(
                        server(
                            backend,
                            ttl=1800,
                            rate_window=60,
                            builds=builds,
                            extra_env=env,
                        )
                    )
                    for backend in BACKENDS
                }
                result = unittest.TextTestRunner(verbosity=2).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(
                        SharedPostgresContract
                    )
                )
                passed = result.wasSuccessful() and passed
            restart_checks(url, env, builds)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
