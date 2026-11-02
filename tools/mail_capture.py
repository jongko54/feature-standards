"""Capture local test mail capabilities into a new private file; never send mail."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from pg_support import assert_test_database


def capture(url: str, destination: Path, origin: str) -> int:
    url = assert_test_database(url)
    if origin not in ("http://127.0.0.1:5173", "http://localhost:5173"):
        raise ValueError("The capture tool only builds local test links")
    # New private files only: never follow or truncate an existing path or symlink.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    count = 0
    durable = False
    try:
        with (
            os.fdopen(fd, "w") as sink,
            psycopg.connect(url, connect_timeout=3) as conn,
        ):
            has_delivery = conn.execute(
                "SELECT to_regclass('feature_auth.mail_delivery') IS NOT NULL"
            ).fetchone()[0]
            conn.execute(
                "UPDATE feature_auth.mail_outbox SET token=NULL WHERE expires_at<=clock_timestamp()"
            )
            messages = conn.execute(
                "SELECT id,kind,recipient,token FROM feature_auth.mail_outbox "
                "WHERE delivered_at IS NULL AND token IS NOT NULL AND expires_at>clock_timestamp() "
                "ORDER BY id FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for message_id, kind, recipient, token in messages:
                # The parent lock precedes this new READ COMMITTED snapshot, just as
                # SMTP claims lock parent before sidecar. Never steal a worker's retry.
                if has_delivery:
                    delivery = conn.execute(
                        "SELECT state FROM feature_auth.mail_delivery WHERE outbox_id=%s",
                        (message_id,),
                    ).fetchone()
                    if delivery and delivery[0] != "pending":
                        continue
                route = "/verify-email" if kind == "verify" else "/reset-password"
                sink.write(
                    json.dumps(
                        {
                            "id": message_id,
                            "kind": kind,
                            "recipient": recipient,
                            "url": origin + route + "#" + urlencode({"token": token}),
                        }
                    )
                    + "\n"
                )
                conn.execute(
                    "UPDATE feature_auth.mail_outbox SET token=NULL,delivered_at=clock_timestamp() WHERE id=%s",
                    (message_id,),
                )
                count += 1
            sink.flush()
            os.fsync(sink.fileno())
            durable = True
    except BaseException:
        # Once fsynced, a lost COMMIT acknowledgement may mean delivery committed.
        # Preserve the only durable copy; a retry can be deduplicated by message id.
        if not durable:
            destination.unlink(missing_ok=True)
        raise
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:5173")
    args = parser.parse_args()
    try:
        count = capture(
            os.environ.get("FEATURE_STANDARDS_TEST_DATABASE_URL", ""),
            args.output,
            args.origin,
        )
    except (OSError, ValueError, psycopg.Error):
        print(
            "Local capture failed; no connection details or capabilities are displayed."
        )
        return 1
    print(f"Captured {count} local test messages into a private file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
