"""Explicit PostgreSQL migration/demo tools. Connection details stay in the environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parents[1]
DEMO_USERS = (
    ("demo-user", "demo@example.com", "correct-horse-battery-staple"),
    ("other-user", "other@example.com", "other-correct-horse-password"),
)


def connect(url: str):
    return psycopg.connect(url, connect_timeout=3)


def migrate(url: str) -> None:
    with connect(url) as conn:
        exists = conn.execute(
            "SELECT to_regclass('feature_auth.schema_version')"
        ).fetchone()[0]
        if exists and conn.execute(
            "SELECT version FROM feature_auth.schema_version"
        ).fetchall() != [(1,)]:
            raise ValueError("Unsupported schema version")
    # The checked-in migration owns its transaction and is idempotent.
    with psycopg.connect(url, autocommit=True, connect_timeout=3) as conn:
        conn.execute((ROOT / "features/auth/postgres/001_initial.sql").read_text())


def seed_demo(url: str) -> None:
    hasher = PasswordHasher(
        time_cost=3, memory_cost=65536, parallelism=4, salt_len=16, hash_len=32
    )
    with connect(url) as conn:
        if conn.execute(
            "SELECT version FROM feature_auth.schema_version"
        ).fetchall() != [(1,)]:
            raise ValueError("Unsupported schema version")
        for user_id, email, password in DEMO_USERS:
            conn.execute(
                "INSERT INTO feature_auth.users(id,email,password_hash) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (user_id, email, hasher.hash(password)),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["migrate", "seed-demo", "status"])
    parser.add_argument(
        "--confirm-demo",
        action="store_true",
        help="Explicitly allow public demo fixtures",
    )
    args = parser.parse_args()
    url = os.environ.get("AUTH_DATABASE_URL", "")
    if not url:
        parser.error("AUTH_DATABASE_URL is required")
    if args.command == "seed-demo" and not args.confirm_demo:
        parser.error(
            "seed-demo requires --confirm-demo; it never overwrites existing accounts"
        )
    try:
        if args.command == "migrate":
            migrate(url)
            print("PostgreSQL auth schema version 1 is ready.")
        elif args.command == "seed-demo":
            seed_demo(url)
            print("Public demo fixtures ensured; existing accounts unchanged.")
        else:
            with connect(url) as conn:
                version = conn.execute(
                    "SELECT version FROM feature_auth.schema_version"
                ).fetchall()
                print(
                    f"Schema version: {version[0][0] if len(version) == 1 else 'invalid'}"
                )
    except (psycopg.Error, ValueError, OSError):
        print("Database operation failed; connection details are not displayed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
