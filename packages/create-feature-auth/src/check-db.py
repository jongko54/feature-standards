"""Private pipe protocol for task-owned generated-consumer database fixtures.

No connection details, passwords or capabilities are written to files or stderr.
The supplied base database is only an administrative connection; all DDL and demo
data belong to the fresh random database owned by this one process.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    if len(sys.argv) != 4:
        raise ValueError("invalid-fixture-arguments")
    source, stack, profile = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if stack not in {"python", "go", "java", "rust"} or profile not in {
        "browser-session-v2",
        "browser-session-v3",
    }:
        raise ValueError("unsupported-fixture-profile")
    sys.path[:0] = [str(source / "tests"), str(source / "tools")]
    import psycopg
    from auth_db import migrate, migrate_accounts, seed_demo
    from pg_support import assert_test_database
    from psycopg import sql

    base = assert_test_database(
        os.environ.get("FEATURE_STANDARDS_TEST_DATABASE_URL", "")
    )
    name = f"feature_standards_test_generated_{stack}_{profile[-2:]}_{uuid.uuid4().hex[:12]}"
    url = assert_test_database(urlunsplit(urlsplit(base)._replace(path="/" + name)))

    # SIGTERM also runs the owned-database cleanup below.
    def interrupted(*_):
        raise SystemExit(130)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    created = False
    try:
        with psycopg.connect(base, autocommit=True, connect_timeout=3) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
        (migrate_accounts if profile == "browser-session-v3" else migrate)(url)
        seed_demo(url)
        emit({"ready": True, "url": url})
        for line in sys.stdin:
            request = json.loads(line)
            if request == {"command": "close"}:
                break
            if (
                request.get("command") != "token"
                or request.get("kind") not in {"verify", "reset"}
                or not isinstance(request.get("email"), str)
            ):
                raise ValueError("unsupported-fixture-command")
            with psycopg.connect(url, connect_timeout=3) as conn:
                row = conn.execute(
                    "SELECT token FROM feature_auth.mail_outbox "
                    "WHERE recipient=%s AND kind=%s AND token IS NOT NULL "
                    "ORDER BY id DESC LIMIT 1",
                    (request["email"], request["kind"]),
                ).fetchone()
            if not row:
                raise ValueError("fixture-capability-not-found")
            emit({"token": row[0]})
    finally:
        if created:
            with psycopg.connect(base, autocommit=True, connect_timeout=3) as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(name)
                    )
                )
    emit({"closed": True})


if __name__ == "__main__":
    try:
        main()
    except (Exception, SystemExit):  # noqa: BLE001 -- driver diagnostics must not enter the pipe protocol
        # Do not include exception text: driver errors may contain connection details.
        emit({"error": "check-database-fixture-failed"})
        raise SystemExit(1) from None
