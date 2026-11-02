"""SMTP adapter. Success means the relay acknowledged DATA, not inbox delivery."""

from __future__ import annotations

import html
import ipaddress
import os
import re
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.errors import HeaderParseError, NonASCIILocalPartDefect
from email.message import EmailMessage
from email.policy import SMTP, SMTPUTF8
from email.utils import format_datetime
from urllib.parse import urlencode, urlsplit
from uuid import UUID

ERROR_CODES = frozenset(
    {
        "SMTP_NETWORK",
        "SMTP_TLS",
        "SMTP_AUTH",
        "SMTP_TEMPORARY",
        "SMTP_PERMANENT",
        "SMTP_UTF8_UNSUPPORTED",
        "INVALID_RECIPIENT",
        "INVALID_MESSAGE",
    }
)


class DeliveryError(Exception):
    def __init__(self, code: str, retryable: bool):
        if code not in ERROR_CODES:
            raise ValueError("Unsupported delivery error code")
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class DeliveryMessage:
    delivery_id: str
    recipient: str = field(repr=False)
    kind: str
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    mode: str
    from_address: str = field(repr=False)
    public_origin: str
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    ca_file: str | None = field(default=None, repr=False)
    timeout_seconds: int = 10
    demo: bool = False

    def __post_init__(self):
        if (
            not self.host
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in self.host)
            or any(c in self.host for c in "@/\\?#")
            or not 1 <= self.port <= 65535
            or not 1 <= self.timeout_seconds <= 30
            or self.mode not in ("starttls", "tls", "plain-local")
            or bool(self.username) != bool(self.password)
            or self.username is not None
            and not self.username
            or self.password is not None
            and not self.password
        ):
            raise ValueError("Invalid SMTP connection configuration")
        try:
            _host(self.host)
            _address(self.from_address, ascii_only=True)
            origin = urlsplit(self.public_origin)
            port = origin.port
            _host(origin.hostname or "")
        except (ValueError, UnicodeError, HeaderParseError):
            raise ValueError("Invalid SMTP sender or origin configuration") from None
        if (
            origin.scheme not in ("https", "http")
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
            or self.public_origin != f"{origin.scheme}://{origin.netloc}"
            or "*" in origin.netloc
            or "\\" in origin.netloc
            or origin.netloc.endswith(":")
            or any(
                c.isspace() or ord(c) < 32 or ord(c) == 127 for c in self.public_origin
            )
            or port is not None
            and not 1 <= port <= 65535
            or self.ca_file == ""
        ):
            raise ValueError("AUTH_MAIL_PUBLIC_ORIGIN must be one exact HTTPS origin")
        local_origin = origin.hostname == "localhost" or _loopback(origin.hostname)
        if origin.scheme != "https" and not (self.demo and local_origin):
            raise ValueError("An HTTP public origin requires a local mail demo")
        if self.mode == "plain-local" and not (
            self.demo
            and _loopback(self.host)
            and local_origin
            and origin.scheme == "http"
            and self.username is None
            and self.password is None
            and self.ca_file is None
        ):
            raise ValueError(
                "Plain SMTP requires an unauthenticated numeric-loopback demo"
            )

    @classmethod
    def from_env(cls, mapping: Mapping[str, str] | None = None) -> SMTPSettings:
        values = os.environ if mapping is None else mapping
        mode = values.get("AUTH_SMTP_MODE", "starttls")
        demo = values.get("AUTH_MAIL_DEMO", "false")
        if demo not in ("true", "false"):
            raise ValueError("AUTH_MAIL_DEMO must be true or false")
        raw_port = values.get("AUTH_SMTP_PORT", "465" if mode == "tls" else "587")
        raw_timeout = values.get("AUTH_SMTP_TIMEOUT_SECONDS", "10")
        if (
            not raw_port.isascii()
            or not raw_port.isdecimal()
            or not raw_timeout.isascii()
            or not raw_timeout.isdecimal()
        ):
            raise ValueError("SMTP port and timeout must be positive decimal integers")
        return cls(
            host=values.get("AUTH_SMTP_HOST", ""),
            port=int(raw_port),
            mode=mode,
            from_address=values.get("AUTH_SMTP_FROM", ""),
            public_origin=values.get("AUTH_MAIL_PUBLIC_ORIGIN", ""),
            username=values.get("AUTH_SMTP_USERNAME"),
            password=values.get("AUTH_SMTP_PASSWORD"),
            ca_file=values.get("AUTH_SMTP_CA_FILE"),
            timeout_seconds=int(raw_timeout),
            demo=demo == "true",
        )


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host(value: str) -> None:
    try:
        ipaddress.ip_address(value)
        return
    except ValueError:
        pass
    encoded = value.encode("idna").decode("ascii")
    if (
        not encoded
        or len(encoded) > 253
        or not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in encoded.removesuffix(".").split(".")
        )
    ):
        raise ValueError("Invalid SMTP hostname")


def _address(value: str, *, ascii_only: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value.encode("utf-8")) <= 254
        or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        or value.count("@") != 1
        or ascii_only
        and not value.isascii()
    ):
        raise ValueError("Invalid bare mailbox")
    header = SMTPUTF8.header_factory("To", value)
    if len(header.addresses) != 1 or any(
        not isinstance(defect, NonASCIILocalPartDefect) for defect in header.defects
    ):
        raise ValueError("Invalid bare mailbox")
    parsed = header.addresses[0]
    if (
        parsed.display_name
        or not parsed.username
        or not parsed.domain
        or parsed.addr_spec != value
    ):
        raise ValueError("Invalid bare mailbox")
    # Sender's domain also forms a stable RFC Message-ID domain.
    if ascii_only and not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", parsed.domain
    ):
        raise ValueError("Invalid sender domain")
    return value


def _render(settings: SMTPSettings, delivery: DeliveryMessage) -> EmailMessage:
    invalid = False
    try:
        if str(UUID(delivery.delivery_id)) != delivery.delivery_id:
            raise ValueError
        if delivery.kind not in ("verify", "reset") or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", delivery.token
        ):
            raise ValueError
        if (
            delivery.expires_at.tzinfo is None
            or delivery.expires_at.utcoffset() is None
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        invalid = True
    if invalid:
        raise DeliveryError("INVALID_MESSAGE", False) from None
    invalid = False
    try:
        recipient = _address(delivery.recipient)
    except (ValueError, UnicodeError, HeaderParseError):
        invalid = True
    if invalid:
        raise DeliveryError("INVALID_RECIPIENT", False) from None
    route = "/verify-email" if delivery.kind == "verify" else "/reset-password"
    link = settings.public_origin + route + "#" + urlencode({"token": delivery.token})
    title = "이메일 확인" if delivery.kind == "verify" else "비밀번호 재설정"
    expiry = delivery.expires_at.astimezone(UTC).isoformat()
    message = EmailMessage(policy=SMTP)
    message["From"] = settings.from_address
    message["To"] = recipient
    message["Subject"] = f"Feature Standards · {title}"
    message["Message-ID"] = (
        f"<feature-standards.{delivery.delivery_id}@{settings.from_address.rsplit('@', 1)[1]}>"
    )
    message["Date"] = format_datetime(datetime.now(UTC))
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(
        f"{title} 요청을 받았습니다.\n아래 링크에서 직접 진행해 주세요.\n\n{link}\n\n"
        f"유효 기한 (UTC): {expiry}\n요청하지 않았다면 이 메일을 무시해 주세요.\n"
    )
    message.add_alternative(
        f"<html><body><h1>{title}</h1><p>아래 링크에서 직접 진행해 주세요.</p>"
        f'<p><a href="{html.escape(link, quote=True)}">{title}</a></p>'
        f"<p>유효 기한 (UTC): {html.escape(expiry)}</p>"
        "<p>요청하지 않았다면 이 메일을 무시해 주세요.</p></body></html>",
        subtype="html",
    )
    return message


def _response_failure(code: int) -> DeliveryError:
    if 500 <= code < 600:
        return DeliveryError("SMTP_PERMANENT", False)
    return DeliveryError(
        "SMTP_TEMPORARY" if 400 <= code < 500 else "SMTP_NETWORK", True
    )


def _failure(error: Exception) -> DeliveryError:
    if isinstance(error, DeliveryError):
        return error
    if isinstance(error, ssl.SSLError):
        return DeliveryError("SMTP_TLS", True)
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return DeliveryError("SMTP_AUTH", True)
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return _response_failure(next(iter(error.recipients.values()))[0])
    if isinstance(error, smtplib.SMTPResponseException):
        return _response_failure(error.smtp_code)
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return DeliveryError("SMTP_PERMANENT", False)
    if isinstance(error, (OSError, smtplib.SMTPException)):
        return DeliveryError("SMTP_NETWORK", True)
    return DeliveryError("INVALID_MESSAGE", False)


class SMTPTransport:
    def __init__(self, settings: SMTPSettings):
        self.settings = settings

    def send(self, message: DeliveryMessage) -> None:
        rendered = _render(self.settings, message)
        connection = None
        failure = None
        accepted = False
        try:
            context = None
            if self.settings.mode != "plain-local":
                context = ssl.create_default_context(cafile=self.settings.ca_file)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.keylog_filename = None
            common = {
                "timeout": self.settings.timeout_seconds,
                "local_hostname": "feature-standards.invalid",
            }
            connection = (
                smtplib.SMTP_SSL(
                    host=self.settings.host,
                    port=self.settings.port,
                    context=context,
                    **common,
                )
                if self.settings.mode == "tls"
                else smtplib.SMTP(
                    host=self.settings.host, port=self.settings.port, **common
                )
            )
            code, diagnostic = connection.ehlo()
            if code != 250:
                raise smtplib.SMTPHeloError(code, diagnostic)
            if self.settings.mode == "starttls":
                if not connection.has_extn("starttls"):
                    raise DeliveryError("SMTP_TLS", True)
                connection.starttls(context=context)
                code, diagnostic = connection.ehlo()
                if code != 250:
                    raise smtplib.SMTPHeloError(code, diagnostic)
            if self.settings.username is not None:
                if not connection.has_extn("auth"):
                    raise DeliveryError("SMTP_AUTH", True)
                connection.login(self.settings.username, self.settings.password)
            if not message.recipient.isascii() and not connection.has_extn("smtputf8"):
                raise DeliveryError("SMTP_UTF8_UNSUPPORTED", False)
            refused = connection.send_message(
                rendered,
                from_addr=self.settings.from_address,
                to_addrs=[message.recipient],
            )
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
            accepted = True
        except (
            OSError,
            ValueError,
            TypeError,
            smtplib.SMTPException,
            DeliveryError,
        ) as error:
            failure = _failure(error)
        finally:
            if connection is not None:
                # A QUIT failure cannot revoke a previously observed DATA acknowledgement.
                if accepted:
                    try:
                        connection.quit()
                    except (OSError, smtplib.SMTPException):
                        pass
                try:
                    connection.close()
                except (OSError, smtplib.SMTPException):
                    pass
        if failure is not None:
            raise failure from None
