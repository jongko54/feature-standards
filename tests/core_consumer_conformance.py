#!/usr/bin/env python3
"""Exercise real TCP HTTP against auth + trusted membership + both core features."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/core-python"))

import app as core_app
import uvicorn
from app import create_core_app
from conformance import EMAIL, ORIGIN, PASSWORD, Client
from feature_auth import Settings
from feature_standards.authorization import Principal


class CoreConsumerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.membership = {"roles": ("viewer",), "unavailable": False}

        def membership(user):
            if cls.membership["unavailable"]:
                raise RuntimeError("private-provider-detail")
            if cls.membership.get("missing"):
                return None
            if cls.membership.get("mutate"):
                user["id"] = "other-user"
            return Principal(
                cls.membership.get("subject") or user["id"],
                "tenant-a",
                cls.membership["roles"],
            )

        app = create_core_app(
            membership=membership,
            settings=Settings(
                demo=True,
                email=EMAIL,
                password=PASSWORD,
                origin=ORIGIN,
                secure_cookie=False,
                rate_limit_max=1000,
            ),
        )
        # Own the listening socket for the complete server lifetime (no port race).
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", proxy_headers=False)
        )
        cls.thread = threading.Thread(
            target=cls.server.run,
            kwargs={"sockets": [cls.listener]},
            daemon=True,
        )
        cls.thread.start()
        for _ in range(200):
            if cls.server.started:
                return
            if not cls.thread.is_alive():
                break
            time.sleep(0.05)
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.listener.close()
        raise RuntimeError("Core consumer did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.listener.close()
        if cls.thread.is_alive():
            raise RuntimeError("Core consumer did not stop")

    def setUp(self):
        self.membership.update(
            roles=("viewer",),
            unavailable=False,
            missing=False,
            subject=None,
            mutate=False,
        )
        self.client = Client(self.base)

    def login(self):
        result = self.client.login()
        self.assertEqual(result[0], 200, result)
        return json.loads(result[2])

    def error(self, result, status, code):
        self.assertEqual(result[0], status, result[2])
        self.assertEqual(json.loads(result[2])["error"]["code"], code)
        self.assertEqual(result[1].get("cache-control"), "no-store")
        self.assertEqual(result[1].get("x-content-type-options"), "nosniff")
        self.assertNotIn(b"private-provider-detail", result[2])

    def test_anonymous_and_forged_sessions(self):
        for path in ("/api/documents", "/api/documents/own-a"):
            self.error(self.client.request("GET", path), 401, "UNAUTHENTICATED")
            self.error(
                self.client.request(
                    "GET", path, headers={"Cookie": "fs_session=forged"}
                ),
                401,
                "UNAUTHENTICATED",
            )

    def test_owner_tenant_and_nonexistent_resources(self):
        self.login()
        result = self.client.request("GET", "/api/documents/own-a")
        self.assertEqual(result[0], 200)
        self.assertEqual(json.loads(result[2])["id"], "own-a")
        self.assertEqual(result[1]["cache-control"], "no-store")
        for identifier in ("other-owner", "other-tenant", "missing"):
            self.error(
                self.client.request("GET", f"/api/documents/{identifier}"),
                403,
                "FORBIDDEN",
            )

    def test_headers_and_query_cannot_grant_roles(self):
        self.login()
        forged = {
            "X-Role": "admin",
            "X-Roles": "editor",
            "X-Tenant-Id": "tenant-b",
            "X-Subject-Id": "other-user",
        }
        self.error(
            self.client.request("GET", "/api/documents/other-owner", headers=forged),
            403,
            "FORBIDDEN",
        )
        self.error(
            self.client.request("GET", "/api/documents?role=admin", headers=forged),
            400,
            "INVALID_LIST_QUERY",
        )

    def test_authorized_rows_precede_totals_and_pagination(self):
        self.login()
        result = self.client.request("GET", "/api/documents?limit=1&sort=-score")
        self.assertEqual(result[0], 200, result[2])
        value = json.loads(result[2])
        self.assertEqual(
            value,
            {
                "items": [{"id": "own-a", "name": "Alpha", "score": 2, "active": True}],
                "total": 2,
                "limit": 1,
                "offset": 0,
                "nextOffset": 1,
            },
        )
        result = self.client.request(
            "GET", "/api/documents?limit=1&offset=1&sort=-score"
        )
        self.assertEqual(json.loads(result[2])["items"][0]["id"], "own-b")
        self.assertIsNone(json.loads(result[2])["nextOffset"])

    def test_filter_and_out_of_range_offset(self):
        self.login()
        result = self.client.request(
            "GET", "/api/documents?filter.active=false&offset=10000"
        )
        self.assertEqual(result[0], 200)
        self.assertEqual(
            json.loads(result[2]),
            {"items": [], "total": 1, "limit": 20, "offset": 10000, "nextOffset": None},
        )

    def test_strict_raw_query_errors(self):
        self.login()
        for query in (
            "limit=1&%6cimit=2",
            "filter.name=%FF",
            "filter.name=%ED%A0%80",
            "sort=id%2Cname",
            "limit=01",
            "filter.score=-0",
            "limit=1&",
            "filter.name=%00",
        ):
            with self.subTest(query=query):
                self.error(
                    self.client.request("GET", "/api/documents?" + query),
                    400,
                    "INVALID_LIST_QUERY",
                )

    def test_role_revocation_applies_to_existing_session(self):
        self.login()
        self.assertEqual(self.client.request("GET", "/api/documents")[0], 200)
        self.membership["roles"] = ()
        self.error(self.client.request("GET", "/api/documents"), 403, "FORBIDDEN")
        self.error(self.client.request("GET", "/api/documents/own-a"), 403, "FORBIDDEN")

    def test_provider_failure_is_generic_and_fails_closed(self):
        self.login()
        self.membership["unavailable"] = True
        for path in ("/api/documents", "/api/documents/own-a"):
            self.error(
                self.client.request("GET", path), 503, "AUTHORIZATION_UNAVAILABLE"
            )

    def test_missing_or_mismatched_current_membership_denies_existing_session(self):
        self.login()
        for state in ({"missing": True}, {"missing": False, "subject": "other-user"}):
            self.membership.update(state)
            for path in ("/api/documents", "/api/documents/own-a"):
                self.error(self.client.request("GET", path), 403, "FORBIDDEN")

    def test_membership_provider_cannot_rewrite_authenticated_subject(self):
        self.login()
        self.membership["mutate"] = True
        self.error(
            self.client.request("GET", "/api/documents/other-owner"), 403, "FORBIDDEN"
        )
        self.membership["mutate"] = False
        self.assertEqual(self.client.request("GET", "/api/documents/own-a")[0], 200)

    def test_logout_revokes_replayed_cookie(self):
        session = self.login()
        saved = self.client.cookie
        result = self.client.request(
            "POST", "/auth/logout", headers={"X-CSRF-Token": session["csrfToken"]}
        )
        self.assertEqual(result[0], 204, result)
        self.client.cookie = saved
        self.error(self.client.request("GET", "/api/documents"), 401, "UNAUTHENTICATED")

    def test_missing_trusted_data_returns_fixed_error(self):
        self.login()
        incomplete = {
            "id": "own-a",
            "name": "Private row",
            "active": True,
            "tenantId": "tenant-a",
            "ownerId": "demo-user",
        }
        with patch.object(core_app, "DOCUMENTS", (incomplete,)):
            for path in ("/api/documents?sort=score", "/api/documents/own-a"):
                result = self.client.request("GET", path)
                self.error(result, 500, "INVALID_LIST_DATA")
                self.assertNotIn(b"Private row", result[2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
