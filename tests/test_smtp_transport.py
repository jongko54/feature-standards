"""Transport settings and real loopback SMTP wire boundary tests."""

import sys
import threading
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from uuid import uuid4

from smtp_fixture import SMTPFixture, certificates

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from smtp_transport import DeliveryError, DeliveryMessage, SMTPSettings, SMTPTransport


class SMTPConfiguration(unittest.TestCase):
    def env(self, **overrides):
        return {
            "AUTH_SMTP_HOST": "relay.example.com",
            "AUTH_SMTP_FROM": "noreply@example.com",
            "AUTH_MAIL_PUBLIC_ORIGIN": "https://app.example.com",
            **overrides,
        }

    def test_secure_defaults_and_redacted_credentials(self):
        settings = SMTPSettings.from_env(
            self.env(
                AUTH_SMTP_USERNAME="fixture-user", AUTH_SMTP_PASSWORD="fixture-secret"
            )
        )
        self.assertEqual(
            (settings.mode, settings.port, settings.timeout_seconds),
            ("starttls", 587, 10),
        )
        self.assertNotIn("fixture-user", repr(settings))
        self.assertNotIn("fixture-secret", repr(settings))

    def test_remote_plaintext_and_header_injection_rejected(self):
        for overrides in (
            {"AUTH_SMTP_MODE": "plain-local", "AUTH_MAIL_DEMO": "true"},
            {"AUTH_SMTP_FROM": "noreply@example.com\r\nBcc: other@example.com"},
            {"AUTH_MAIL_PUBLIC_ORIGIN": "https://evil.example/path"},
            {"AUTH_SMTP_USERNAME": "fixture-user"},
            {"AUTH_MAIL_PUBLIC_ORIGIN": "https://*.example.com"},
            {"AUTH_MAIL_PUBLIC_ORIGIN": "https://app.example.com:"},
            {"AUTH_SMTP_HOST": "https://relay.example.com"},
        ):
            with (
                self.subTest(overrides=sorted(overrides)),
                self.assertRaises(ValueError),
            ):
                SMTPSettings.from_env(self.env(**overrides))


class SMTPWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certificates_context = certificates()
        cls.certs = cls.certificates_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.certificates_context.__exit__(None, None, None)

    def delivery(self, **changes):
        return DeliveryMessage(
            delivery_id=str(uuid4()),
            recipient="recipient@example.com",
            kind="verify",
            token="A" * 43,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            **changes,
        )

    def settings(self, fixture, *, mode=None, **changes):
        mode = mode or ("plain-local" if fixture.mode == "plain" else fixture.mode)
        return SMTPSettings(
            host="127.0.0.1" if mode == "plain-local" else "localhost",
            port=fixture.port,
            mode=mode,
            from_address="noreply@example.com",
            public_origin="http://127.0.0.1:5173"
            if mode == "plain-local"
            else "https://app.example.com",
            ca_file=None if mode == "plain-local" else str(self.certs.root),
            demo=mode == "plain-local",
            **changes,
        )

    def error(self, settings, delivery, code, retryable):
        with self.assertRaises(DeliveryError) as caught:
            SMTPTransport(settings).send(delivery)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.retryable, retryable)
        self.assertNotIn(delivery.token, repr(caught.exception))
        self.assertNotIn(delivery.recipient, repr(caught.exception))
        self.assertIsNone(caught.exception.__context__)

    def test_starttls_authentication_and_fragment_links(self):
        with SMTPFixture(mode="starttls", certs=self.certs, auth=True) as fixture:
            settings = self.settings(
                fixture, username="fixture-user", password="fixture-secret"
            )
            delivery = self.delivery()
            SMTPTransport(settings).send(delivery)
            self.assertEqual(fixture.auth_encrypted, [True])
            self.assertEqual(fixture.message_encrypted, [True])
            parsed = BytesParser(policy=policy.default).parsebytes(fixture.messages[0])
            self.assertEqual(
                parsed["Message-ID"],
                f"<feature-standards.{delivery.delivery_id}@example.com>",
            )
            self.assertTrue(parsed.is_multipart())
            self.assertIn(
                "https://app.example.com/verify-email#token=",
                parsed.get_body(preferencelist=("plain",)).get_content(),
            )
            self.assertIn(
                "https://app.example.com/verify-email#token=",
                parsed.get_body(preferencelist=("html",)).get_content(),
            )
            self.assertLess(
                fixture.commands.index("STARTTLS"), fixture.commands.index("AUTH")
            )

    def test_direct_tls_and_reset_message(self):
        with SMTPFixture(mode="tls", certs=self.certs) as fixture:
            delivery = replace(self.delivery(), kind="reset")
            SMTPTransport(self.settings(fixture)).send(delivery)
            self.assertEqual(fixture.message_encrypted, [True])
            parsed = BytesParser(policy=policy.default).parsebytes(fixture.messages[0])
            self.assertIn(
                "/reset-password#token=",
                parsed.get_body(preferencelist=("plain",)).get_content(),
            )

    def test_wrong_ca_and_hostname_fail_without_data(self):
        for change in ({"ca_file": str(self.certs.other_root)}, {"host": "127.0.0.1"}):
            with SMTPFixture(mode="tls", certs=self.certs) as fixture:
                self.error(
                    replace(self.settings(fixture), **change),
                    self.delivery(),
                    "SMTP_TLS",
                    True,
                )
                self.assertEqual(len(fixture.messages), 0)

    def test_starttls_is_required_before_auth(self):
        with SMTPFixture(
            mode="starttls", certs=self.certs, advertise_starttls=False, auth=True
        ) as fixture:
            self.error(
                self.settings(
                    fixture, username="fixture-user", password="fixture-secret"
                ),
                self.delivery(),
                "SMTP_TLS",
                True,
            )
            self.assertNotIn("AUTH", fixture.commands)
            self.assertNotIn("MAIL", fixture.commands)

    def test_unicode_mailbox_uses_smtputf8(self):
        with SMTPFixture(mode="starttls", certs=self.certs, smtp_utf8=True) as fixture:
            SMTPTransport(self.settings(fixture)).send(
                replace(self.delivery(), recipient="한@예시.한국")
            )
            self.assertEqual(len(fixture.messages), 1)
            self.assertIn("SMTPUTF8", fixture.mail_options[0])

    def test_missing_smtputf8_is_permanent(self):
        with SMTPFixture(mode="starttls", certs=self.certs, smtp_utf8=False) as fixture:
            self.error(
                self.settings(fixture),
                replace(self.delivery(), recipient="한@example.com"),
                "SMTP_UTF8_UNSUPPORTED",
                False,
            )
            self.assertNotIn("MAIL", fixture.commands)

    def test_temporary_and_permanent_recipient_failures(self):
        for status, code, retryable in [
            (450, "SMTP_TEMPORARY", True),
            (550, "SMTP_PERMANENT", False),
        ]:
            with SMTPFixture(rcpt_code=status) as fixture:
                self.error(self.settings(fixture), self.delivery(), code, retryable)

    def test_disconnect_after_data_is_retryable_with_stable_id(self):
        delivery = self.delivery()
        with SMTPFixture(drop_after_data=True) as first:
            self.error(self.settings(first), delivery, "SMTP_NETWORK", True)
            first_id = BytesParser(policy=policy.default).parsebytes(first.messages[0])[
                "Message-ID"
            ]
        with SMTPFixture() as second:
            SMTPTransport(self.settings(second)).send(delivery)
            second_id = BytesParser(policy=policy.default).parsebytes(
                second.messages[0]
            )["Message-ID"]
        self.assertEqual(first_id, second_id)

    def test_quit_failure_does_not_revoke_known_acceptance(self):
        with SMTPFixture(quit_code=500) as fixture:
            SMTPTransport(self.settings(fixture)).send(self.delivery())
            self.assertEqual(len(fixture.messages), 1)
            self.assertIn("QUIT", fixture.commands)

    def test_header_injection_is_rejected_before_connecting(self):
        with SMTPFixture() as fixture:
            self.error(
                self.settings(fixture),
                replace(
                    self.delivery(),
                    recipient="recipient@example.com\r\nBcc:other@example.com",
                ),
                "INVALID_RECIPIENT",
                False,
            )
            self.assertEqual(fixture.commands, [])

    def test_authentication_failure_is_sanitized(self):
        with SMTPFixture(
            mode="starttls", certs=self.certs, auth=True, auth_code=535
        ) as fixture:
            self.error(
                self.settings(
                    fixture, username="fixture-user", password="fixture-secret"
                ),
                self.delivery(),
                "SMTP_AUTH",
                True,
            )
            self.assertEqual(fixture.auth_encrypted, [True])

    def test_temporary_and_permanent_data_rejections(self):
        for status, code, retryable in [
            (451, "SMTP_TEMPORARY", True),
            (554, "SMTP_PERMANENT", False),
        ]:
            with SMTPFixture(data_code=status) as fixture:
                self.error(self.settings(fixture), self.delivery(), code, retryable)

    def test_stalled_data_acknowledgement_has_a_finite_timeout(self):
        with SMTPFixture(ack_gate=threading.Event()) as fixture:
            self.error(
                replace(self.settings(fixture), timeout_seconds=1),
                self.delivery(),
                "SMTP_NETWORK",
                True,
            )
