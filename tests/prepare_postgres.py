"""Prepare isolated PostgreSQL fixtures explicitly, outside application startup."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from pg_support import assert_test_database
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_db import migrate, migrate_accounts, migrate_mail_delivery, seed_demo

LANGUAGES = ("python", "go", "java", "rust")
MAIL_DATABASES = ("worker", "capture", "integration")


def fixture_urls(raw_url: str, prefix: str) -> tuple[str, dict[str, str]]:
    base_url = assert_test_database(raw_url)
    if not re.fullmatch(r"feature_standards_test[A-Za-z0-9_]*", prefix):
        raise ValueError(
            "Fixture DB prefix must be an ASCII feature_standards_test name"
        )
    if len(prefix) + len("_mail_") + max(map(len, MAIL_DATABASES)) > 63:
        raise ValueError("Fixture database names must fit PostgreSQL's 63-byte limit")
    parts = urlsplit(base_url)
    targets = {
        language: assert_test_database(
            urlunsplit(parts._replace(path=f"/{prefix}_{language}"))
        )
        for language in LANGUAGES
    }
    return base_url, targets


def account_fixture_urls(base_url: str, prefix: str) -> dict[str, str]:
    parts = urlsplit(base_url)
    return {
        name: assert_test_database(
            urlunsplit(parts._replace(path=f"/{prefix}_v3_{name}"))
        )
        for name in (*LANGUAGES, "sql")
    }


def mail_fixture_urls(base_url: str, prefix: str) -> dict[str, str]:
    parts = urlsplit(base_url)
    return {
        name: assert_test_database(
            urlunsplit(parts._replace(path=f"/{prefix}_mail_{name}"))
        )
        for name in MAIL_DATABASES
    }


def prepare(raw_url: str, prefix: str) -> None:
    # Validate every target before the first connection or SQL statement.
    base_url, targets = fixture_urls(raw_url, prefix)
    account_targets = account_fixture_urls(base_url, prefix)
    mail_targets = mail_fixture_urls(base_url, prefix)
    with psycopg.connect(base_url, autocommit=True, connect_timeout=3) as conn:
        for url in (
            *targets.values(),
            *account_targets.values(),
            *mail_targets.values(),
        ):
            name = urlsplit(url).path[1:]
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
            ).fetchone()
            if not exists:
                try:
                    conn.execute(
                        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                    )
                except psycopg.errors.DuplicateDatabase:
                    # Another explicit preparation may have created the same fixture.
                    pass
    for url in (base_url, *targets.values()):
        migrate(url)
        seed_demo(url)
    for url in account_targets.values():
        migrate_accounts(url)
        seed_demo(url)
    for url in mail_targets.values():
        migrate_accounts(url)
        migrate_mail_delivery(url)
        seed_demo(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        default="feature_standards_test",
        help="Per-language fixture DB prefix; use feature_standards_test_ci_* for local checks",
    )
    args = parser.parse_args()
    url = os.environ.get("FEATURE_STANDARDS_TEST_DATABASE_URL", "")
    if not url:
        parser.error("FEATURE_STANDARDS_TEST_DATABASE_URL is required")
    try:
        prepare(url, args.prefix)
    except (psycopg.Error, ValueError):
        print(
            "PostgreSQL fixture preparation failed; connection details are not displayed."
        )
        return 1
    print("PostgreSQL v2/v3/mail schemas and fixtures are ready in isolated test DBs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
