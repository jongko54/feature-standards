"""Task-owned SMTP wire fixture. Payloads remain in memory and are never logged."""

from __future__ import annotations

import contextlib
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Certificates:
    root: Path
    other_root: Path
    certificate: Path
    key: Path


@contextlib.contextmanager
def certificates():
    with tempfile.TemporaryDirectory(prefix="fs-smtp-certs-") as directory:
        base = Path(directory)

        def run(args):
            subprocess.run(
                args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

        for name in ("root", "other-root"):
            run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-sha256",
                    "-days",
                    "2",
                    "-subj",
                    f"/CN=Feature Standards SMTP {name}",
                    "-keyout",
                    str(base / f"{name}.key"),
                    "-out",
                    str(base / f"{name}.pem"),
                    "-addext",
                    "basicConstraints=critical,CA:TRUE",
                    "-addext",
                    "keyUsage=critical,keyCertSign,cRLSign",
                ]
            )
        run(
            [
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-subj",
                "/CN=localhost",
                "-keyout",
                str(base / "server.key"),
                "-out",
                str(base / "server.csr"),
            ]
        )
        (base / "extensions.cnf").write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
        )
        run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(base / "server.csr"),
                "-CA",
                str(base / "root.pem"),
                "-CAkey",
                str(base / "root.key"),
                "-CAcreateserial",
                "-out",
                str(base / "server.pem"),
                "-days",
                "2",
                "-sha256",
                "-extfile",
                str(base / "extensions.cnf"),
            ]
        )
        (base / "server.key").chmod(0o600)
        yield Certificates(
            base / "root.pem",
            base / "other-root.pem",
            base / "server.pem",
            base / "server.key",
        )


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        if self.fixture.mode == "tls":
            try:
                connection = self.fixture.context.wrap_socket(
                    connection, server_side=True
                )
            except OSError:
                connection.close()
                raise
        with self.fixture.lock:
            self.fixture.connections.add(connection)
        return connection, address

    def handle_error(self, request, client_address):
        # TLS-negative cases deliberately make the peer disconnect mid-handshake.
        return


class _Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.fixture = self.server.fixture
        self.encrypted = isinstance(self.request, ssl.SSLSocket)
        self.reader = self.request.makefile("rb")
        self.writer = self.request.makefile("wb")

    def reply(self, payload):
        self.writer.write(payload)
        self.writer.flush()

    def handle(self):
        self.reply(b"220 local-fixture ESMTP\r\n")
        while True:
            line = self.reader.readline(65537)
            if not line:
                return
            name = (
                line.split(b" ", 1)[0].strip().decode("ascii", errors="replace").upper()
            )
            self.fixture.commands.append(name)
            if name in ("EHLO", "HELO"):
                parts = [b"250-local-fixture\r\n"]
                if (
                    self.fixture.mode == "starttls"
                    and not self.encrypted
                    and self.fixture.advertise_starttls
                ):
                    parts.append(b"250-STARTTLS\r\n")
                if self.fixture.smtp_utf8:
                    parts.extend([b"250-SMTPUTF8\r\n", b"250-8BITMIME\r\n"])
                if self.fixture.auth:
                    parts.append(b"250-AUTH PLAIN\r\n")
                self.reply(b"".join(parts) + b"250 OK\r\n")
            elif name == "STARTTLS":
                if not self.fixture.advertise_starttls:
                    self.reply(b"454 unavailable\r\n")
                    continue
                self.reply(b"220 begin TLS\r\n")
                original = self.request
                self.reader.close()
                self.writer.close()
                self.request = self.fixture.context.wrap_socket(
                    original, server_side=True
                )
                with self.fixture.lock:
                    self.fixture.connections.discard(original)
                    self.fixture.connections.add(self.request)
                self.reader = self.request.makefile("rb")
                self.writer = self.request.makefile("wb")
                self.encrypted = True
            elif name == "AUTH":
                self.fixture.auth_encrypted.append(self.encrypted)
                self.reply(
                    f"{self.fixture.auth_code} fixture auth response\r\n".encode()
                )
            elif name == "MAIL":
                self.fixture.mail_options.append(
                    set(line.partition(b">")[2].decode("ascii").upper().split())
                )
                self.reply(
                    f"{self.fixture.mail_code} fixture sender response\r\n".encode()
                )
            elif name == "RCPT":
                self.reply(
                    f"{self.fixture.rcpt_code} fixture recipient response\r\n".encode()
                )
            elif name == "DATA":
                self.reply(b"354 end with dot\r\n")
                body = bytearray()
                while True:
                    data = self.reader.readline(65537)
                    if not data:
                        return
                    if data == b".\r\n":
                        break
                    body.extend(data[1:] if data.startswith(b"..") else data)
                with self.fixture.lock:
                    self.fixture.messages.append(bytes(body))
                    self.fixture.message_encrypted.append(self.encrypted)
                self.fixture.data_received.set()
                if self.fixture.ack_gate is not None:
                    self.fixture.ack_gate.wait(timeout=10)
                if self.fixture.drop_after_data:
                    return
                self.reply(
                    f"{self.fixture.data_code} fixture DATA response\r\n".encode()
                )
            elif name == "QUIT":
                self.reply(
                    f"{self.fixture.quit_code} fixture quit response\r\n".encode()
                )
                return
            elif name in ("RSET", "NOOP"):
                self.reply(b"250 OK\r\n")
            else:
                self.reply(b"500 unsupported fixture command\r\n")

    def finish(self):
        with self.fixture.lock:
            self.fixture.connections.discard(self.request)
        try:
            self.reader.close()
            self.writer.close()
        except OSError:
            pass
        self.request.close()


class SMTPFixture:
    """Context manager: .port, .messages(bytes), .commands(names), .data_received.

    TLS modes require a Certificates object. The listener always binds numeric
    loopback; passing localhost to a client tests certificate hostname validation.
    ack_gate can pause DATA acknowledgement for parent transaction-race tests.
    """

    def __init__(
        self,
        *,
        mode="plain",
        certs=None,
        advertise_starttls=True,
        smtp_utf8=True,
        auth=False,
        auth_code=235,
        mail_code=250,
        rcpt_code=250,
        data_code=250,
        drop_after_data=False,
        quit_code=221,
        ack_gate=None,
    ):
        self.mode = mode
        self.advertise_starttls = advertise_starttls
        self.smtp_utf8 = smtp_utf8
        self.auth = auth
        self.auth_code = auth_code
        self.mail_code = mail_code
        self.rcpt_code = rcpt_code
        self.data_code = data_code
        self.drop_after_data = drop_after_data
        self.quit_code = quit_code
        self.ack_gate = ack_gate
        self.lock = threading.Lock()
        self.connections = set()
        self.messages = []
        self.message_encrypted = []
        self.commands = []
        self.auth_encrypted = []
        self.mail_options = []
        self.data_received = threading.Event()
        self.context = None
        if mode not in ("plain", "starttls", "tls"):
            raise ValueError("Unsupported fixture mode")
        if mode != "plain":
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.context.load_cert_chain(certs.certificate, certs.key)
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.fixture = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        if self.ack_gate is not None:
            self.ack_gate.set()
        self.server.shutdown()
        with self.lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self.server.server_close()
        self.thread.join(timeout=3)
