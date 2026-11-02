#!/usr/bin/env python3
"""Own two isolated PostgreSQL servers and verify Rust TLS trust boundaries."""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION = Path(__file__).resolve().parents[1]


def run(command, *, env=None, input=None):
    subprocess.run(
        command,
        env=env,
        input=input,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def binaries():
    explicit = os.environ.get("FEATURE_STANDARDS_TLS_PG_BIN")
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        if shutil.which("postgres"):
            candidates.append(Path(shutil.which("postgres")).parent)
        # Ubuntu's PostgreSQL server tools are deliberately not always on PATH.
        candidates.extend(
            sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
        )
    for directory in candidates:
        if all(
            (directory / name).is_file()
            for name in ("postgres", "initdb", "pg_ctl", "psql")
        ):
            return directory
    raise RuntimeError(
        "Provide FEATURE_STANDARDS_TLS_PG_BIN with SSL-enabled PostgreSQL server tools"
    )


def certificates(base):
    common = ["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256"]
    for name in ("root", "other-root"):
        run(
            [
                *common,
                "-x509",
                "-days",
                "2",
                "-subj",
                f"/CN=Feature Standards Test {name}",
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
            *common,
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
        "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n"
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
            "-days",
            "2",
            "-sha256",
            "-extfile",
            str(base / "extensions.cnf"),
            "-out",
            str(base / "server.pem"),
        ]
    )
    (base / "server.key").chmod(0o600)


@contextlib.contextmanager
def server(pg_bin, base, *, tls):
    port = free_port()
    data = base / ("tls-data" if tls else "plaintext-data")
    run(
        [
            str(pg_bin / "initdb"),
            "-D",
            str(data),
            "-A",
            "trust",
            "-U",
            "feature_test",
            "--encoding=UTF8",
            "--no-locale",
        ]
    )
    # Config only controls this new, task-owned data directory.
    with (data / "postgresql.conf").open("a") as config:
        config.write(
            f"\nlisten_addresses='127.0.0.1'\nport={port}\nunix_socket_directories='{base}'\n"
        )
        config.write("ssl=" + ("on\n" if tls else "off\n"))
        if tls:
            config.write(
                f"ssl_cert_file='{base / 'server.pem'}'\nssl_key_file='{base / 'server.key'}'\n"
            )
    control = [str(pg_bin / "pg_ctl"), "-D", str(data)]
    try:
        run(
            [
                *control,
                "-l",
                str(base / f"{'tls' if tls else 'plaintext'}.log"),
                "-w",
                "start",
            ]
        )
        admin = f"postgresql://feature_test@127.0.0.1:{port}/postgres?sslmode=disable"
        run(
            [
                str(pg_bin / "psql"),
                admin,
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "CREATE DATABASE feature_standards_test_tls",
            ]
        )
        database = f"postgresql://feature_test@127.0.0.1:{port}/feature_standards_test_tls?sslmode=disable"
        run(
            [
                str(pg_bin / "psql"),
                database,
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(ROOT / "features/auth/postgres/001_initial.sql"),
            ]
        )
        yield port
    finally:
        if (data / "postmaster.pid").exists():
            run([*control, "-m", "fast", "-w", "stop"])


def main():
    if any(name.startswith("PG") and value for name, value in os.environ.items()):
        raise ValueError("Clear PG* environment before creating isolated TLS fixtures")
    pg_bin = binaries()
    with tempfile.TemporaryDirectory(
        prefix="fs-rust-tls-",
        dir="/private/tmp" if Path("/private/tmp").exists() else None,
    ) as directory:
        base = Path(directory)
        certificates(base)
        with (
            server(pg_bin, base, tls=True) as tls_port,
            server(pg_bin, base, tls=False) as plaintext_port,
        ):

            def uri(host, port, root):
                return (
                    f"postgresql://feature_test@{host}:{port}/feature_standards_test_tls?"
                    + urlencode(
                        {"sslmode": "verify-full", "sslrootcert": str(base / root)}
                    )
                )

            env = os.environ.copy()
            env.update(
                AUTH_TLS_TEST_GOOD_URL=uri("localhost", tls_port, "root.pem"),
                AUTH_TLS_TEST_WRONG_CA_URL=uri("localhost", tls_port, "other-root.pem"),
                AUTH_TLS_TEST_WRONG_HOST_URL=uri("127.0.0.1", tls_port, "root.pem"),
                AUTH_TLS_TEST_PLAINTEXT_URL=uri(
                    "localhost", plaintext_port, "root.pem"
                ),
            )
            subprocess.run(
                [
                    "cargo",
                    "test",
                    "--locked",
                    "postgres_tls_certificate_boundaries",
                    "--",
                    "--ignored",
                ],
                cwd=IMPLEMENTATION,
                env=env,
                check=True,
            )
    print(
        "Rust PostgreSQL TLS: trusted/encrypted PASS; wrong CA/hostname/plaintext refused PASS"
    )


if __name__ == "__main__":
    main()
