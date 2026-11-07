#!/usr/bin/env python3
"""Real PostgreSQL tests in a task-owned schema or an owned temporary cluster."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libraries/python"))

import psycopg
from feature_standards.listing import ListingError, ListingSchema
from feature_standards.postgres_listing import PostgresListing, VisibilityScope
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.pq import TransactionStatus

_UNSAFE_LIBPQ_ENV = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")


class ListingDatabase:
    """Never use auth schemas, inherited AUTH_DATABASE_URL, or remote databases."""

    def __enter__(self):
        self.temporary = None
        self.cluster_started = False
        self.schema_created = False
        if any(name in os.environ for name in _UNSAFE_LIBPQ_ENV):
            raise RuntimeError("Unsafe inherited PostgreSQL environment")
        configured = os.environ.get("FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL")
        if configured:
            fields = conninfo_to_dict(configured)
            if (
                fields.get("host") not in ("127.0.0.1", "localhost", "::1")
                or not fields.get("port", "").isdigit()
                or not 1 <= int(fields.get("port", "0")) <= 65535
                or not fields.get("dbname", "").startswith("feature_standards_test")
                or fields.get("sslmode") != "disable"
                or any(key in fields for key in ("hostaddr", "service", "options"))
            ):
                raise RuntimeError("Unsafe listing test database configuration")
            address = "127.0.0.1" if fields["host"] == "localhost" else fields["host"]
            self.conninfo = make_conninfo(configured, hostaddr=address, options="")
        else:
            binaries = os.environ.get("FEATURE_STANDARDS_LISTING_PG_BIN")
            self.initdb = (
                str(Path(binaries) / "initdb") if binaries else shutil.which("initdb")
            )
            self.pg_ctl = (
                str(Path(binaries) / "pg_ctl") if binaries else shutil.which("pg_ctl")
            )
            if (
                not self.initdb
                or not self.pg_ctl
                or not (Path(self.initdb).resolve().parent / "postgres").is_file()
            ):
                raise RuntimeError(
                    "Listing tests require owned PostgreSQL binaries or explicit test database"
                )
            self.temporary = Path(
                tempfile.mkdtemp(
                    prefix="pg-list-",
                    dir="/private/tmp" if sys.platform == "darwin" else None,
                )
            )
            base = self.temporary
            self.data = base / "data"
            socket = base / "socket"
            socket.mkdir(mode=0o700)
            initialized = subprocess.run(
                [
                    self.initdb,
                    "-D",
                    str(self.data),
                    "--auth=trust",
                    "--no-sync",
                    "--encoding=UTF8",
                    "--locale=C",
                    "-U",
                    "feature_listing_test",
                ],
                check=False,
                capture_output=True,
            )
            if initialized.returncode:
                shutil.rmtree(self.temporary)
                raise RuntimeError(
                    "Owned listing PostgreSQL bootstrap files are incomplete"
                )
            started = subprocess.run(
                [
                    self.pg_ctl,
                    "-D",
                    str(self.data),
                    "-l",
                    str(base / "postgres.log"),
                    "-o",
                    f"-F -h '' -k {socket} -p 5432",
                    "-w",
                    "start",
                ],
                check=False,
                capture_output=True,
            )
            if started.returncode:
                # A timed-out pg_ctl can leave its own postmaster starting.
                # Never remove a data directory until this owned process stops.
                if (self.data / "postmaster.pid").exists():
                    stopped = subprocess.run(
                        [self.pg_ctl, "-D", str(self.data), "-m", "fast", "-w", "stop"],
                        check=False,
                        capture_output=True,
                    )
                    if stopped.returncode:
                        raise RuntimeError(
                            "Owned listing PostgreSQL startup cleanup could not stop its process"
                        )
                shutil.rmtree(self.temporary)
                raise RuntimeError("Owned listing PostgreSQL cluster could not start")
            self.cluster_started = True
            self.conninfo = make_conninfo(
                host=str(socket),
                hostaddr="",
                port=5432,
                user="feature_listing_test",
                dbname="postgres",
                sslmode="disable",
                options="",
            )
        self.schema = "core_listing_" + uuid.uuid4().hex
        try:
            with psycopg.connect(self.conninfo, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
                )
                self.schema_created = True
                connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema))
                )
                connection.execute(
                    (ROOT / "tests/fixtures/core_listing.sql").read_text()
                )
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(self, *_):
        try:
            if self.schema_created:
                with psycopg.connect(self.conninfo, autocommit=True) as connection:
                    connection.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(self.schema)
                        )
                    )
        finally:
            if self.temporary is not None:
                if self.cluster_started:
                    stopped = subprocess.run(
                        [self.pg_ctl, "-D", str(self.data), "-m", "fast", "-w", "stop"],
                        check=False,
                        capture_output=True,
                    )
                    if stopped.returncode:
                        raise RuntimeError(
                            "Owned listing PostgreSQL cluster did not stop"
                        )
                shutil.rmtree(self.temporary)


class ListingDatabaseGuard(unittest.TestCase):
    def test_inherited_libpq_defaults_are_rejected_before_fixture_or_connection_io(
        self,
    ):
        uri = "postgresql://reader@127.0.0.1:5432/feature_standards_test_listing?sslmode=disable"
        for configured in (False, True):
            for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
                environment = {name: "203.0.113.99"}
                if configured:
                    environment["FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL"] = uri
                with (
                    self.subTest(configured=configured, name=name),
                    patch.dict(os.environ, environment, clear=True),
                    patch(
                        "psycopg.connect",
                        side_effect=AssertionError("connection boundary reached"),
                    ),
                    patch(
                        "shutil.which",
                        side_effect=AssertionError("fixture probe reached"),
                    ),
                    patch(
                        "tempfile.mkdtemp",
                        side_effect=AssertionError("fixture creation reached"),
                    ),
                    self.assertRaisesRegex(
                        RuntimeError, "^Unsafe inherited PostgreSQL environment$"
                    ),
                ):
                    ListingDatabase().__enter__()

    def test_configured_connection_pins_validated_loopback_hostaddr(self):
        class ConnectionObserved(Exception):
            pass

        for host, address in (
            ("127.0.0.1", "127.0.0.1"),
            ("localhost", "127.0.0.1"),
            ("::1", "::1"),
        ):
            uri = make_conninfo(
                host=host,
                port=5432,
                dbname="feature_standards_test_listing",
                user="reader",
                sslmode="disable",
            )
            with (
                self.subTest(host=host),
                patch.dict(
                    os.environ,
                    {"FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL": uri},
                    clear=True,
                ),
                patch("psycopg.connect", side_effect=ConnectionObserved) as connect,
                self.assertRaises(ConnectionObserved),
            ):
                ListingDatabase().__enter__()
            args, kwargs = connect.call_args
            kwargs = {
                key: value for key, value in kwargs.items() if key != "autocommit"
            }
            fields = conninfo_to_dict(*args, **kwargs)
            self.assertEqual(fields["hostaddr"], address)
            self.assertEqual(fields["options"], "")
            self.assertEqual(fields["host"], host)
            self.assertEqual(fields["port"], "5432")
            self.assertEqual(fields["dbname"], "feature_standards_test_listing")

    def test_even_empty_inherited_defaults_are_rejected_before_fixture_or_connection_io(
        self,
    ):
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {name: ""}, clear=True),
                patch(
                    "psycopg.connect",
                    side_effect=AssertionError("connection boundary reached"),
                ),
                patch(
                    "shutil.which", side_effect=AssertionError("fixture probe reached")
                ),
                patch(
                    "tempfile.mkdtemp",
                    side_effect=AssertionError("fixture creation reached"),
                ),
                self.assertRaisesRegex(
                    RuntimeError, "^Unsafe inherited PostgreSQL environment$"
                ),
            ):
                ListingDatabase().__enter__()


class PostgresListingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = ListingDatabase().__enter__()
        cls.schema = ListingSchema(
            {"id": "string", "name": "string", "score": "integer", "active": "boolean"},
            {"name": "string", "score": "integer", "active": "boolean"},
        )
        cls.adapter = PostgresListing(
            schema=cls.schema,
            table=(cls.database.schema, "documents"),
            columns={"id": "id", "name": "name", "score": "score", "active": "active"},
            tenant_column="tenant_id",
            owner_column="owner_id",
        )
        cls.relation = sql.Identifier(cls.database.schema, "documents")

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__()
        if cls.database.temporary is not None and cls.database.temporary.exists():
            raise RuntimeError("Owned listing PostgreSQL temporary directory remained")
        if cls.database.temporary is None:
            with psycopg.connect(cls.database.conninfo, autocommit=True) as connection:
                found = connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s",
                    (cls.database.schema,),
                ).fetchone()
                if found is not None:
                    raise RuntimeError("Owned listing PostgreSQL schema remained")

    def connection(self, **kwargs):
        return psycopg.connect(
            self.database.conninfo, autocommit=kwargs.pop("autocommit", True), **kwargs
        )

    def setUp(self):
        with self.connection() as connection:
            connection.execute(sql.SQL("TRUNCATE {}").format(self.relation))
            with connection.cursor() as cursor:
                cursor.executemany(
                    sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s)").format(
                        self.relation
                    ),
                    [
                        ("own-b", "tenant-a", "user-1", "Beta", 2, False),
                        ("other-owner", "tenant-a", "user-2", "Private", 10, True),
                        ("other-tenant", "tenant-b", "user-1", "Secret", 99, True),
                        ("own-a", "tenant-a", "user-1", "Alpha", 2, True),
                    ],
                )

    def read(self, raw="", scope=None):
        with self.connection() as connection:
            result = self.adapter.page(
                connection, raw, scope or VisibilityScope("tenant-a", "user-1")
            )
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            return result

    def test_visibility_scopes_rows_before_totals_and_projection(self):
        result = self.read("limit=1&sort=-score")
        self.assertEqual(
            result,
            {
                "items": [{"id": "own-a", "name": "Alpha", "score": 2, "active": True}],
                "total": 2,
                "limit": 1,
                "offset": 0,
                "nextOffset": 1,
            },
        )
        self.assertEqual(self.read(scope=VisibilityScope("tenant-a", None))["total"], 3)
        self.assertEqual(self.read(scope=VisibilityScope("tenant-c", None))["total"], 0)
        self.assertEqual(self.read("offset=9")["nextOffset"], None)

    def test_typed_filters_stable_ties_and_sql_injection_values(self):
        self.assertEqual(
            self.read("filter.active=true&filter.score=2")["items"][0]["id"], "own-a"
        )
        self.assertEqual(
            [x["id"] for x in self.read("sort=-score")["items"]], ["own-a", "own-b"]
        )
        self.assertEqual(
            [x["id"] for x in self.read("sort=-id")["items"]], ["own-b", "own-a"]
        )
        self.assertEqual(self.read("filter.name=%27%20OR%20true--")["total"], 0)
        for query in (
            "sort=name%20DESC",
            "filter.score=01",
            "filter.active=1",
            "limit=1&%6cimit=2",
        ):
            with (
                self.subTest(query=query),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"),
            ):
                self.read(query)

    def test_unicode_scalar_sort_and_string_equality_ignore_database_locale(self):
        with self.connection() as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} VALUES ('unicode-a','unicode','user-1',%s,0,true),('unicode-b','unicode','user-1',%s,0,true)"
                ).format(self.relation),
                ("\ue000", "\U00010000"),
            )
        result = self.read("sort=name", VisibilityScope("unicode", "user-1"))
        self.assertEqual(
            [row["id"] for row in result["items"]], ["unicode-a", "unicode-b"]
        )
        self.assertEqual(
            self.read("filter.name=%F0%90%80%80", VisibilityScope("unicode", "user-1"))[
                "total"
            ],
            1,
        )

    def test_database_dataset_can_exceed_materialized_v1_cap(self):
        with self.connection() as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} SELECT 'bulk-'||n,'bulk-tenant','user-1','Bulk',n,true FROM generate_series(1,12005) n"
                ).format(self.relation)
            )
        result = self.read(
            "offset=10000&limit=100&sort=score",
            VisibilityScope("bulk-tenant", "user-1"),
        )
        self.assertEqual(result["total"], 12005)
        self.assertEqual(len(result["items"]), 100)
        self.assertEqual(result["items"][0]["score"], 10001)
        self.assertIsNone(result["nextOffset"])

    def test_count_and_page_share_snapshot_across_committed_writer(self):
        counted, committed = threading.Event(), threading.Event()
        failures = []

        def writer():
            try:
                if not counted.wait(5):
                    raise RuntimeError("count was not observed")
                with self.connection() as connection:
                    connection.execute(
                        sql.SQL(
                            "INSERT INTO {} VALUES ('own-new','tenant-a','user-1','New',1,true)"
                        ).format(self.relation)
                    )
            except (RuntimeError, psycopg.Error) as exc:
                failures.append(exc)
            finally:
                committed.set()

        class InterleavedCursor(psycopg.Cursor):
            def execute(cursor, query, params=None, **kwargs):
                result = super().execute(query, params, **kwargs)
                text = (
                    query.as_string(cursor.connection)
                    if isinstance(query, sql.Composable)
                    else query
                )
                if text.startswith("SELECT COUNT(*)"):
                    counted.set()
                    if not committed.wait(5):
                        raise RuntimeError("writer did not finish")
                return result

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            with self.connection(cursor_factory=InterleavedCursor) as connection:
                result = self.adapter.page(
                    connection, "", VisibilityScope("tenant-a", "user-1")
                )
            self.assertEqual(result["total"], 2)
            self.assertEqual(len(result["items"]), 2)
            self.assertEqual(self.read()["total"], 3)
        finally:
            counted.set()
            thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])

    def test_active_caller_transaction_is_preserved_and_refused(self):
        with self.connection(autocommit=False) as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} VALUES ('caller','tenant-a','user-1','Caller',1,true)"
                ).format(self.relation)
            )
            with self.assertRaisesRegex(ListingError, "^INVALID_LIST_TRANSACTION$"):
                self.adapter.page(connection, "", VisibilityScope("tenant-a", "user-1"))
            self.assertEqual(
                connection.info.transaction_status, TransactionStatus.INTRANS
            )
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT count(*) FROM {} WHERE id='caller'").format(
                        self.relation
                    )
                ).fetchone()[0],
                1,
            )
            connection.rollback()
        self.assertEqual(self.read()["total"], 2)

    def test_read_only_isolation_and_error_rollback_leave_connection_usable(self):
        observed = []
        relation = self.relation

        class WritingCursor(psycopg.Cursor):
            def execute(cursor, query, params=None, **kwargs):
                text = (
                    query.as_string(cursor.connection)
                    if isinstance(query, sql.Composable)
                    else query
                )
                if text.startswith("SELECT COUNT(*)"):
                    with psycopg.Cursor(cursor.connection) as inspect:
                        inspect.execute("SHOW transaction_read_only")
                        observed.append(inspect.fetchone()[0])
                        inspect.execute("SHOW transaction_isolation")
                        observed.append(inspect.fetchone()[0])
                        inspect.execute(
                            sql.SQL(
                                "INSERT INTO {} VALUES ('must-not-write','tenant-a','user-1','No',1,true)"
                            ).format(relation)
                        )
                return super().execute(query, params, **kwargs)

        with self.connection(cursor_factory=WritingCursor) as connection:
            with self.assertRaisesRegex(
                ListingError, "^LISTING_UNAVAILABLE$"
            ) as failure:
                self.adapter.page(connection, "", VisibilityScope("tenant-a", "user-1"))
            self.assertEqual(str(failure.exception), "LISTING_UNAVAILABLE")
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            with psycopg.Cursor(connection) as cursor:
                self.assertEqual(cursor.execute("SELECT 1").fetchone()[0], 1)
        self.assertEqual(observed, ["on", "repeatable read"])
        self.assertEqual(self.read()["total"], 2)

    def test_missing_relation_and_closed_connection_are_sanitized(self):
        missing = PostgresListing(
            schema=self.schema,
            table=(self.database.schema, "missing_private_table"),
            columns=self.adapter.columns,
            tenant_column="tenant_id",
            owner_column="owner_id",
        )
        with self.connection() as connection:
            with self.assertRaisesRegex(ListingError, "^LISTING_UNAVAILABLE$"):
                missing.page(connection, "", VisibilityScope("tenant-a", "user-1"))
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
        with self.assertRaisesRegex(ListingError, "^LISTING_UNAVAILABLE$"):
            self.adapter.page(connection, "", VisibilityScope("tenant-a", "user-1"))

    def test_database_constraints_reject_invalid_trusted_values(self):
        with self.connection() as connection:
            for name, score in (("Bad\nName", 1), ("", 1), ("Bad", 9007199254740992)):
                with (
                    self.subTest(name=name, score=score),
                    self.assertRaises(psycopg.errors.CheckViolation),
                ):
                    connection.execute(
                        sql.SQL(
                            "INSERT INTO {} VALUES ('bad','tenant-a','user-1',%s,%s,true)"
                        ).format(self.relation),
                        (name, score),
                    )

    def test_selected_trusted_data_is_validated_and_transaction_rolled_back(self):
        loose = sql.Identifier(self.database.schema, "loose_documents")
        with self.connection() as connection:
            connection.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(loose))
            connection.execute(
                sql.SQL("CREATE TABLE {} AS SELECT * FROM {} WHERE id='own-a'").format(
                    loose, self.relation
                )
            )
            connection.execute(sql.SQL("UPDATE {} SET name=NULL").format(loose))
            invalid = PostgresListing(
                schema=self.schema,
                table=(self.database.schema, "loose_documents"),
                columns=self.adapter.columns,
                tenant_column="tenant_id",
                owner_column="owner_id",
            )
            with self.assertRaisesRegex(ListingError, "^INVALID_LIST_DATA$"):
                invalid.page(connection, "", VisibilityScope("tenant-a", "user-1"))
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

    def test_session_defaults_are_preserved_for_non_autocommit_connection(self):
        with self.connection(autocommit=False) as connection:
            connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
            connection.read_only = False
            result = self.adapter.page(
                connection, "", VisibilityScope("tenant-a", "user-1")
            )
            self.assertEqual(result["total"], 2)
            self.assertEqual(connection.info.transaction_status, TransactionStatus.IDLE)
            self.assertEqual(
                connection.isolation_level, psycopg.IsolationLevel.READ_COMMITTED
            )
            self.assertFalse(connection.read_only)

    def test_owned_or_configured_connection_has_explicit_destination_parameters(self):
        fields = conninfo_to_dict(self.database.conninfo)
        self.assertEqual(fields["options"], "")
        if self.database.temporary is not None:
            self.assertEqual(fields["port"], "5432")
            self.assertEqual(fields["host"], str(self.database.temporary / "socket"))
            self.assertEqual(fields["hostaddr"], "")
            self.assertEqual(fields["user"], "feature_listing_test")
            self.assertEqual(fields["dbname"], "postgres")
        else:
            self.assertEqual(
                fields["hostaddr"],
                {"localhost": "127.0.0.1", "127.0.0.1": "127.0.0.1", "::1": "::1"}[
                    fields["host"]
                ],
            )

    def test_startup_failure_stops_only_its_owned_postmaster_before_removal(self):
        explicit = os.environ.get("FEATURE_STANDARDS_LISTING_PG_BIN")
        server = (
            Path(explicit)
            if explicit
            else Path(shutil.which("postgres") or "/missing").parent
        )
        if not all(
            (server / name).is_file() for name in ("postgres", "initdb", "pg_ctl")
        ):
            self.skipTest(
                "Owned server binaries are not available for startup-failure regression"
            )
        with tempfile.TemporaryDirectory(prefix="pg-list-failure-") as temporary:
            base = Path(temporary)
            for name in ("postgres", "initdb"):
                (base / name).symlink_to((server / name).resolve())
            record = base / "owned-data.json"
            wrapper = base / "pg_ctl"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import json,subprocess,sys\n"
                "from pathlib import Path\n"
                f"result=subprocess.run([{str(server / 'pg_ctl')!r},*sys.argv[1:]],check=False,capture_output=True)\n"
                "if result.returncode==0 and sys.argv[-1]=='start':\n"
                " data=Path(sys.argv[sys.argv.index('-D')+1])\n"
                f" Path({str(record)!r}).write_text(json.dumps({{'path':str(data),'pid':int((data/'postmaster.pid').read_text().splitlines()[0])}}))\n"
                " sys.exit(1)\n"
                "sys.exit(result.returncode)\n"
            )
            wrapper.chmod(0o700)
            with patch.dict(
                os.environ, {"FEATURE_STANDARDS_LISTING_PG_BIN": str(base)}
            ):
                os.environ.pop("FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL", None)
                with self.assertRaisesRegex(
                    RuntimeError, "^Owned listing PostgreSQL cluster could not start$"
                ):
                    ListingDatabase().__enter__()
            owned = json.loads(record.read_text())
            self.assertFalse(Path(owned["path"]).parent.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(owned["pid"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
