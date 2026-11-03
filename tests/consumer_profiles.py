#!/usr/bin/env python3
"""Run independent package consumers against isolated PostgreSQL v2/v3 databases."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from conformance import PASSWORD, Client, free_port, require_free_port, stop
from pg_support import assert_test_database, database
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "examples/consumer-python-react"
BACKENDS = ("python", "go", "java", "rust")
PROFILES = ("browser-session-v2", "browser-session-v3")
ORIGIN = "http://127.0.0.1:5175"
NEW_PASSWORD = "consumer-new-password-after-reset"
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate, migrate_accounts, seed_demo
from mail_capture import capture


def require(value: bool, label: str) -> None:
    if not value:
        raise RuntimeError(label)


def database_name(backend: str, profile: str) -> str:
    if backend not in BACKENDS or profile not in PROFILES:
        raise ValueError("Unsupported consumer backend or profile")
    return f"feature_standards_test_consumer_{backend}_{profile[-2:]}_{uuid.uuid4().hex[:12]}"


def consumer_database_url(base: str, backend: str, profile: str) -> str:
    validated = assert_test_database(base)
    parts = urlsplit(validated)
    return assert_test_database(
        urlunsplit(parts._replace(path="/" + database_name(backend, profile)))
    )


@contextlib.contextmanager
def isolated_database(base: str, backend: str, profile: str):
    """Create a new random database; never reset a caller's existing schema."""
    url = consumer_database_url(base, backend, profile)
    name = urlsplit(url).path[1:]
    with psycopg.connect(assert_test_database(base), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        if profile == "browser-session-v3":
            migrate_accounts(url)
        else:
            migrate(url)
        seed_demo(url)
        yield url
    finally:
        with psycopg.connect(assert_test_database(base), autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


class ConsumerClient(Client):
    def request(self, method, path, body=None, *, headers=None, origin=True):
        outgoing = {"Origin": ORIGIN} if origin else {}
        outgoing.update(headers or {})
        return super().request(method, path, body, headers=outgoing, origin=False)


@contextlib.contextmanager
def process(command: list[str], cwd: Path, env: dict, base: str):
    require_free_port(urlsplit(base).port)
    with tempfile.TemporaryFile(mode="w+") as log:
        child = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    break
                try:
                    if (
                        ConsumerClient(base).request("GET", "/healthz", origin=False)[0]
                        == 200
                    ):
                        yield
                        return
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            # Runtime diagnostics may contain credentials or capabilities. Do not echo them.
            raise RuntimeError("Consumer or frontend did not become ready")
        finally:
            stop(child)


class Builds:
    def __init__(self, temporary: Path):
        self.temporary = temporary
        self.cache: dict[str, tuple[Path, list[str]]] = {}

    def command(self, backend: str) -> tuple[Path, list[str]]:
        if backend in self.cache:
            return self.cache[backend]
        directory = ROOT / f"examples/consumer-{backend}"
        if backend == "python":
            directory = FRONTEND
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
            ]
        elif backend == "go":
            binary = self.temporary / "consumer-go"
            subprocess.run(
                ["go", "build", "-o", str(binary), "."], cwd=directory, check=True
            )
            command = [str(binary)]
        elif backend == "java":
            wrapper = ROOT / "implementations/java-spring/mvnw"
            subprocess.run(
                [
                    str(wrapper),
                    "-q",
                    "-f",
                    str(ROOT / "implementations/java-spring/pom.xml"),
                    "-DskipTests",
                    "install",
                ],
                check=True,
            )
            subprocess.run(
                [
                    str(wrapper),
                    "-q",
                    "-f",
                    str(directory / "pom.xml"),
                    "-DskipTests",
                    "package",
                ],
                check=True,
            )
            home = os.environ.get("JAVA_HOME")
            java = str(Path(home) / "bin/java") if home else "java"
            command = [java, "-jar", str(directory / "target/consumer-java.jar")]
        elif backend == "rust":
            result = subprocess.run(
                [
                    "cargo",
                    "build",
                    "--locked",
                    "--message-format=json-render-diagnostics",
                ],
                cwd=directory,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            )
            artifacts = []
            for line in result.stdout.splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if (
                    item.get("reason") == "compiler-artifact"
                    and item.get("executable")
                    and item.get("target", {}).get("name")
                    == "feature-standards-consumer-rust"
                ):
                    artifacts.append(item["executable"])
            require(
                len(artifacts) == 1, "Missing or ambiguous Rust consumer executable"
            )
            command = artifacts
        else:
            raise ValueError("Unsupported consumer backend")
        self.cache[backend] = directory, command
        return directory, command


def expect(response, status: int, label: str):
    require(response[0] == status, label)
    return response


def profile(client: ConsumerClient, expected_id: str, label: str) -> None:
    response = expect(client.request("GET", "/api/profile"), 200, label)
    user = json.loads(response[2]).get("user", {})
    require(user.get("id") == expected_id, label)
    require(response[1].get("cache-control") == "no-store", label)


def session_checks(base: str) -> str:
    anonymous = ConsumerClient(base)
    expect(anonymous.request("GET", "/api/profile"), 401, "Anonymous protected access")
    forged = ConsumerClient(base)
    forged.cookie = "fs_session=forged-consumer-cookie"
    expect(forged.request("GET", "/api/profile"), 401, "Forged protected access")
    first, second = ConsumerClient(base), ConsumerClient(base)
    one = json.loads(expect(first.login(), 200, "First consumer login")[2])
    two = json.loads(expect(second.login(), 200, "Second consumer login")[2])
    require(
        first.cookie != second.cookie and one["csrfToken"] != two["csrfToken"],
        "Independent consumer sessions",
    )
    profile(first, "demo-user", "First protected identity")
    profile(second, "demo-user", "Second protected identity")
    expect(
        first.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": two["csrfToken"]}
        ),
        403,
        "Cross-session CSRF",
    )
    profile(first, "demo-user", "CSRF rejection preserves session")
    stolen = ConsumerClient(base)
    stolen.cookie = first.cookie
    expect(
        first.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": one["csrfToken"]}
        ),
        204,
        "Consumer logout",
    )
    expect(stolen.request("GET", "/api/profile"), 401, "Copied cookie after logout")
    profile(second, "demo-user", "Logout preserves independent session")
    other = ConsumerClient(base)
    expect(
        other.login(email="other@example.com", password="other-correct-horse-password"),
        200,
        "Other consumer login",
    )
    profile(other, "other-user", "Other consumer identity")
    return second.cookie


def captured_token(url: str, directory: Path, email: str, kind: str) -> str:
    output = directory / (uuid.uuid4().hex + ".jsonl")
    capture(url, output, "http://127.0.0.1:5173")
    from urllib.parse import parse_qs

    for line in output.read_text().splitlines():
        message = json.loads(line)
        if message["recipient"] == email and message["kind"] == kind:
            return parse_qs(urlsplit(message["url"]).fragment)["token"][0]
    raise RuntimeError("Expected private local capture message")


def account_checks(base: str, url: str, directory: Path, backend: str) -> None:
    client = ConsumerClient(base)
    email = f"consumer-{backend}@example.com"
    expect(
        client.request(
            "POST", "/auth/register", {"email": email, "password": PASSWORD}
        ),
        202,
        "Consumer registration",
    )
    expect(client.login(email=email), 401, "Unverified consumer login")
    token = captured_token(url, directory, email, "verify")
    expect(
        client.request("POST", "/auth/email-verification/confirm", {"token": token}),
        204,
        "Consumer verification",
    )
    expect(client.login(email=email), 200, "Verified consumer login")
    user = json.loads(
        expect(client.request("GET", "/api/profile"), 200, "Verified protected access")[
            2
        ]
    )["user"]
    require(user["email"] == email, "Verified consumer identity")
    stolen = ConsumerClient(base)
    stolen.cookie = client.cookie
    expect(
        client.request("POST", "/auth/password-reset/request", {"email": email}),
        202,
        "Consumer reset request",
    )
    token = captured_token(url, directory, email, "reset")
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE feature_auth.users SET admin_enabled=false WHERE email=%s", (email,)
        )
    expect(
        client.request(
            "POST",
            "/auth/password-reset/confirm",
            {"token": token, "password": NEW_PASSWORD},
        ),
        400,
        "Reset preserves administrator disable",
    )
    with psycopg.connect(url) as conn:
        allowed = conn.execute(
            "SELECT admin_enabled FROM feature_auth.users WHERE email=%s", (email,)
        ).fetchone()[0]
        require(allowed is False, "Reset preserves administrator disable")
        conn.execute(
            "UPDATE feature_auth.users SET admin_enabled=true WHERE email=%s", (email,)
        )
    expect(
        client.request(
            "POST",
            "/auth/password-reset/confirm",
            {"token": token, "password": NEW_PASSWORD},
        ),
        204,
        "Consumer reset confirmation",
    )
    expect(
        stolen.request("GET", "/api/profile"),
        401,
        "Reset rejects copied consumer session",
    )
    expect(client.login(email=email), 401, "Reset rejects old consumer password")
    expect(
        client.login(email=email, password=NEW_PASSWORD),
        200,
        "Reset accepts new consumer password",
    )
    # Administrator controls remain effective through the consumer integration.
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE feature_auth.users SET admin_enabled=false WHERE email=%s", (email,)
        )
    expect(
        client.request("GET", "/api/profile"),
        401,
        "Administrator disable rejects consumer session",
    )
    expect(
        client.login(email=email, password=NEW_PASSWORD),
        401,
        "Administrator disable rejects consumer login",
    )
    expect(
        client.request("POST", "/auth/email-verification/confirm", {"token": token}),
        400,
        "Invalid verification does not enable user",
    )
    with psycopg.connect(url) as conn:
        allowed = conn.execute(
            "SELECT admin_enabled FROM feature_auth.users WHERE email=%s", (email,)
        ).fetchone()[0]
    require(allowed is False, "Account operation preserves administrator disable")


def run_browser(env: dict) -> None:
    result = subprocess.run(
        ["npx", "playwright", "test", "--config", "playwright.profiles.config.ts"],
        cwd=FRONTEND,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    # Playwright driver errors can include request headers and navigation URLs.
    # Redact capabilities even for the reused legacy consumer scenarios.
    output = re.sub(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])",
        "[REDACTED_CAPABILITY]",
        result.stdout,
    )
    print(output, end="", flush=True)
    require(result.returncode == 0, "Consumer browser scenarios")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("all", *BACKENDS), default="all")
    parser.add_argument("--profile", choices=("all", *PROFILES), default="all")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    backends = BACKENDS if args.backend == "all" else (args.backend,)
    profiles = PROFILES if args.profile == "all" else (args.profile,)
    try:
        with tempfile.TemporaryDirectory(prefix="fs-consumers-") as temporary:
            builds = Builds(Path(temporary))
            commands = {backend: builds.command(backend) for backend in backends}
            with database() as base_url:
                for backend in backends:
                    directory, base_command = commands[backend]
                    for selected in profiles:
                        with isolated_database(base_url, backend, selected) as url:
                            port = free_port()
                            base = f"http://127.0.0.1:{port}"
                            env = os.environ.copy()
                            env.update(
                                AUTH_STORE="postgres",
                                AUTH_DATABASE_URL=url,
                                AUTH_ACCOUNT_LIFECYCLE="true"
                                if selected.endswith("v3")
                                else "false",
                                AUTH_HOST="127.0.0.1",
                                AUTH_PORT=str(port),
                                AUTH_DEMO="true",
                                AUTH_COOKIE_SECURE="false",
                                AUTH_ALLOWED_ORIGIN=ORIGIN,
                                AUTH_SESSION_TTL_SECONDS="1800",
                                AUTH_RATE_LIMIT_MAX="20",
                                AUTH_RATE_LIMIT_WINDOW_SECONDS="60",
                                AUTH_API_TARGET=base,
                                BASE_URL=ORIGIN,
                                VITE_AUTH_ACCOUNT_LIFECYCLE="true"
                                if selected.endswith("v3")
                                else "false",
                                CONSUMER_BACKEND=backend,
                                CONSUMER_PROFILE=selected,
                                CONSUMER_ROOT=str(ROOT),
                                CONSUMER_CAPTURE_DIR=temporary,
                                FEATURE_STANDARDS_TEST_DATABASE_URL=url,
                            )
                            command = (
                                [*base_command, str(port)]
                                if backend == "python"
                                else base_command
                            )
                            with process(command, directory, env, base):
                                health = ConsumerClient(base).request(
                                    "GET", "/healthz", origin=False
                                )
                                require(
                                    json.loads(health[2]).get("profile") == selected,
                                    "Consumer selected PostgreSQL profile",
                                )
                                if selected.endswith("v2"):
                                    expect(
                                        ConsumerClient(base).request(
                                            "POST",
                                            "/auth/register",
                                            {
                                                "email": "unused@example.com",
                                                "password": PASSWORD,
                                            },
                                        ),
                                        404,
                                        "Account lifecycle stays disabled in v2",
                                    )
                                cookie = session_checks(base)
                                if selected.endswith("v3"):
                                    account_checks(base, url, Path(temporary), backend)
                            with process(command, directory, env, base):
                                retained = ConsumerClient(base)
                                retained.cookie = cookie
                                profile(
                                    retained,
                                    "demo-user",
                                    "Consumer restart persistence",
                                )
                                if args.browser:
                                    frontend = [
                                        "npm",
                                        "run",
                                        "dev",
                                        "--",
                                        "--port",
                                        "5175",
                                    ]
                                    with process(frontend, FRONTEND, env, ORIGIN):
                                        run_browser(env)
                            print(
                                f"[{backend}/{selected}] consumer HTTP, storage and restart: PASS",
                                flush=True,
                            )
        print("Independent PostgreSQL consumers: PASS", flush=True)
        return 0
    except RuntimeError as error:
        print(f"Independent consumer validation failed: {error}", file=sys.stderr)
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        psycopg.Error,
        subprocess.SubprocessError,
    ):
        print(
            "Independent consumer validation failed; no connection details or capabilities are displayed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
