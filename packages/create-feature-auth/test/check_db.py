"""Exercise private fixture cleanup on normal completion and protocol failure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import psycopg
from pg_support import assert_test_database
from psycopg import sql


def contents(url):
    with psycopg.connect(url, connect_timeout=3) as conn:
        return conn.execute(
            "SELECT n.nspname,c.relname,c.relkind FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
            "ORDER BY 1,2,3"
        ).fetchall()


def main():
    administrative = assert_test_database(
        os.environ.get("FEATURE_STANDARDS_TEST_DATABASE_URL", "")
    )
    # Seed a sentinel only in our own probe database, never the supplied base.
    probe = "feature_standards_test_fixture_probe_" + uuid.uuid4().hex[:12]
    base = assert_test_database(
        urlunsplit(urlsplit(administrative)._replace(path="/" + probe))
    )
    with psycopg.connect(administrative, autocommit=True, connect_timeout=3) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(probe)))
    try:
        verify_cleanup(base)
    finally:
        with psycopg.connect(
            administrative, autocommit=True, connect_timeout=3
        ) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(probe))
            )


def verify_cleanup(base):
    with psycopg.connect(base, connect_timeout=3) as conn:
        conn.execute("CREATE SCHEMA fixture_sentinel")
        conn.execute(
            "CREATE TABLE fixture_sentinel.records(id integer PRIMARY KEY, value text NOT NULL)"
        )
        conn.execute("INSERT INTO fixture_sentinel.records VALUES (1, 'preserve-me')")
    before = contents(base)
    count = 0
    for profile in ("browser-session-v2", "browser-session-v3"):
        for failed in (False, True):
            request = {"command": "unsupported"} if failed else {"command": "close"}
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "packages/create-feature-auth/src/check-db.py"),
                    str(ROOT),
                    "python",
                    profile,
                ],
                input=json.dumps(request) + "\n",
                env={**os.environ, "FEATURE_STANDARDS_TEST_DATABASE_URL": base},
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            assert len(messages) == 2 and messages[0].get("ready") is True, (
                "fixture setup failed"
            )
            name = urlsplit(assert_test_database(messages[0]["url"])).path[1:]
            assert name.startswith("feature_standards_test_generated_python_"), (
                "unexpected owned database name"
            )
            assert result.returncode == (1 if failed else 0), (
                "wrong fixture exit status"
            )
            assert messages[-1] == (
                {"error": "check-database-fixture-failed"}
                if failed
                else {"closed": True}
            ), "wrong fixture outcome"
            with psycopg.connect(base, connect_timeout=3) as conn:
                assert conn.execute(
                    "SELECT count(*) FROM pg_database WHERE datname=%s", (name,)
                ).fetchone() == (0,), "owned database was not dropped"
            assert contents(base) == before, "supplied database contents changed"
            with psycopg.connect(base, connect_timeout=3) as conn:
                assert conn.execute(
                    "SELECT id,value FROM fixture_sentinel.records ORDER BY id"
                ).fetchall() == [(1, "preserve-me")], "sentinel rows changed"
            count += 1
    print(
        json.dumps(
            {
                "privateFixtureCleanupChecks": count,
                "normalAndErrorPaths": True,
                "suppliedDatabaseContentsUnchanged": True,
                "sentinelRowsUnchanged": True,
                "probeDatabaseOwnedByTest": True,
            }
        )
    )


if __name__ == "__main__":
    main()
