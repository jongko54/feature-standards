"""Worker policy and opt-in PostgreSQL delivery fencing regressions."""

from __future__ import annotations

import os
import secrets
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from pg_support import assert_test_database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mail_worker import MailWorker, WorkerError, WorkerSettings
from smtp_transport import DeliveryError


class WorkerSettingsTests(unittest.TestCase):
    def test_tls_is_required_for_remote_databases(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                WorkerSettings.from_env(
                    mapping={
                        "AUTH_DATABASE_URL": "postgresql://x@remote.example/db?sslmode=disable"
                    }
                )
            settings = WorkerSettings.from_env(
                mapping={
                    "AUTH_DATABASE_URL": "postgresql://x:secret@remote.example/db?sslmode=verify-full"
                }
            )
            self.assertNotIn("secret", repr(settings))

    def test_plain_loopback_requires_demo_and_explicit_tls_policy(self):
        uri = "postgresql://x@127.0.0.1:5432/feature_standards_test?sslmode=disable"
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                WorkerSettings.from_env(mapping={"AUTH_DATABASE_URL": uri})
            settings = WorkerSettings.from_env(
                mapping={"AUTH_DATABASE_URL": uri, "AUTH_MAIL_DEMO": "true"}
            )
            self.assertGreaterEqual(settings.lease_seconds, 300)

    def test_routing_overrides_and_short_leases_are_rejected(self):
        uri = "postgresql://x@127.0.0.1:5432/feature_standards_test?sslmode=disable"
        for extra in (
            "&hostaddr=198.51.100.1",
            "&host=production.example",
            "&dbname=production",
            "&service=production",
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                WorkerSettings.from_env(
                    mapping={"AUTH_DATABASE_URL": uri + extra, "AUTH_MAIL_DEMO": "true"}
                )
        with self.assertRaises(ValueError):
            WorkerSettings.from_env(
                smtp_timeout_seconds=30,
                mapping={
                    "AUTH_DATABASE_URL": uri,
                    "AUTH_MAIL_DEMO": "true",
                    "AUTH_MAIL_LEASE_SECONDS": "300",
                },
            )


class RecordingSender:
    def __init__(self, error=None):
        self.messages = []
        self.error = error

    def send(self, message):
        self.messages.append(message)
        if self.error:
            raise self.error


@unittest.skipUnless(
    os.environ.get("AUTH_MAIL_TEST_DATABASE_URL"),
    "requires a disposable SMTP queue database",
)
class MailWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = assert_test_database(os.environ["AUTH_MAIL_TEST_DATABASE_URL"])
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
            for migration in (
                "001_initial.sql",
                "002_accounts.sql",
                "003_mail_delivery.sql",
            ):
                conn.execute((ROOT / "features/auth/postgres" / migration).read_text())

    def setUp(self):
        self.query("TRUNCATE feature_auth.users CASCADE")
        self.query("TRUNCATE feature_auth.account_attempts")
        self.settings = WorkerSettings(self.url, demo=True)
        self.sender = RecordingSender()
        self.worker = MailWorker(self.settings, self.sender)

    def query(self, statement, args=()):
        with psycopg.connect(self.url) as conn:
            cursor = conn.execute(statement, args)
            return cursor.fetchall() if cursor.description else []

    def message(self, email="test@example.com"):
        token = secrets.token_urlsafe(32)
        self.query(
            "SELECT feature_auth.account_apply('register','127.0.0.1',%s,%s,'test-phc')",
            (email, token),
        )
        return self.query(
            "SELECT id FROM feature_auth.mail_outbox WHERE recipient=%s", (email,)
        )[0][0], token

    def test_one_delivery_is_accepted_then_acknowledged_and_redacted(self):
        outbox, token = self.message()
        stats = self.worker.run_once()
        self.assertEqual((stats.accepted, stats.delivered), (1, 1))
        self.assertEqual(len(self.sender.messages), 1)
        self.assertTrue(secrets.compare_digest(self.sender.messages[0].token, token))
        self.assertEqual(
            self.query(
                "SELECT token IS NULL,delivered_at IS NOT NULL FROM feature_auth.mail_outbox WHERE id=%s",
                (outbox,),
            ),
            [(True, True)],
        )
        self.assertEqual(
            self.query("SELECT state,attempts FROM feature_auth.mail_delivery"),
            [("delivered", 1)],
        )

    def test_concurrent_claims_have_one_winner(self):
        self.message()
        workers = [MailWorker(self.settings, RecordingSender()) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda worker: worker.claim(), workers))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        self.assertEqual(
            self.query("SELECT attempts FROM feature_auth.mail_delivery"), [(1,)]
        )

    def test_retry_keeps_delivery_id_and_obeys_due_time(self):
        self.message()
        self.sender.error = DeliveryError("SMTP_TEMPORARY", True)
        first = self.worker.run_once()
        self.assertEqual(first.retried, 1)
        original = self.sender.messages[0].delivery_id
        self.assertEqual(self.worker.run_once().accepted, 0)
        self.query(
            "UPDATE feature_auth.mail_delivery SET next_attempt_at=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        self.sender.error = None
        self.assertEqual(self.worker.run_once().delivered, 1)
        self.assertEqual(self.sender.messages[-1].delivery_id, original)

    def test_expired_lease_reclaims_and_stale_ack_is_fenced(self):
        outbox, token = self.message()
        old = self.worker.claim()
        self.query(
            "UPDATE feature_auth.mail_delivery SET lease_until=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        fresh = self.worker.claim()
        self.assertIsNotNone(fresh)
        self.assertEqual(old.delivery_id, fresh.delivery_id)
        self.assertNotEqual(old.claim_id, fresh.claim_id)
        self.assertFalse(self.worker.acknowledge(old))
        self.assertFalse(self.worker.fail(old, "SMTP_PERMANENT", False))
        self.assertEqual(
            self.query(
                "SELECT token=%s FROM feature_auth.mail_outbox WHERE id=%s",
                (token, outbox),
            ),
            [(True,)],
        )
        self.assertTrue(self.worker.acknowledge(fresh))

    def test_permanent_failure_clears_capability_without_delivery_claim(self):
        self.message()
        self.sender.error = DeliveryError("SMTP_PERMANENT", False)
        self.assertEqual(self.worker.run_once().failed, 1)
        self.assertEqual(
            self.query(
                "SELECT token IS NULL,delivered_at IS NULL FROM feature_auth.mail_outbox"
            ),
            [(True, True)],
        )
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("failed", "SMTP_PERMANENT")],
        )

    def test_exhausted_lease_does_not_remain_leased_forever(self):
        self.message()
        self.worker.claim()
        self.query(
            "UPDATE feature_auth.mail_delivery SET attempts=5,lease_until=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        stats = self.worker.run_once()
        self.assertEqual((stats.failed, stats.cancelled), (1, 0))
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("failed", "ATTEMPTS_EXHAUSTED")],
        )
        self.assertEqual(
            self.query("SELECT token IS NULL FROM feature_auth.mail_outbox"), [(True,)]
        )

    def test_expired_consumed_and_disabled_capabilities_are_not_sent(self):
        for variant in ("expired", "consumed", "disabled"):
            outbox, token = self.message(variant + "@example.com")
            if variant == "expired":
                self.query(
                    "UPDATE feature_auth.mail_outbox SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s RETURNING id",
                    (outbox,),
                )
            elif variant == "consumed":
                self.query(
                    "SELECT feature_auth.account_apply('verify-confirm','127.0.0.1','',%s,'')",
                    (token,),
                )
            else:
                self.query(
                    "UPDATE feature_auth.users SET admin_enabled=false WHERE email=%s RETURNING id",
                    (variant + "@example.com",),
                )
        self.assertEqual(self.worker.run_once().accepted, 0)
        self.assertEqual(len(self.sender.messages), 0)
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM feature_auth.mail_outbox WHERE token IS NOT NULL"
            ),
            [(0,)],
        )

    def test_reissue_between_claim_and_send_cancels_old_work(self):
        self.message()
        claim = self.worker.claim()
        self.query(
            "UPDATE feature_auth.account_mail_limits SET sent_at=clock_timestamp()-interval '61 seconds' RETURNING user_id"
        )
        replacement = secrets.token_urlsafe(32)
        self.query(
            "SELECT feature_auth.account_apply('verify-request','127.0.0.1','test@example.com',%s,'')",
            (replacement,),
        )
        self.assertIsNone(self.worker.validate(claim))
        self.assertFalse(self.worker.acknowledge(claim))
        self.assertEqual(
            self.query("SELECT token=%s FROM feature_auth.mail_outbox", (replacement,)),
            [(True,)],
        )
        self.assertEqual(self.worker.run_once().delivered, 1)
        self.assertTrue(
            secrets.compare_digest(self.sender.messages[0].token, replacement)
        )

    def test_send_failure_diagnostics_never_reach_metadata(self):
        self.message()
        self.sender.error = RuntimeError("private recipient token password diagnostic")
        self.assertEqual(self.worker.run_once().retried, 1)
        self.assertEqual(
            self.query("SELECT last_error_code FROM feature_auth.mail_delivery"),
            [("INTERNAL",)],
        )

    def test_last_unknown_transport_failure_is_failed_not_retried(self):
        from dataclasses import replace

        self.message()
        self.sender.error = RuntimeError("untrusted private diagnostic")
        worker = MailWorker(replace(self.settings, max_attempts=1), self.sender)
        stats = worker.run_once()
        self.assertEqual((stats.failed, stats.retried, stats.cancelled), (1, 0, 0))
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("failed", "INTERNAL")],
        )

    def test_account_disabled_during_transport_failure_is_cancelled(self):
        self.message()

        def disabled(message):
            self.query("UPDATE feature_auth.users SET admin_enabled=false RETURNING id")
            raise DeliveryError("SMTP_NETWORK", True)

        self.sender.send = disabled
        stats = self.worker.run_once()
        self.assertEqual((stats.cancelled, stats.retried, stats.failed), (1, 0, 0))
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("cancelled", "DISABLED")],
        )

    def test_uncertain_ack_commit_does_not_record_smtp_failure(self):
        self.message()
        original = psycopg.connect

        class LostAck:
            def __init__(self, *args, **kwargs):
                self.connection = original(*args, **kwargs)

            def __enter__(self):
                return self.connection.__enter__()

            def __exit__(self, *args):
                self.connection.__exit__(*args)
                raise psycopg.OperationalError("private commit acknowledgement lost")

        claim = self.worker.claim()
        self.sender.send(self.worker.validate(claim))
        self.worker._connect = LostAck
        with self.assertRaises(WorkerError):
            self.worker.acknowledge(claim)
        self.assertEqual(
            self.query("SELECT state,last_error_code FROM feature_auth.mail_delivery"),
            [("delivered", None)],
        )

    def test_claim_commit_failure_never_starts_smtp(self):
        self.message()
        original = psycopg.connect

        class FailedCommit:
            def __init__(self, *args, **kwargs):
                self.connection = original(*args, **kwargs)

            def __enter__(self):
                return self.connection.__enter__()

            def __exit__(self, *args):
                self.connection.rollback()
                self.connection.close()
                raise psycopg.OperationalError("test-only rejected commit")

        self.worker._connect = FailedCommit
        with self.assertRaises(WorkerError):
            self.worker.run_once()
        self.assertEqual(self.sender.messages, [])
        self.assertEqual(
            self.query("SELECT state,attempts FROM feature_auth.mail_delivery"),
            [("pending", 0)],
        )

    def test_consume_after_claim_is_detected_before_smtp(self):
        _, token = self.message()
        claim = self.worker.claim()
        self.query(
            "SELECT feature_auth.account_apply('verify-confirm','127.0.0.1','',%s,'')",
            (token,),
        )
        self.assertIsNone(self.worker.validate(claim))
        self.assertFalse(self.worker.acknowledge(claim))
        self.assertEqual(self.sender.messages, [])

    def test_failed_ack_retries_same_message_id_after_lease(self):
        self.message()
        claim = self.worker.claim()
        self.sender.send(self.worker.validate(claim))
        # SMTP accepted, but a worker died before recording an acknowledgement.
        self.query(
            "UPDATE feature_auth.mail_delivery SET lease_until=clock_timestamp()-interval '1 second' RETURNING outbox_id"
        )
        self.assertEqual(self.worker.run_once().delivered, 1)
        self.assertEqual(len(self.sender.messages), 2)
        self.assertEqual(
            self.sender.messages[0].delivery_id, self.sender.messages[1].delivery_id
        )

    def test_unavailable_database_is_sanitized(self):
        def unavailable(*args, **kwargs):
            raise psycopg.OperationalError("private database secret")

        with self.assertRaises(WorkerError) as caught:
            MailWorker(self.settings, self.sender, connect=unavailable)
        self.assertNotIn("private", str(caught.exception))
