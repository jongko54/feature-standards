"""Real TCP + PostgreSQL composition; no public fixture-control endpoints."""

import json
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

import app as consumer
import psycopg
import uvicorn
from conformance import EMAIL, ORIGIN, PASSWORD, Client
from feature_auth import Settings
from feature_standards.authorization import Principal
from feature_standards.listing import ListingError
from feature_standards.postgres_listing import PostgresListing
from postgres_listing_conformance import ListingDatabase
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class DemoDatabaseGuard(unittest.TestCase):
    def test_inherited_libpq_defaults_are_rejected_before_connect(self):
        uri = "postgresql://reader@127.0.0.1:5432/feature_standards_test_documents?sslmode=disable"
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            with (
                self.subTest(name=name),
                patch.dict(
                    os.environ,
                    {
                        "FEATURE_STANDARDS_LISTING_DATABASE_URL": uri,
                        name: "203.0.113.99",
                    },
                    clear=True,
                ),
                patch.object(
                    consumer.psycopg,
                    "connect",
                    side_effect=AssertionError("connection boundary reached"),
                ),
                self.assertRaisesRegex(ListingError, "^LISTING_UNAVAILABLE$"),
            ):
                consumer.connect_database()

    def test_validated_loopback_address_is_pinned_in_public_connection_parameters(self):
        for host, address in (
            ("127.0.0.1", "127.0.0.1"),
            ("localhost", "127.0.0.1"),
            ("::1", "::1"),
        ):
            uri = make_conninfo(
                host=host,
                port=5432,
                dbname="feature_standards_test_documents",
                user="reader",
                sslmode="disable",
            )
            with (
                self.subTest(host=host),
                patch.dict(
                    os.environ,
                    {"FEATURE_STANDARDS_LISTING_DATABASE_URL": uri},
                    clear=True,
                ),
                patch.object(
                    consumer.psycopg, "connect", return_value=object()
                ) as connect,
            ):
                consumer.connect_database()
                args, kwargs = connect.call_args
                fields = conninfo_to_dict(*args, **kwargs)
                self.assertEqual(fields["hostaddr"], address)
                self.assertEqual(fields["options"], "")
                self.assertEqual(fields["host"], host)
                self.assertEqual(fields["port"], "5432")
                self.assertEqual(fields["dbname"], "feature_standards_test_documents")

    def test_even_empty_inherited_libpq_defaults_are_rejected(self):
        uri = "postgresql://reader@127.0.0.1:5432/feature_standards_test_documents?sslmode=disable"
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            with (
                self.subTest(name=name),
                patch.dict(
                    os.environ,
                    {"FEATURE_STANDARDS_LISTING_DATABASE_URL": uri, name: ""},
                    clear=True,
                ),
                patch.object(
                    consumer.psycopg,
                    "connect",
                    side_effect=AssertionError("connection boundary reached"),
                ),
                self.assertRaisesRegex(ListingError, "^LISTING_UNAVAILABLE$"),
            ):
                consumer.connect_database()

    def test_default_demo_factory_rejects_unsafe_or_missing_database_before_connect(
        self,
    ):
        for value in (
            "",
            "postgresql://reader@db.example.com:5432/feature_standards_test_documents?sslmode=disable",
            "postgresql://reader@127.0.0.1:5432/product_database?sslmode=disable",
            "postgresql://reader@127.0.0.1/feature_standards_test_documents?sslmode=disable",
            "postgresql://reader@127.0.0.1:5432/feature_standards_test_documents?sslmode=disable&options=-csearch_path=public",
        ):
            with (
                self.subTest(value=value),
                patch.dict(
                    os.environ, {"FEATURE_STANDARDS_LISTING_DATABASE_URL": value}
                ),
                patch.object(
                    consumer.psycopg,
                    "connect",
                    side_effect=AssertionError("must not connect"),
                ),
                self.assertRaisesRegex(ListingError, "^LISTING_UNAVAILABLE$"),
            ):
                consumer.connect_database()


class PostgresCoreHttpContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = ListingDatabase().__enter__()
        cls.state = {
            "roles": ("viewer",),
            "membership_down": False,
            "database_down": False,
            "wrong_subject": False,
            "mutate_user": False,
            "connections": 0,
        }
        cls.store = PostgresListing(
            schema=consumer.SCHEMA,
            table=(cls.database.schema, "documents"),
            columns={"id": "id", "name": "name", "score": "score", "active": "active"},
            tenant_column="tenant_id",
            owner_column="owner_id",
        )

        def membership(user):
            if cls.state["membership_down"]:
                raise RuntimeError("private-membership-details")
            if cls.state["mutate_user"]:
                user["id"] = "other-user"
            return Principal(
                "wrong-subject" if cls.state["wrong_subject"] else user["id"],
                "tenant-a",
                cls.state["roles"],
            )

        def connect():
            cls.state["connections"] += 1
            if cls.state["database_down"]:
                raise psycopg.OperationalError("private-database-details")
            return psycopg.connect(cls.database.conninfo)

        application = consumer.create_postgres_core_app(
            settings=Settings(
                demo=True,
                email=EMAIL,
                password=PASSWORD,
                origin=ORIGIN,
                secure_cookie=False,
                rate_limit_max=1000,
            ),
            membership=membership,
            connect=connect,
            store=cls.store,
        )
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.server = uvicorn.Server(
            uvicorn.Config(application, log_level="error", proxy_headers=False)
        )
        cls.thread = threading.Thread(
            target=cls.server.run, kwargs={"sockets": [cls.listener]}, daemon=True
        )
        cls.thread.start()
        for _ in range(200):
            if cls.server.started:
                return
            if not cls.thread.is_alive():
                break
            time.sleep(0.05)
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.listener.close()
        cls.database.__exit__()
        raise RuntimeError("PostgreSQL core HTTP consumer did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.listener.close()
        cls.database.__exit__()
        if cls.thread.is_alive():
            raise RuntimeError("PostgreSQL core HTTP consumer did not stop")

    def setUp(self):
        self.state.update(
            roles=("viewer",),
            membership_down=False,
            database_down=False,
            wrong_subject=False,
            mutate_user=False,
            connections=0,
        )
        with psycopg.connect(self.database.conninfo, autocommit=True) as connection:
            relation = sql.Identifier(self.database.schema, "documents")
            connection.execute(sql.SQL("TRUNCATE {}").format(relation))
            with connection.cursor() as cursor:
                cursor.executemany(
                    sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s)").format(
                        relation
                    ),
                    [
                        ("own-b", "tenant-a", "demo-user", "Beta", 2, False),
                        ("other-owner", "tenant-a", "other-user", "Private", 10, True),
                        ("other-tenant", "tenant-b", "demo-user", "Secret", 99, True),
                        ("own-a", "tenant-a", "demo-user", "Alpha", 2, True),
                    ],
                )
        self.client = Client(self.base)

    def login(self):
        result = self.client.login()
        self.assertEqual(result[0], 200, result[2])
        return json.loads(result[2])

    def error(self, result, status, code):
        self.assertEqual(result[0], status, result[2])
        self.assertEqual(json.loads(result[2])["error"]["code"], code)
        self.assertEqual(result[1].get("cache-control"), "no-store")
        self.assertEqual(result[1].get("x-content-type-options"), "nosniff")
        self.assertNotIn(b"private-membership-details", result[2])
        self.assertNotIn(b"private-database-details", result[2])

    def test_anonymous_or_forged_session_does_not_open_database(self):
        self.error(self.client.request("GET", "/api/documents"), 401, "UNAUTHENTICATED")
        self.client.cookie = "fs_session=forged"
        self.error(self.client.request("GET", "/api/documents"), 401, "UNAUTHENTICATED")
        self.assertEqual(self.state["connections"], 0)

    def test_owner_and_tenant_grants_are_scoped_before_total_and_projection(self):
        self.login()
        result = self.client.request("GET", "/api/documents?limit=1&sort=-score")
        self.assertEqual(result[0], 200)
        value = json.loads(result[2])
        self.assertEqual(value["total"], 2)
        self.assertEqual(
            value["items"],
            [{"id": "own-a", "name": "Alpha", "score": 2, "active": True}],
        )
        self.state["roles"] = ("editor",)
        result = self.client.request("GET", "/api/documents?sort=-score")
        self.assertEqual(result[0], 200)
        value = json.loads(result[2])
        self.assertEqual(value["total"], 3)
        self.assertEqual(value["items"][0]["id"], "other-owner")
        self.assertNotIn(b"other-tenant", result[2])
        self.assertNotIn(b"owner_id", result[2])

    def test_current_membership_revocation_and_subject_mismatch_deny(self):
        self.login()
        self.state["roles"] = ()
        self.error(
            self.client.request(
                "GET",
                "/api/documents",
                headers={
                    "X-Role": "editor",
                    "X-Tenant-Id": "tenant-b",
                    "X-Subject-Id": "other-user",
                },
            ),
            403,
            "FORBIDDEN",
        )
        self.state.update(roles=("viewer",), wrong_subject=True)
        self.error(self.client.request("GET", "/api/documents"), 403, "FORBIDDEN")
        self.assertEqual(self.state["connections"], 0)

    def test_mutating_provider_cannot_change_authenticated_subject_or_session(self):
        self.login()
        self.state["mutate_user"] = True
        self.error(self.client.request("GET", "/api/documents"), 403, "FORBIDDEN")
        self.assertEqual(self.state["connections"], 0)
        self.state["mutate_user"] = False
        current = self.client.request("GET", "/auth/me")
        self.assertEqual(current[0], 200)
        self.assertEqual(json.loads(current[2])["user"]["id"], "demo-user")
        result = self.client.request("GET", "/api/documents")
        self.assertEqual(result[0], 200)
        self.assertEqual(
            [row["id"] for row in json.loads(result[2])["items"]], ["own-a", "own-b"]
        )

    def test_strict_queries_and_bound_filter_values(self):
        self.login()
        self.state["database_down"] = True
        for query in (
            "role=editor",
            "limit=0",
            "limit=1&%6cimit=2",
            "sort=name%20DESC",
            "filter.score=01",
        ):
            self.error(
                self.client.request("GET", "/api/documents?" + query),
                400,
                "INVALID_LIST_QUERY",
            )
        self.assertEqual(self.state["connections"], 0)
        self.state["database_down"] = False
        result = self.client.request(
            "GET", "/api/documents?filter.name=%27%20OR%20true--"
        )
        self.assertEqual(result[0], 200)
        self.assertEqual(json.loads(result[2])["total"], 0)

    def test_provider_and_database_failure_are_sanitized(self):
        self.login()
        self.state["membership_down"] = True
        self.error(
            self.client.request("GET", "/api/documents"),
            503,
            "AUTHORIZATION_UNAVAILABLE",
        )
        self.assertEqual(self.state["connections"], 0)
        self.state.update(membership_down=False, database_down=True)
        self.error(
            self.client.request("GET", "/api/documents"), 503, "LISTING_UNAVAILABLE"
        )

    def test_logout_revokes_old_cookie_before_database_use(self):
        session = self.login()
        self.assertEqual(self.client.request("GET", "/api/documents")[0], 200)
        old = self.client.cookie
        result = self.client.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": session["csrfToken"]}
        )
        self.assertEqual(result[0], 204, result[2])
        before = self.state["connections"]
        self.client.cookie = old
        self.error(self.client.request("GET", "/api/documents"), 401, "UNAUTHENTICATED")
        self.assertEqual(self.state["connections"], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
