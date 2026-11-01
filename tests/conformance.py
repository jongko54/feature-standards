#!/usr/bin/env python3
"""One black-box HTTP suite for every implementation. No third-party test deps."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:5173"
EMAIL = "demo@example.com"
PASSWORD = "correct-horse-battery-staple"


class Client:
    def __init__(self, base_url: str):
        self.url = urlsplit(base_url)
        self.cookie = ""

    def request(self, method, path, body=None, *, headers=None, origin=True):
        outgoing = {"Origin": ORIGIN} if origin else {}
        if self.cookie:
            outgoing["Cookie"] = self.cookie
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            outgoing["Content-Type"] = "application/json"
        outgoing.update(headers or {})
        conn = http.client.HTTPConnection(self.url.hostname, self.url.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=outgoing)
            response = conn.getresponse()
            payload = response.read()
            result = (
                response.status,
                {k.lower(): v for k, v in response.getheaders()},
                payload,
            )
            cookie = result[1].get("set-cookie")
            if cookie:
                parsed = SimpleCookie()
                parsed.load(cookie)
                if "fs_session" in parsed:
                    value = parsed["fs_session"].value
                    self.cookie = f"fs_session={value}" if value else ""
            return result
        finally:
            conn.close()

    def login(self, **overrides):
        return self.request(
            "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD, **overrides}
        )


class AuthContract(unittest.TestCase):
    base_url = ""
    ttl = 3
    rate_max = 3
    rate_window = 3

    def setUp(self):
        self.client = Client(self.base_url)
        self.login_response = self.client.login()
        self.assertEqual(self.login_response[0], 200, self.login_response)
        self.session = json.loads(self.login_response[2])

    def assert_error(self, response, status, code):
        actual, headers, body = response
        self.assertEqual(actual, status, body)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], code)
        self.assertIsInstance(data["error"]["message"], str)
        self.assertNotIn(PASSWORD, body.decode())
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    def test_01_login_user_shape_and_cache(self):
        status, headers, _ = self.login_response
        self.assertEqual(status, 200)
        self.assertEqual(self.session["user"], {"id": "demo-user", "email": EMAIL})
        self.assertGreaterEqual(len(self.session["csrfToken"]), 43)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    def test_02_cookie_policy(self):
        cookie = SimpleCookie()
        cookie.load(self.login_response[1]["set-cookie"])
        session = cookie["fs_session"]
        self.assertTrue(session["httponly"])
        self.assertEqual(session["samesite"].lower(), "lax")
        self.assertEqual(session["path"], "/")
        self.assertFalse(session["domain"])
        self.assertFalse(session["secure"], "local demo explicitly disables Secure")
        self.assertGreaterEqual(len(session.value), 43)
        self.assertGreater(int(session["max-age"]), 0)
        self.assertLessEqual(int(session["max-age"]), self.ttl)

    def test_03_me_and_forged_session(self):
        response = self.client.request("GET", "/auth/me")
        self.assertEqual(response[0], 200)
        self.assertEqual(json.loads(response[2]), self.session)
        anonymous = Client(self.base_url)
        self.assert_error(anonymous.request("GET", "/auth/me"), 401, "UNAUTHENTICATED")
        anonymous.cookie = "fs_session=forged-token"
        self.assert_error(anonymous.request("GET", "/auth/me"), 401, "UNAUTHENTICATED")

    def test_04_email_normalization(self):
        response = self.client.login(email="  DEMO@EXAMPLE.COM  ")
        self.assertEqual(response[0], 200)
        self.assertEqual(json.loads(response[2])["user"]["email"], EMAIL)
        response = self.client.login(email="\t\r\nDEMO@EXAMPLE.COM\v\f ")
        self.assertEqual(response[0], 200)
        # Python str.strip treats U+001C as whitespace; the protocol deliberately does not.
        self.assert_error(
            self.client.login(email="\u001cDEMO@EXAMPLE.COM"),
            401,
            "INVALID_CREDENTIALS",
        )

    def test_05_generic_credentials_error(self):
        wrong_password = self.client.login(password="incorrect-password")
        unknown_user = self.client.login(email="missing@example.com")
        self.assert_error(wrong_password, 401, "INVALID_CREDENTIALS")
        self.assert_error(unknown_user, 401, "INVALID_CREDENTIALS")
        self.assertEqual(wrong_password[2], unknown_user[2])

    def test_06_origin_required_for_login(self):
        body = {"email": EMAIL, "password": PASSWORD}
        for headers, origin in [
            ({}, False),
            ({"Origin": "https://evil.example"}, True),
            ({"Origin": ORIGIN + ".evil.example"}, True),
            ({"Origin": "null"}, True),
        ]:
            with self.subTest(headers=headers, origin=origin):
                self.assert_error(
                    self.client.request(
                        "POST", "/auth/login", body, headers=headers, origin=origin
                    ),
                    403,
                    "ORIGIN_DENIED",
                )

    def test_07_strict_json(self):
        invalid = [
            b"{",
            b"null",
            b"[]",
            b'"string"',
            b'{"email":"demo@example.com","password":null}',
            b'{"email":12,"password":"abc"}',
            b'{"email":"demo@example.com","password":"abc","admin":true}',
            b'{"email":"first@example.com","email":"demo@example.com","password":"abc"}',
            b'{"email":"demo@example.com","password":"a","password":"b"}',
            b'{"email":"\xff@example.com","password":"abc"}',
            b"{}",
            b'{"email":"no-at-symbol","password":"abc"}',
        ]
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.request(
                    "POST",
                    "/auth/login",
                    body,
                    headers={"Content-Type": "application/json"},
                )
                self.assert_error(response, 400, "INVALID_REQUEST")
        for escaped in [b"\\ud800", b"\\udfff", b"\\ud800x", b"\\ud800\\ud800"]:
            with self.subTest(unpaired=escaped):
                body = b'{"email":"demo@example.com","password":"' + escaped + b'"}'
                self.assert_error(
                    self.client.request(
                        "POST",
                        "/auth/login",
                        body,
                        headers={"Content-Type": "application/json"},
                    ),
                    400,
                    "INVALID_REQUEST",
                )

    def test_08_content_type_and_size(self):
        self.assert_error(
            self.client.request("POST", "/auth/login", b"{}"),
            415,
            "UNSUPPORTED_MEDIA_TYPE",
        )
        self.assert_error(
            self.client.request(
                "POST",
                "/auth/login",
                b"x" * 4097,
                headers={"Content-Type": "application/json"},
            ),
            413,
            "REQUEST_TOO_LARGE",
        )
        body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
        response = self.client.request(
            "POST",
            "/auth/login",
            body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(response[0], 200)

    def test_09_utf8_field_limits(self):
        for body in [
            {"email": "a" * 250 + "@x.io", "password": "a"},
            {"email": "한" * 84 + "@x.io", "password": "a"},
            {"email": EMAIL, "password": "a" * 1025},
            {"email": EMAIL, "password": "한" * 342},
            {"email": EMAIL, "password": ""},
        ]:
            with self.subTest(field=list(body)):
                self.assert_error(
                    self.client.request("POST", "/auth/login", body),
                    400,
                    "INVALID_REQUEST",
                )

    def test_10_password_is_not_trimmed(self):
        self.assert_error(
            self.client.login(password=PASSWORD + " "), 401, "INVALID_CREDENTIALS"
        )

    def test_11_session_rotation_revokes_previous_cookie(self):
        previous = self.client.cookie
        previous_csrf = self.session["csrfToken"]
        response = self.client.login()
        self.assertEqual(response[0], 200)
        self.assertNotEqual(previous, self.client.cookie)
        self.assertNotEqual(previous_csrf, json.loads(response[2])["csrfToken"])
        copied = Client(self.base_url)
        copied.cookie = previous
        self.assert_error(copied.request("GET", "/auth/me"), 401, "UNAUTHENTICATED")

    def test_12_csrf_failure_preserves_session(self):
        for headers in [{}, {"X-CSRF-Token": "wrong-token"}]:
            self.assert_error(
                self.client.request("POST", "/auth/logout", headers=headers),
                403,
                "CSRF_INVALID",
            )
            self.assertEqual(self.client.request("GET", "/auth/me")[0], 200)

    def test_13_logout_origin_failure_preserves_session(self):
        response = self.client.request(
            "POST",
            "/auth/logout",
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": self.session["csrfToken"],
            },
        )
        self.assert_error(response, 403, "ORIGIN_DENIED")
        self.assertEqual(self.client.request("GET", "/auth/me")[0], 200)

    def test_14_logout_revokes_stolen_cookie_and_is_idempotent(self):
        previous = self.client.cookie
        response = self.client.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": self.session["csrfToken"]}
        )
        self.assertEqual(response[0], 204)
        self.assertEqual(response[2], b"")
        self.assertIn("Max-Age=0", response[1].get("set-cookie", ""))
        self.assertEqual(response[1].get("cache-control"), "no-store")
        copied = Client(self.base_url)
        copied.cookie = previous
        self.assert_error(copied.request("GET", "/auth/me"), 401, "UNAUTHENTICATED")
        self.assertEqual(copied.request("POST", "/auth/logout")[0], 204)
        self.assertEqual(self.client.request("POST", "/auth/logout")[0], 204)

    def test_15_logout_does_not_revoke_other_browser(self):
        other = Client(self.base_url)
        self.assertEqual(other.login()[0], 200)
        self.client.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": self.session["csrfToken"]}
        )
        self.assertEqual(other.request("GET", "/auth/me")[0], 200)

    def test_16_csrf_is_bound_to_session(self):
        other = Client(self.base_url)
        other_session = json.loads(other.login()[2])
        self.assert_error(
            self.client.request(
                "POST",
                "/auth/logout",
                headers={"X-CSRF-Token": other_session["csrfToken"]},
            ),
            403,
            "CSRF_INVALID",
        )

    def test_17_methods_and_paths(self):
        for method, path in [
            ("GET", "/auth/login"),
            ("GET", "/auth/logout"),
            ("POST", "/auth/me"),
            ("OPTIONS", "/auth/login"),
        ]:
            with self.subTest(method=method, path=path):
                self.assert_error(
                    self.client.request(method, path), 405, "METHOD_NOT_ALLOWED"
                )
        self.assert_error(self.client.request("GET", "/auth/missing"), 404, "NOT_FOUND")

    def test_18_absolute_expiry_is_not_extended_by_reads(self):
        time.sleep(self.ttl * 0.55)
        self.assertEqual(self.client.request("GET", "/auth/me")[0], 200)
        time.sleep(self.ttl * 0.55)
        self.assert_error(
            self.client.request("GET", "/auth/me"), 401, "UNAUTHENTICATED"
        )
        self.assertEqual(self.client.request("POST", "/auth/logout")[0], 204)

    def test_19_rate_limit_ignores_untrusted_forwarded_address(self):
        for i in range(self.rate_max):
            response = self.client.request(
                "POST",
                "/auth/login",
                {"email": EMAIL, "password": "wrong"},
                headers={"X-Forwarded-For": f"198.51.100.{i + 1}"},
            )
            self.assert_error(response, 401, "INVALID_CREDENTIALS")
        response = self.client.login()
        self.assert_error(response, 429, "RATE_LIMITED")
        self.assertGreater(int(response[1].get("retry-after", "0")), 0)
        time.sleep(self.rate_window + 0.2)
        self.assertEqual(self.client.login()[0], 200)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)


@contextlib.contextmanager
def server(backend, *, ttl=3, rate_window=3, secure=False):
    """Launch task-owned processes only, on an ephemeral loopback port."""
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="feature-standards-") as temp:
        env = os.environ.copy()
        env.update(
            AUTH_HOST="127.0.0.1",
            AUTH_PORT=str(port),
            AUTH_DEMO="true",
            AUTH_COOKIE_SECURE=str(secure).lower(),
            AUTH_ALLOWED_ORIGIN=ORIGIN,
            AUTH_SESSION_TTL_SECONDS=str(ttl),
            AUTH_RATE_LIMIT_MAX="3",
            AUTH_RATE_LIMIT_WINDOW_SECONDS=str(rate_window),
        )
        if backend == "python":
            workdir = ROOT / "implementations/python-fastapi"
            command = [
                "uv",
                "run",
                "--frozen",
                "uvicorn",
                "app:app",
                "--no-proxy-headers",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        else:
            workdir = ROOT / "implementations/go-net-http"
            executable = str(Path(temp) / "auth-server")
            subprocess.run(
                ["go", "build", "-o", executable, "."], cwd=workdir, env=env, check=True
            )
            command = [executable]
        with open(Path(temp) / "server.log", "w+") as log:
            process = subprocess.Popen(
                command,
                cwd=workdir,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        if Client(base).request("GET", "/healthz")[0] == 200:
                            yield base
                            return
                    except (OSError, http.client.HTTPException):
                        pass
                    time.sleep(0.1)
                log.seek(0)
                raise RuntimeError(f"{backend} failed to start:\n{log.read()[-5000:]}")
            finally:
                stop(process)


def run_contract(base):
    AuthContract.base_url = base
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AuthContract)
    )
    return result.wasSuccessful()


def run_secure_cookie_check(backend):
    with server(backend, secure=True) as base:
        response = Client(base).login()
        assert response[0] == 200, response
        cookie = SimpleCookie()
        cookie.load(response[1]["set-cookie"])
        assert cookie["fs_session"]["secure"], "Secure attribute missing when enabled"
        print(f"[{backend}] Secure cookie check: PASS", flush=True)


def require_free_port(port):
    with socket.socket() as probe:
        # A just-closed Vite connection can remain in TIME_WAIT. Match server
        # socket reuse semantics while still rejecting a live listening socket.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"Browser tests need a free loopback port {port}") from exc


def run_browser(backend):
    # Refuse to reuse somebody else's dev server and accidentally test the wrong backend.
    require_free_port(5173)
    with server(backend, ttl=1800, rate_window=60) as base:
        env = os.environ.copy()
        env.update(AUTH_API_TARGET=base, BASE_URL=ORIGIN)
        with tempfile.TemporaryFile(mode="w+") as log:
            process = subprocess.Popen(
                [
                    "npm",
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5173",
                    "--strictPort",
                ],
                cwd=ROOT / "clients/react",
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        if Client(ORIGIN).request("GET", "/healthz")[0] == 200:
                            subprocess.run(
                                ["npm", "run", "test:e2e"],
                                cwd=ROOT / "clients/react",
                                env=env,
                                check=True,
                            )
                            return
                    except (OSError, http.client.HTTPException):
                        pass
                    time.sleep(0.1)
                log.seek(0)
                raise RuntimeError(f"Vite failed to start:\n{log.read()[-3000:]}")
            finally:
                stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["python", "go", "all"], default="all")
    parser.add_argument(
        "--base-url",
        help="Test a separately started server with demo fixture, TTL=3 and rate max/window=3",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Also run React Playwright against each backend (port 5173 must be free)",
    )
    args = parser.parse_args()
    if args.base_url and args.browser:
        parser.error(
            "--base-url runs API tests only; run the target app's browser tests separately"
        )
    if args.base_url:
        return 0 if run_contract(args.base_url) else 1
    passed = True
    for backend in ["python", "go"] if args.backend == "all" else [args.backend]:
        print(f"\n=== {backend}: browser-session-v1 ===", flush=True)
        with server(backend) as base:
            passed = run_contract(base) and passed
        run_secure_cookie_check(backend)
        if args.browser:
            run_browser(backend)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
