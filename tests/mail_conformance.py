#!/usr/bin/env python3
"""Four-language accounts -> real TLS SMTP -> capability consumption and queue races."""

from __future__ import annotations

import contextlib
import re
import secrets
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import psycopg
from conformance import BACKENDS, PASSWORD, BackendBuilds, Client, server
from pg_support import database
from smtp_fixture import SMTPFixture, certificates

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate_accounts, migrate_mail_delivery, seed_demo
from mail_capture import capture
from mail_worker import MailWorker, WorkerSettings
from smtp_transport import SMTPSettings, SMTPTransport

ORIGIN = "http://127.0.0.1:5173"
NEW_PASSWORD = "smtp-reset-new-long-password"


class MailDeliveryContract(unittest.TestCase):
    url = ""
    bases: ClassVar[dict[str, str]] = {}
    fixture = None
    certs = None

    def query(self, statement, args=()):
        with psycopg.connect(self.url) as conn:
            cursor = conn.execute(statement, args)
            return cursor.fetchall() if cursor.description else []

    def setUp(self):
        self.query(
            "DELETE FROM feature_auth.users WHERE id NOT IN ('demo-user','other-user') RETURNING id"
        )
        self.query(
            "TRUNCATE feature_auth.login_attempts,feature_auth.account_attempts,feature_auth.sessions"
        )
        self.fixture.messages.clear()
        self.fixture.message_encrypted.clear()
        self.fixture.mail_options.clear()
        self.fixture.data_received.clear()
        self.fixture.rcpt_code = 250
        self.fixture.data_code = 250
        self.fixture.ack_gate = None
        self.fixture.drop_after_data = False
        self.email = "smtp-account@example.com"

    def worker(self):
        settings = WorkerSettings.from_env(
            smtp_timeout_seconds=2,
            mapping={
                "AUTH_DATABASE_URL": self.url,
                "AUTH_MAIL_DEMO": "true",
                "AUTH_MAIL_BATCH_SIZE": "1",
            },
        )
        smtp = SMTPSettings(
            host="localhost",
            port=self.fixture.port,
            mode="starttls",
            from_address="noreply@example.com",
            public_origin=ORIGIN,
            ca_file=str(self.certs.root),
            timeout_seconds=2,
            demo=True,
        )
        return MailWorker(settings, SMTPTransport(smtp))

    def post(self, base, path, body):
        return Client(base).request("POST", "/auth/" + path, body)

    def register(self, base=None):
        base = base or self.bases["python"]
        self.assertEqual(
            self.post(base, "register", {"email": self.email, "password": PASSWORD})[0],
            202,
        )

    def link(self, index=-1):
        message = BytesParser(policy=policy.default).parsebytes(
            self.fixture.messages[index]
        )
        content = message.get_body(preferencelist=("plain",)).get_content()
        match = re.search(
            r"http://127\.0\.0\.1:5173/(?:verify-email|reset-password)#[A-Za-z0-9_=&%-]+",
            content,
        )
        self.assertIsNotNone(match, "expected local SMTP capability link")
        parts = urlsplit(match[0])
        token = parse_qs(parts.fragment)["token"][0]
        self.assertEqual(len(token), 43)
        return token, str(message["Message-ID"])

    def verify(self, base=None):
        self.worker().run_once()
        token, _ = self.link()
        self.assertEqual(
            self.post(
                base or self.bases["python"],
                "email-verification/confirm",
                {"token": token},
            )[0],
            204,
        )
        return token

    def test_01_all_languages_deliver_verify_and_reset_over_tls(self):
        names = list(self.bases)
        for n, name in enumerate(names):
            with self.subTest(issuer=name):
                self.email = f"{name}-한@example.com"
                issuer = self.bases[name]
                reader = self.bases[names[(n + 1) % 4]]
                self.register(issuer)
                self.assertEqual(self.worker().run_once().delivered, 1)
                verify, message_id = self.link()
                self.assertEqual(
                    self.post(reader, "email-verification/confirm", {"token": verify})[
                        0
                    ],
                    204,
                )
                client = Client(reader)
                self.assertEqual(client.login(email=self.email)[0], 200)
                old = client.cookie
                self.assertEqual(
                    self.post(issuer, "password-reset/request", {"email": self.email})[
                        0
                    ],
                    202,
                )
                self.assertEqual(self.worker().run_once().delivered, 1)
                reset, reset_id = self.link()
                self.assertNotEqual(message_id, reset_id)
                self.assertEqual(
                    self.post(
                        reader,
                        "password-reset/confirm",
                        {"token": reset, "password": NEW_PASSWORD},
                    )[0],
                    204,
                )
                for base in self.bases.values():
                    copied = Client(base)
                    copied.cookie = old
                    self.assertEqual(copied.request("GET", "/auth/me")[0], 401)
                self.assertEqual(
                    client.login(email=self.email, password=NEW_PASSWORD)[0], 200
                )
        self.assertEqual(self.fixture.message_encrypted, [True] * 8)
        self.assertTrue(
            all("SMTPUTF8" in options for options in self.fixture.mail_options)
        )
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM feature_auth.mail_delivery WHERE state='delivered'"
            ),
            [(8,)],
        )

    def test_02_temporary_failure_retries_with_stable_identity(self):
        self.register()
        identity = self.query("SELECT delivery_id FROM feature_auth.mail_delivery")[0][
            0
        ]
        self.fixture.rcpt_code = 450
        self.assertEqual(self.worker().run_once().retried, 1)
        self.assertEqual(
            self.query(
                "SELECT state,attempts,last_error_code FROM feature_auth.mail_delivery"
            ),
            [("retry", 1, "SMTP_TEMPORARY")],
        )
        self.assertEqual(
            self.query(
                "SELECT token IS NOT NULL,delivered_at IS NULL FROM feature_auth.mail_outbox"
            ),
            [(True, True)],
        )
        self.assertEqual(self.worker().run_once().processed, 0)
        self.query(
            "UPDATE feature_auth.mail_delivery SET next_attempt_at=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        self.fixture.rcpt_code = 250
        self.assertEqual(self.worker().run_once().delivered, 1)
        _, message_id = self.link()
        self.assertEqual(message_id, f"<feature-standards.{identity}@example.com>")
        self.assertEqual(
            self.query("SELECT attempts FROM feature_auth.mail_delivery"), [(2,)]
        )

    def test_03_permanent_failure_never_claims_delivery(self):
        self.register()
        self.fixture.rcpt_code = 550
        self.assertEqual(self.worker().run_once().failed, 1)
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("failed", "SMTP_PERMANENT")],
        )
        self.assertEqual(
            self.query(
                "SELECT token IS NULL,delivered_at IS NULL FROM feature_auth.mail_outbox"
            ),
            [(True, True)],
        )
        self.assertEqual(len(self.fixture.messages), 0)

    def test_04_consumption_after_claim_prevents_smtp(self):
        self.register()
        worker = self.worker()
        claim = worker.claim()
        self.assertIsNotNone(claim)
        self.assertEqual(
            self.post(
                self.bases["go"], "email-verification/confirm", {"token": claim.token}
            )[0],
            204,
        )
        self.assertIsNone(worker.validate(claim))
        self.assertEqual(len(self.fixture.messages), 0)
        self.assertEqual(
            self.query("SELECT token IS NULL FROM feature_auth.mail_outbox"), [(True,)]
        )
        self.query(
            "UPDATE feature_auth.mail_delivery SET lease_until=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        self.assertEqual(self.worker().run_once().cancelled, 1)
        self.assertEqual(
            self.query("SELECT state FROM feature_auth.mail_delivery"), [("cancelled",)]
        )

    def test_05_reissue_during_smtp_does_not_ack_replacement(self):
        self.register()
        gate = threading.Event()
        self.fixture.ack_gate = gate
        with ThreadPoolExecutor(max_workers=1) as pool:
            sending = pool.submit(self.worker().run_once)
            self.assertTrue(
                self.fixture.data_received.wait(5), "SMTP did not receive DATA"
            )
            old_token, _ = self.link()
            self.query(
                "UPDATE feature_auth.account_mail_limits SET sent_at=clock_timestamp()-interval '61 seconds' RETURNING user_id"
            )
            try:
                self.assertEqual(
                    self.post(
                        self.bases["java"],
                        "email-verification/request",
                        {"email": self.email},
                    )[0],
                    202,
                )
            finally:
                gate.set()
            self.assertEqual(sending.result(timeout=8).fenced, 1)
        self.assertEqual(
            self.query("SELECT state,attempts FROM feature_auth.mail_delivery"),
            [("pending", 0)],
        )
        self.fixture.ack_gate = None
        self.assertEqual(self.worker().run_once().delivered, 1)
        new_token, _ = self.link()
        self.assertFalse(secrets.compare_digest(old_token, new_token))
        self.assertEqual(
            self.post(
                self.bases["rust"], "email-verification/confirm", {"token": old_token}
            )[0],
            400,
        )
        self.assertEqual(
            self.post(
                self.bases["python"], "email-verification/confirm", {"token": new_token}
            )[0],
            204,
        )

    def test_06_capture_and_smtp_race_have_one_consumer(self):
        for n in range(6):
            self.email = f"capture-race-{n}@example.com"
            self.register()
            before = len(self.fixture.messages)
            start = threading.Barrier(2)
            with (
                tempfile.TemporaryDirectory(prefix="fs-mail-race-") as directory,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):

                def capture_once(start=start, directory=directory):
                    start.wait()
                    return capture(self.url, Path(directory) / "capture.jsonl", ORIGIN)

                def smtp_once(start=start):
                    worker = self.worker()
                    start.wait()
                    return worker.run_once()

                captured = pool.submit(capture_once)
                sent = pool.submit(smtp_once)
                count = captured.result(timeout=10)
                stats = sent.result(timeout=10)
            self.assertEqual(count + stats.accepted, 1)
            self.assertEqual(len(self.fixture.messages) - before, stats.accepted)

    def test_07_concurrent_smtp_workers_send_once(self):
        self.register()
        start = threading.Barrier(2)

        def deliver():
            worker = self.worker()
            start.wait()
            return worker.run_once()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: deliver(), range(2)))
        self.assertEqual(sum(item.accepted for item in statuses), 1)
        self.assertEqual(len(self.fixture.messages), 1)
        self.assertEqual(
            self.query("SELECT attempts,state FROM feature_auth.mail_delivery"),
            [(1, "delivered")],
        )

    def test_08_uncertain_smtp_acceptance_retries_same_message_id(self):
        self.register()
        self.fixture.drop_after_data = True
        self.assertEqual(self.worker().run_once().retried, 1)
        first_token, first_id = self.link()
        self.query(
            "UPDATE feature_auth.mail_delivery SET next_attempt_at=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        self.fixture.drop_after_data = False
        self.assertEqual(self.worker().run_once().delivered, 1)
        retry_token, retry_id = self.link()
        self.assertEqual(first_id, retry_id)
        self.assertTrue(secrets.compare_digest(first_token, retry_token))
        self.assertEqual(len(self.fixture.messages), 2)
        self.assertEqual(
            self.query("SELECT attempts,state FROM feature_auth.mail_delivery"),
            [(2, "delivered")],
        )


def main():
    with (
        database() as url,
        tempfile.TemporaryDirectory(prefix="fs-mail-build-") as build_dir,
    ):
        with psycopg.connect(url) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
        migrate_accounts(url)
        seed_demo(url)
        migrate_mail_delivery(url)
        builds = BackendBuilds(build_dir)
        with contextlib.ExitStack() as stack:
            certs = stack.enter_context(certificates())
            fixture = stack.enter_context(SMTPFixture(mode="starttls", certs=certs))
            MailDeliveryContract.url = url
            MailDeliveryContract.fixture = fixture
            MailDeliveryContract.certs = certs
            env = {
                "AUTH_STORE": "postgres",
                "AUTH_ACCOUNT_LIFECYCLE": "true",
                "AUTH_DATABASE_URL": url,
            }
            MailDeliveryContract.bases = {
                name: stack.enter_context(
                    server(name, ttl=1800, rate_window=60, builds=builds, extra_env=env)
                )
                for name in BACKENDS
            }
            result = unittest.TextTestRunner(verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(MailDeliveryContract)
            )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
