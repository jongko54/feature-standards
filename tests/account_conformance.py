#!/usr/bin/env python3
"""Identical account lifecycle HTTP/browser tests and mixed-language race checks."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import secrets
import stat
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import psycopg
from conformance import (
    BACKENDS,
    PASSWORD,
    BackendBuilds,
    Client,
    run_browser,
    run_contract,
    server,
)
from pg_support import DatabaseGate, database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate_accounts, seed_demo
from mail_capture import capture

ROUTES = {
    "register": "/auth/register",
    "verify-request": "/auth/email-verification/request",
    "verify-confirm": "/auth/email-verification/confirm",
    "reset-request": "/auth/password-reset/request",
    "reset-confirm": "/auth/password-reset/confirm",
}
NEW_PASSWORD = "a-new-long-password-for-reset"


class AccountContract(unittest.TestCase):
    url = ""
    base = ""

    def query(self, statement, args=()):
        with psycopg.connect(self.url) as conn:
            cursor = conn.execute(statement, args)
            return cursor.fetchall() if cursor.description else []

    def setUp(self):
        self.query(
            "DELETE FROM feature_auth.users WHERE id NOT IN ('demo-user','other-user') RETURNING id"
        )
        self.query(
            "TRUNCATE feature_auth.sessions,feature_auth.login_attempts,feature_auth.account_attempts"
        )
        self.email = "new-한@example.com"
        self.client = Client(self.base)

    def call(self, action, body, client=None, **kwargs):
        return (client or self.client).request("POST", ROUTES[action], body, **kwargs)

    def expect(self, response, status, code=None):
        self.assertEqual(response[0], status)
        self.assertEqual(response[1].get("cache-control"), "no-store")
        self.assertEqual(response[1].get("x-content-type-options"), "nosniff")
        self.assertNotIn("set-cookie", response[1])
        if code:
            self.assertEqual(json.loads(response[2])["error"]["code"], code)

    def mail(self, kind, email=None):
        rows = self.query(
            "SELECT token FROM feature_auth.mail_outbox WHERE recipient=%s AND kind=%s AND token IS NOT NULL ORDER BY id DESC",
            (email or self.email, kind),
        )
        self.assertTrue(rows, "expected local outbox message")
        return rows[0][0]

    def register(self, client=None, email=None):
        self.expect(
            self.call(
                "register", {"email": email or self.email, "password": PASSWORD}, client
            ),
            202,
        )
        return self.mail("verify", email)

    def verified(self, client=None):
        token = self.register(client)
        self.expect(self.call("verify-confirm", {"token": token}, client), 204)
        return token

    def reset_token(self, client=None):
        self.expect(self.call("reset-request", {"email": self.email}, client), 202)
        return self.mail("reset")

    def test_01_register_verify_login(self):
        token = self.register()
        self.assertEqual(self.client.login(email=self.email)[0], 401)
        self.expect(self.call("verify-confirm", {"token": token}), 204)
        self.assertEqual(self.client.login(email="  NEW-한@EXAMPLE.COM ")[0], 200)
        self.assertEqual(
            self.query("SELECT token_hash FROM feature_auth.account_tokens"), []
        )

    def test_02_duplicate_and_generic_requests(self):
        token = self.register()
        before = self.query(
            "SELECT password_hash FROM feature_auth.users WHERE email=%s", (self.email,)
        )
        response = self.call(
            "register", {"email": self.email, "password": NEW_PASSWORD}
        )
        self.expect(response, 202)
        self.assertEqual(
            before,
            self.query(
                "SELECT password_hash FROM feature_auth.users WHERE email=%s",
                (self.email,),
            ),
        )
        for action in ("verify-request", "reset-request"):
            known = self.call(action, {"email": self.email})
            unknown = self.call(action, {"email": "missing@example.com"})
            self.expect(known, 202)
            self.expect(unknown, 202)
            self.assertEqual(known[2], unknown[2])
            self.assertEqual(known[2], response[2])
        self.assertEqual(self.mail("verify"), token)

    def test_03_strict_inputs_and_origin(self):
        bodies = {
            "register": {"email": self.email, "password": PASSWORD},
            "verify-request": {"email": self.email},
            "reset-request": {"email": self.email},
            "verify-confirm": {"token": "A" * 43},
            "reset-confirm": {"token": "A" * 43, "password": PASSWORD},
        }
        for action, body in bodies.items():
            with self.subTest(action=action):
                self.expect(self.call(action, body, origin=False), 403, "ORIGIN_DENIED")
                self.expect(
                    self.call(action, {**body, "extra": True}), 400, "INVALID_REQUEST"
                )
                duplicate = (
                    json.dumps(body)[:-1]
                    + ","
                    + json.dumps(next(iter(body)))
                    + ':"duplicate"}'
                )
                self.expect(
                    self.call(
                        action,
                        duplicate.encode(),
                        headers={"Content-Type": "application/json"},
                    ),
                    400,
                    "INVALID_REQUEST",
                )
                self.expect(self.call(action, b"{}"), 415, "UNSUPPORTED_MEDIA_TYPE")
                self.expect(
                    self.call(
                        action,
                        b"x" * 4097,
                        headers={"Content-Type": "application/json"},
                    ),
                    413,
                    "REQUEST_TOO_LARGE",
                )
        for email in (
            "no-at",
            "a\x00@example.com",
            "a b@example.com",
            "a\r\n@example.com",
            "a\x7f@example.com",
        ):
            self.expect(
                self.call("register", {"email": email, "password": PASSWORD}),
                400,
                "INVALID_REQUEST",
            )
        for password in ("short", "😀" * 14, "한" * 342):
            self.expect(
                self.call("register", {"email": self.email, "password": password}),
                400,
                "INVALID_REQUEST",
            )
        self.expect(
            self.call("register", {"email": self.email, "password": "😀" * 15}), 202
        )
        for token in ("short", "=" * 43):
            self.expect(
                self.call("verify-confirm", {"token": token}), 400, "INVALID_REQUEST"
            )

    def test_04_token_kind_expiry_and_replay(self):
        token = self.register()
        self.expect(
            self.call("reset-confirm", {"token": token, "password": NEW_PASSWORD}),
            400,
            "INVALID_TOKEN",
        )
        self.query(
            "UPDATE feature_auth.account_tokens SET expires_at=created_at+interval '1 microsecond' RETURNING user_id"
        )
        self.expect(self.call("verify-confirm", {"token": token}), 400, "INVALID_TOKEN")
        self.query(
            "UPDATE feature_auth.account_tokens SET expires_at=clock_timestamp()+interval '1 hour' RETURNING user_id"
        )
        self.expect(self.call("verify-confirm", {"token": token}), 204)
        self.expect(self.call("verify-confirm", {"token": token}), 400, "INVALID_TOKEN")

    def test_05_reset_revokes_all_sessions(self):
        self.verified()
        first = Client(self.base)
        second = Client(self.base)
        self.assertEqual(first.login(email=self.email)[0], 200)
        self.assertEqual(second.login(email=self.email)[0], 200)
        token = self.reset_token()
        self.expect(
            self.call("reset-confirm", {"token": token, "password": "short"}),
            400,
            "INVALID_REQUEST",
        )
        self.assertEqual(first.request("GET", "/auth/me")[0], 200)
        self.expect(
            self.call("reset-confirm", {"token": token, "password": NEW_PASSWORD}), 204
        )
        for reader in (first, second):
            self.assertEqual(reader.request("GET", "/auth/me")[0], 401)
        self.assertEqual(self.client.login(email=self.email)[0], 401)
        self.assertEqual(
            self.client.login(email=self.email, password=NEW_PASSWORD)[0], 200
        )
        self.expect(
            self.call("reset-confirm", {"token": token, "password": PASSWORD}),
            400,
            "INVALID_TOKEN",
        )

    def test_06_admin_disabled_state_is_preserved(self):
        token = self.register()
        self.query(
            "UPDATE feature_auth.users SET admin_enabled=false WHERE email=%s RETURNING id",
            (self.email,),
        )
        self.expect(self.call("verify-confirm", {"token": token}), 400, "INVALID_TOKEN")
        self.assertEqual(
            self.query(
                "SELECT enabled,email_verified_at FROM feature_auth.users WHERE email=%s",
                (self.email,),
            ),
            [(False, None)],
        )
        self.query(
            "UPDATE feature_auth.users SET admin_enabled=true WHERE email=%s RETURNING id",
            (self.email,),
        )
        self.expect(self.call("verify-confirm", {"token": token}), 204)
        reset = self.reset_token()
        self.query(
            "UPDATE feature_auth.users SET admin_enabled=false WHERE email=%s RETURNING id",
            (self.email,),
        )
        self.expect(
            self.call("reset-confirm", {"token": reset, "password": NEW_PASSWORD}),
            400,
            "INVALID_TOKEN",
        )
        self.assertEqual(
            self.query(
                "SELECT enabled FROM feature_auth.users WHERE email=%s", (self.email,)
            ),
            [(False,)],
        )

    def test_07_cooldown_and_reissue(self):
        old = self.register()
        self.expect(self.call("verify-request", {"email": self.email}), 202)
        self.assertEqual(self.mail("verify"), old)
        self.query(
            "UPDATE feature_auth.account_mail_limits SET sent_at=clock_timestamp()-interval '61 seconds' RETURNING user_id"
        )
        self.expect(self.call("verify-request", {"email": self.email}), 202)
        fresh = self.mail("verify")
        self.assertNotEqual(old, fresh)
        self.expect(self.call("verify-confirm", {"token": old}), 400, "INVALID_TOKEN")
        self.expect(self.call("verify-confirm", {"token": fresh}), 204)

    def test_08_peer_limit_ignores_forwarded_headers(self):
        for n in range(10):
            self.expect(
                self.call(
                    "reset-request",
                    {"email": "missing@example.com"},
                    headers={"X-Forwarded-For": f"198.51.100.{n}"},
                ),
                202,
            )
        response = self.call("reset-request", {"email": "missing@example.com"})
        self.expect(response, 429, "RATE_LIMITED")
        self.assertGreater(int(response[1]["retry-after"]), 0)

    def test_09_account_operations_do_not_authenticate(self):
        self.verified()
        self.assertEqual(self.client.request("GET", "/auth/me")[0], 401)
        token = self.reset_token()
        self.expect(
            self.call("reset-confirm", {"token": token, "password": NEW_PASSWORD}), 204
        )
        self.assertEqual(self.client.request("GET", "/auth/me")[0], 401)

    def test_10_commit_failure_rolls_back(self):
        with psycopg.connect(self.url) as conn:
            conn.execute(
                "CREATE OR REPLACE FUNCTION feature_auth.test_fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test-only deferred rejection'; END $$"
            )
            conn.execute(
                "CREATE CONSTRAINT TRIGGER test_fail_commit AFTER INSERT ON feature_auth.mail_outbox DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION feature_auth.test_fail_commit()"
            )
        try:
            self.expect(
                self.call("register", {"email": self.email, "password": PASSWORD}),
                503,
                "STORAGE_UNAVAILABLE",
            )
            self.assertEqual(
                self.query(
                    "SELECT count(*) FROM feature_auth.users WHERE email=%s",
                    (self.email,),
                ),
                [(0,)],
            )
        finally:
            with psycopg.connect(self.url) as conn:
                conn.execute(
                    "DROP TRIGGER test_fail_commit ON feature_auth.mail_outbox"
                )
                conn.execute("DROP FUNCTION feature_auth.test_fail_commit()")


class SharedAccounts(AccountContract):
    bases: ClassVar[dict[str, str]] = {}
    gate = None
    builds = None
    env: ClassVar[dict[str, str]] = {}

    def setUp(self):
        self.base = self.bases["python"]
        super().setUp()

    # Use a distinct loader below: these named mixed tests replace inherited HTTP cases.
    def mixed_01_cross_language_lifecycle(self):
        names = list(self.bases)
        for n, name in enumerate(names):
            self.email = f"cross-{n}@example.com"
            clients = [Client(self.bases[names[(n + i) % 4]]) for i in range(4)]
            token = self.register(clients[0])
            self.expect(self.call("verify-confirm", {"token": token}, clients[1]), 204)
            self.assertEqual(clients[2].login(email=self.email)[0], 200)
            cookie = clients[2].cookie
            token = self.reset_token(clients[3])
            self.expect(
                self.call(
                    "reset-confirm",
                    {"token": token, "password": NEW_PASSWORD},
                    clients[0],
                ),
                204,
            )
            for client in clients:
                client.cookie = cookie
                self.assertEqual(client.request("GET", "/auth/me")[0], 401)
            self.assertEqual(
                clients[1].login(email=self.email, password=NEW_PASSWORD)[0], 200
            )

    def mixed_02_concurrent_verification_single_winner(self):
        token = self.register()
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(
                pool.map(
                    lambda base: self.call(
                        "verify-confirm", {"token": token}, Client(base)
                    )[0],
                    self.bases.values(),
                )
            )
        self.assertEqual(sorted(statuses), [204, 400, 400, 400])

    def mixed_03_concurrent_reset_single_winner(self):
        self.verified()
        token = self.reset_token()
        passwords = [NEW_PASSWORD + str(i) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(
                    self.call,
                    "reset-confirm",
                    {"token": token, "password": password},
                    Client(base),
                )
                for base, password in zip(self.bases.values(), passwords, strict=True)
            ]
            statuses = [future.result()[0] for future in futures]
        self.assertEqual(sorted(statuses), [204, 400, 400, 400])
        self.assertEqual(
            self.client.login(
                email=self.email, password=passwords[statuses.index(204)]
            )[0],
            200,
        )

    def mixed_04_login_reset_lock_race(self):
        for name, base in self.bases.items():
            with self.subTest(backend=name):
                self.email = f"race-{name}@example.com"
                self.verified()
                token = self.reset_token()
                uid = self.query(
                    "SELECT id FROM feature_auth.users WHERE email=%s", (self.email,)
                )[0][0]
                with psycopg.connect(self.url, autocommit=True) as controller:
                    controller.execute("SELECT pg_advisory_lock(20261107,1)")
                    controller.execute(
                        "CREATE OR REPLACE FUNCTION feature_auth.test_pause_login() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.user_id=TG_ARGV[0] THEN PERFORM pg_advisory_xact_lock(20261107,1); END IF; RETURN NEW; END $$"
                    )
                    controller.execute(
                        psycopg.sql.SQL(
                            "CREATE TRIGGER test_pause_login BEFORE INSERT ON feature_auth.sessions FOR EACH ROW EXECUTE FUNCTION feature_auth.test_pause_login({})"
                        ).format(psycopg.sql.Literal(uid))
                    )
                    try:
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            client = Client(base)
                            login = pool.submit(client.login, email=self.email)
                            self.wait_lock("sessions")
                            reset = pool.submit(
                                self.call,
                                "reset-confirm",
                                {"token": token, "password": NEW_PASSWORD},
                                Client(base),
                            )
                            try:
                                self.wait_lock("account_apply", future=reset)
                            finally:
                                controller.execute(
                                    "SELECT pg_advisory_unlock(20261107,1)"
                                )
                            self.assertEqual(login.result(timeout=20)[0], 200)
                            self.expect(reset.result(timeout=20), 204)
                        self.assertEqual(client.request("GET", "/auth/me")[0], 401)
                    finally:
                        controller.execute("SELECT pg_advisory_unlock(20261107,1)")
                        controller.execute(
                            "DROP TRIGGER test_pause_login ON feature_auth.sessions"
                        )
                        controller.execute(
                            "DROP FUNCTION feature_auth.test_pause_login()"
                        )

    def wait_lock(self, fragment, future=None):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if future and future.done():
                self.fail("reset committed while the old-password login was paused")
            if self.query(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query ILIKE %s",
                ("%" + fragment + "%",),
            )[0][0]:
                return
            time.sleep(0.03)
        self.fail("expected PostgreSQL transaction lock was not observed")

    def mixed_05_generated_enabled_blocks_pending_users(self):
        self.register()
        for base in self.bases.values():
            self.assertEqual(Client(base).login(email=self.email)[0], 401)
            self.query("TRUNCATE feature_auth.login_attempts")
        self.assertEqual(
            self.query(
                "SELECT enabled FROM feature_auth.users WHERE email=%s", (self.email,)
            ),
            [(False,)],
        )

    def mixed_06_database_disconnect_preserves_capabilities(self):
        token = self.register()
        self.gate.disable()
        try:
            for base in self.bases.values():
                self.expect(
                    self.call("verify-confirm", {"token": token}, Client(base)),
                    503,
                    "STORAGE_UNAVAILABLE",
                )
        finally:
            self.gate.enabled.set()
        for base in self.bases.values():
            deadline = time.monotonic() + 8
            while True:
                status = Client(base).request("GET", "/healthz")[0]
                if status == 200 or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
            self.assertEqual(
                status, 200, "storage did not recover after the test fault"
            )
        self.expect(self.call("verify-confirm", {"token": token}), 204)

    def mixed_07_peer_limit_shared_between_servers(self):
        bases = list(self.bases.values())
        for n in range(10):
            self.expect(
                self.call(
                    "reset-request",
                    {"email": "missing@example.com"},
                    Client(bases[n % 4]),
                ),
                202,
            )
        for base in bases:
            self.expect(
                self.call(
                    "reset-request", {"email": "missing@example.com"}, Client(base)
                ),
                429,
                "RATE_LIMITED",
            )

    def mixed_08_private_capture_and_no_public_mailbox(self):
        token = self.register()
        with tempfile.TemporaryDirectory(prefix="fs-mail-capture-") as temp:
            output = Path(temp) / "mail.jsonl"
            self.assertEqual(capture(self.url, output, "http://127.0.0.1:5173"), 1)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            parsed = parse_qs(urlsplit(json.loads(output.read_text())["url"]).fragment)
            self.assertTrue(secrets.compare_digest(parsed["token"][0], token))
        self.assertEqual(
            self.query("SELECT token FROM feature_auth.mail_outbox"), [(None,)]
        )
        self.expect(
            self.call("verify-confirm", {"token": token}, Client(self.bases["go"])), 204
        )
        self.assertEqual(self.client.request("GET", "/auth/mailbox")[0], 404)

    def mixed_09_token_lifetimes_and_hashes(self):
        token = self.register()
        row = self.query(
            "SELECT token_hash,expires_at-created_at FROM feature_auth.account_tokens"
        )[0]
        self.assertTrue(
            secrets.compare_digest(
                bytes(row[0]), hashlib.sha256(token.encode()).digest()
            )
        )
        self.assertEqual(row[1].total_seconds(), 86400)
        self.expect(self.call("verify-confirm", {"token": token}), 204)
        self.reset_token()
        self.assertEqual(
            self.query(
                "SELECT extract(epoch FROM expires_at-created_at)::int FROM feature_auth.account_tokens"
            ),
            [(900,)],
        )

    def mixed_10_tokens_survive_process_restart(self):
        for name in BACKENDS:
            self.email = f"restart-{name}@example.com"
            with server(name, builds=self.builds, extra_env=self.env) as base:
                token = self.register(Client(base))
            with server(name, builds=self.builds, extra_env=self.env) as base:
                self.expect(
                    self.call("verify-confirm", {"token": token}, Client(base)), 204
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=[*BACKENDS, "all"], default="all")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    passed = True
    with (
        database() as url,
        tempfile.TemporaryDirectory(prefix="fs-account-build-") as output,
    ):
        with psycopg.connect(url) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
        migrate_accounts(url)
        seed_demo(url)
        builds = BackendBuilds(output)
        with DatabaseGate(url) as gate:
            env = {
                "AUTH_STORE": "postgres",
                "AUTH_DATABASE_URL": gate.url,
                "AUTH_ACCOUNT_LIFECYCLE": "true",
            }
            for backend in BACKENDS if args.backend == "all" else [args.backend]:
                print(f"\n=== {backend}: browser-session-v3 ===", flush=True)
                with server(backend, ttl=3, builds=builds, extra_env=env) as base:
                    passed = run_contract(base) and passed
                with server(
                    backend, ttl=1800, rate_window=60, builds=builds, extra_env=env
                ) as base:
                    AccountContract.url = url
                    AccountContract.base = base
                    passed = (
                        unittest.TextTestRunner(verbosity=2)
                        .run(
                            unittest.defaultTestLoader.loadTestsFromTestCase(
                                AccountContract
                            )
                        )
                        .wasSuccessful()
                        and passed
                    )
                if args.browser:
                    run_browser(
                        backend,
                        builds=builds,
                        extra_env=env,
                        client_env={
                            "VITE_AUTH_ACCOUNT_LIFECYCLE": "true",
                            "FEATURE_STANDARDS_TEST_DATABASE_URL": url,
                        },
                        playwright_config="playwright.accounts.config.ts",
                    )
            if args.backend == "all":
                with contextlib.ExitStack() as stack:
                    SharedAccounts.url = url
                    SharedAccounts.gate = gate
                    SharedAccounts.env = env
                    SharedAccounts.builds = builds
                    SharedAccounts.bases = {
                        name: stack.enter_context(
                            server(
                                name,
                                ttl=1800,
                                rate_window=60,
                                builds=builds,
                                extra_env=env,
                            )
                        )
                        for name in BACKENDS
                    }
                    names = sorted(
                        name
                        for name in dir(SharedAccounts)
                        if name.startswith("mixed_")
                    )
                    suite = unittest.TestSuite(SharedAccounts(name) for name in names)
                    passed = (
                        unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
                        and passed
                    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
