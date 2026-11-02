"""Private capture must not consume messages owned by an SMTP worker."""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from pg_support import assert_test_database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate_accounts, migrate_mail_delivery
from mail_capture import capture


@unittest.skipUnless(
    os.environ.get("AUTH_MAIL_CAPTURE_TEST_DATABASE_URL"), "requires isolated mail DB"
)
class CaptureDeliveryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = assert_test_database(
            os.environ["AUTH_MAIL_CAPTURE_TEST_DATABASE_URL"]
        )
        migrate_accounts(cls.url)
        migrate_mail_delivery(cls.url)

    def setUp(self):
        with psycopg.connect(self.url) as conn:
            conn.execute("TRUNCATE feature_auth.users CASCADE")
            conn.execute("TRUNCATE feature_auth.account_attempts")
            conn.execute(
                "SELECT feature_auth.account_apply('register','127.0.0.1','capture@example.com',%s,'test-only-hash')",
                (secrets.token_urlsafe(32),),
            )

    def query(self, sql, args=()):
        with psycopg.connect(self.url) as conn:
            return conn.execute(sql, args).fetchall()

    def test_leased_message_is_reserved_for_smtp(self):
        self.query(
            "UPDATE feature_auth.mail_delivery SET state='leased',claim_id=%s,lease_until=clock_timestamp()+interval '10 minutes',attempts=1 RETURNING outbox_id",
            (uuid.uuid4(),),
        )
        with tempfile.TemporaryDirectory(prefix="fs-capture-smtp-") as directory:
            self.assertEqual(
                capture(
                    self.url, Path(directory) / "capture.jsonl", "http://127.0.0.1:5173"
                ),
                0,
            )
        self.assertEqual(
            self.query(
                "SELECT token IS NOT NULL,delivered_at IS NULL FROM feature_auth.mail_outbox"
            ),
            [(True, True)],
        )

    def test_retry_message_remains_with_smtp(self):
        self.query(
            "UPDATE feature_auth.mail_delivery SET state='retry',attempts=1,next_attempt_at=clock_timestamp()+interval '10 minutes' RETURNING outbox_id"
        )
        with tempfile.TemporaryDirectory(prefix="fs-capture-smtp-") as directory:
            self.assertEqual(
                capture(
                    self.url, Path(directory) / "capture.jsonl", "http://127.0.0.1:5173"
                ),
                0,
            )

    def test_unclaimed_pending_message_can_be_captured(self):
        with tempfile.TemporaryDirectory(prefix="fs-capture-smtp-") as directory:
            self.assertEqual(
                capture(
                    self.url, Path(directory) / "capture.jsonl", "http://127.0.0.1:5173"
                ),
                1,
            )
        self.assertEqual(
            self.query(
                "SELECT token IS NULL,delivered_at IS NOT NULL FROM feature_auth.mail_outbox"
            ),
            [(True, True)],
        )

    def test_migration_rerun_preserves_delivery_identity_and_lease(self):
        before = self.query("SELECT delivery_id FROM feature_auth.mail_delivery")[0][0]
        self.query(
            "UPDATE feature_auth.mail_delivery SET state='leased',claim_id=%s,lease_until=clock_timestamp()+interval '10 minutes',attempts=1 RETURNING outbox_id",
            (uuid.uuid4(),),
        )
        migrate_mail_delivery(self.url)
        self.assertEqual(
            self.query(
                "SELECT delivery_id,state,attempts FROM feature_auth.mail_delivery"
            ),
            [(before, "leased", 1)],
        )


if __name__ == "__main__":
    unittest.main()
