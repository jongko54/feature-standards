"""Real PostgreSQL account invariants; opt-in with a disposable test URI."""

import hashlib
import os
import secrets
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg
from pg_support import assert_test_database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mail_capture import capture

PHC = "$argon2id$v=19$m=65536,t=3,p=4$" + "YQ" * 11 + "$" + "YQ" * 21 + "Y"


@unittest.skipUnless(
    os.environ.get("AUTH_ACCOUNT_TEST_DATABASE_URL"), "requires isolated v3 DB"
)
class AccountStoreContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = assert_test_database(os.environ["AUTH_ACCOUNT_TEST_DATABASE_URL"])
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS feature_auth CASCADE")
            conn.execute((ROOT / "features/auth/postgres/001_initial.sql").read_text())
            conn.execute((ROOT / "features/auth/postgres/002_accounts.sql").read_text())

    def setUp(self):
        with psycopg.connect(self.url) as conn:
            conn.execute("TRUNCATE feature_auth.users CASCADE")
            conn.execute("TRUNCATE feature_auth.account_attempts")

    def apply(self, action, *, email="new@example.com", token="", phc=PHC):
        with psycopg.connect(self.url) as conn:
            return conn.execute(
                "SELECT feature_auth.account_apply(%s,'127.0.0.1',%s,%s,%s)",
                (action, email, token, phc),
            ).fetchone()[0]

    def query(self, statement, args=()):
        with psycopg.connect(self.url) as conn:
            return conn.execute(statement, args).fetchall()

    def register(self):
        token = secrets.token_urlsafe(32)
        self.assertEqual(self.apply("register", token=token), 0)
        return token

    def verified(self):
        token = self.register()
        self.assertEqual(self.apply("verify-confirm", token=token), 0)
        return token

    def test_account_gateway_accepts_a_new_registration(self):
        token = secrets.token_urlsafe(32)
        with psycopg.connect(self.url) as conn:
            code = conn.execute(
                "SELECT feature_auth.account_apply('register','127.0.0.1','new@example.com',%s,%s)",
                (token, PHC),
            ).fetchone()[0]
            self.assertEqual(code, 0)
            self.assertEqual(
                conn.execute(
                    "SELECT enabled FROM feature_auth.users WHERE email='new@example.com'"
                ).fetchone(),
                (False,),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT token_hash FROM feature_auth.account_tokens"
                ).fetchone()[0],
                hashlib.sha256(token.encode()).digest(),
            )

    def test_duplicate_never_replaces_password_or_reissues(self):
        token = self.register()
        self.assertEqual(
            self.apply("register", token=secrets.token_urlsafe(32), phc="replacement"),
            0,
        )
        self.assertEqual(
            self.query("SELECT password_hash FROM feature_auth.users"), [(PHC,)]
        )
        self.assertEqual(
            self.query("SELECT token FROM feature_auth.mail_outbox"), [(token,)]
        )

    def test_verification_single_use_and_kind_binding(self):
        token = self.register()
        self.assertEqual(self.apply("reset-confirm", token=token), -1)
        self.assertEqual(self.apply("verify-confirm", token=token), 0)
        self.assertEqual(self.apply("verify-confirm", token=token), -1)
        self.assertEqual(
            self.query("SELECT enabled FROM feature_auth.users"), [(True,)]
        )
        self.assertEqual(
            self.query("SELECT token FROM feature_auth.mail_outbox"), [(None,)]
        )

    def test_expiry_and_disabled_admin_preserve_token(self):
        token = self.register()
        self.query("UPDATE feature_auth.users SET admin_enabled=false RETURNING id")
        self.assertEqual(self.apply("verify-confirm", token=token), -1)
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.account_tokens"), [(1,)]
        )
        self.query("UPDATE feature_auth.users SET admin_enabled=true RETURNING id")
        self.query(
            "UPDATE feature_auth.account_tokens SET expires_at=created_at+interval '1 microsecond' RETURNING user_id"
        )
        self.assertEqual(self.apply("verify-confirm", token=token), -1)
        self.assertEqual(
            self.query("SELECT enabled FROM feature_auth.users"), [(False,)]
        )

    def test_generic_unknown_requests_and_unverified_reset(self):
        self.register()
        for action in ("verify-request", "reset-request"):
            self.assertEqual(
                self.apply(
                    action, email="missing@example.com", token=secrets.token_urlsafe(32)
                ),
                0,
            )
        self.assertEqual(
            self.apply("reset-request", token=secrets.token_urlsafe(32)), 0
        )
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.mail_outbox"), [(1,)]
        )

    def test_cooldown_and_reissue_invalidates_old_token(self):
        old = self.register()
        fresh = secrets.token_urlsafe(32)
        self.assertEqual(self.apply("verify-request", token=fresh), 0)
        self.assertEqual(
            self.query("SELECT token FROM feature_auth.mail_outbox"), [(old,)]
        )
        self.query(
            "UPDATE feature_auth.account_mail_limits SET sent_at=clock_timestamp()-interval '61 seconds' RETURNING user_id"
        )
        self.assertEqual(self.apply("verify-request", token=fresh), 0)
        self.assertEqual(self.apply("verify-confirm", token=old), -1)
        self.assertEqual(self.apply("verify-confirm", token=fresh), 0)

    def test_reset_replaces_password_revokes_sessions_and_preserves_admin(self):
        self.verified()
        uid = self.query("SELECT id FROM feature_auth.users")[0][0]
        self.query(
            "INSERT INTO feature_auth.sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES (%s,%s,%s,clock_timestamp(),clock_timestamp()+interval '1 hour') RETURNING user_id",
            (secrets.token_bytes(32), uid, secrets.token_urlsafe(32)),
        )
        reset = secrets.token_urlsafe(32)
        self.assertEqual(self.apply("reset-request", token=reset), 0)
        self.query("UPDATE feature_auth.users SET admin_enabled=false RETURNING id")
        self.assertEqual(self.apply("reset-confirm", token=reset, phc="new-hash"), -1)
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.sessions"), [(1,)]
        )
        self.query("UPDATE feature_auth.users SET admin_enabled=true RETURNING id")
        self.assertEqual(self.apply("reset-confirm", token=reset, phc="new-hash"), 0)
        self.assertEqual(
            self.query("SELECT password_hash FROM feature_auth.users"), [("new-hash",)]
        )
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.sessions"), [(0,)]
        )
        self.assertEqual(self.apply("reset-confirm", token=reset), -1)

    def test_same_peer_rate_limit_is_shared(self):
        for _ in range(10):
            self.assertEqual(
                self.apply(
                    "reset-request",
                    email="missing@example.com",
                    token=secrets.token_urlsafe(32),
                ),
                0,
            )
        self.assertGreater(
            self.apply("reset-request", token=secrets.token_urlsafe(32)), 0
        )
        self.assertEqual(
            self.query("SELECT hits FROM feature_auth.account_attempts"), [(10,)]
        )

    def test_rollback_does_not_leave_user_or_outbox(self):
        with psycopg.connect(self.url) as conn:
            conn.execute(
                "SELECT feature_auth.account_apply('register','127.0.0.1','new@example.com',%s,%s)",
                (secrets.token_urlsafe(32), PHC),
            )
            conn.rollback()
        self.assertEqual(self.query("SELECT count(*) FROM feature_auth.users"), [(0,)])
        self.assertEqual(
            self.query("SELECT count(*) FROM feature_auth.mail_outbox"), [(0,)]
        )

    def test_migration_rerun_does_not_verify_pending_users(self):
        self.register()
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute((ROOT / "features/auth/postgres/002_accounts.sql").read_text())
        self.assertEqual(
            self.query("SELECT enabled,email_verified_at FROM feature_auth.users"),
            [(False, None)],
        )

    def test_reservation_is_consumed_once_and_is_transaction_local(self):
        with psycopg.connect(self.url) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT feature_auth.account_reserve('register','127.0.0.1')"
                ).fetchone(),
                (0,),
            )
            conn.execute(
                "SELECT feature_auth.account_apply('register','127.0.0.1','one@example.com',%s,%s)",
                (secrets.token_urlsafe(32), PHC),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT hits FROM feature_auth.account_attempts"
                ).fetchone(),
                (1,),
            )
            conn.execute(
                "SELECT feature_auth.account_apply('register','127.0.0.1','two@example.com',%s,%s)",
                (secrets.token_urlsafe(32), PHC),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT hits FROM feature_auth.account_attempts"
                ).fetchone(),
                (2,),
            )
        self.assertEqual(self.apply("register", token=secrets.token_urlsafe(32)), 0)
        self.assertEqual(
            self.query("SELECT hits FROM feature_auth.account_attempts"), [(3,)]
        )

    def test_private_capture_preserves_file_when_commit_acknowledgement_is_lost(self):
        self.register()
        original_connect = psycopg.connect

        class LostAcknowledgement:
            def __init__(self, *args, **kwargs):
                self.connection = original_connect(*args, **kwargs)

            def __enter__(self):
                return self.connection.__enter__()

            def __exit__(self, *args):
                self.connection.__exit__(*args)
                raise psycopg.OperationalError("test-only lost commit acknowledgement")

        with tempfile.TemporaryDirectory(prefix="fs-private-capture-") as directory:
            destination = Path(directory) / "captured.jsonl"
            with (
                patch(
                    "mail_capture.psycopg.connect",
                    side_effect=LostAcknowledgement,
                ),
                self.assertRaises(psycopg.OperationalError),
            ):
                capture(self.url, destination, "http://127.0.0.1:5173")
            self.assertTrue(
                destination.exists(),
                "durable delivery must survive an uncertain commit result",
            )
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(
                self.query(
                    "SELECT token,delivered_at IS NOT NULL FROM feature_auth.mail_outbox"
                ),
                [(None, True)],
            )
            self.assertEqual(
                capture(
                    self.url, Path(directory) / "retry.jsonl", "http://127.0.0.1:5173"
                ),
                0,
            )

    def test_capture_never_overwrites_an_existing_file(self):
        self.register()
        with tempfile.TemporaryDirectory(prefix="fs-private-capture-") as directory:
            destination = Path(directory) / "existing.jsonl"
            destination.write_text("preserve this file")
            with self.assertRaises(FileExistsError):
                capture(self.url, destination, "http://127.0.0.1:5173")
            self.assertEqual(destination.read_text(), "preserve this file")
        self.assertEqual(
            self.query("SELECT delivered_at IS NULL FROM feature_auth.mail_outbox"),
            [(True,)],
        )
