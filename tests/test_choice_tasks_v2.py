"""Guidance v2 protocol and real loopback checks, without model/toolchain calls."""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "libraries/python"))
import auth_eval
import core_discovery_eval as discovery
import core_eval
import test_core_eval as fixtures
from feature_standards.listing import ListingError, ListingSchema, page, parse_query


class ProtocolTests(unittest.TestCase):
    def test_v2_exposes_explicit_scenarios_conditions_and_preserves_common_body(self):
        self.assertIsNotNone(importlib.util.find_spec("choice_tasks_v2"))
        choice = importlib.import_module("choice_tasks_v2")
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        self.assertEqual(choice.SCENARIOS, ("documents", "tickets"))
        self.assertEqual(choice.CONDITIONS, ("baseline", "sdk-pointer"))
        for scenario in choice.SCENARIOS:
            for stack in auth_eval.STACKS:
                baseline = choice.prompt(
                    stack, "a" * 40, tasks, "baseline", scenario=scenario
                )
                pointed = choice.prompt(
                    stack, "a" * 40, tasks, "sdk-pointer", scenario=scenario
                )
                self.assertTrue(pointed.startswith(baseline))
                addition = pointed[len(baseline) :]
                self.assertIn(f"../docs/ai-entry/{stack}.md", addition)
                self.assertIn("OPTIONAL", addition)
                self.assertEqual(
                    addition,
                    f"\nOPTIONAL: ../docs/ai-entry/{stack}.md describes available SDK entrypoints.\n",
                )
                self.assertIn(
                    "SDK dependency, vendored/copied source, or direct implementation are all accepted.",
                    baseline,
                )
                self.assertNotIn("../docs/ai-entry/", baseline)
                self.assertIn("uv venv --python 3.13 --allow-existing", baseline)
                self.assertIn("uv pip install --python .venv/bin/python", baseline)
                self.assertIn("2,000,000", baseline)
                self.assertIn("existing workspace", baseline)
                self.assertIn('"profile":"browser-session-v1"', baseline)

    def test_documents_clarifies_collection_visibility_without_changing_legacy(self):
        import choice_tasks

        choice = importlib.import_module("choice_tasks_v2")
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        old = choice_tasks.prompt("python", "a" * 40, tasks, "documents")
        text = choice.prompt(
            "python", "a" * 40, tasks, "baseline", scenario="documents"
        )
        self.assertIn("Viewer may list its tenant collection", old)
        self.assertNotIn("Viewer may list its tenant collection", text)
        self.assertIn("BOTH collection and detail", text)
        self.assertIn("143 HTTP assertions", text)
        self.assertEqual(choice.expected_assertions("documents"), 143)

    def test_ticket_prompt_contains_shape_and_contract_but_no_private_fixture_values(
        self,
    ):
        choice = importlib.import_module("choice_tasks_v2")
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        data = choice.ticket_fixture("private-pair-seed")
        contract = choice.contract_factory("tickets", "sdk-pointer", ticket_data=data)
        text = contract.prompt_builder("python", "a" * 40, tasks, "sdk-pointer")
        self.assertEqual(
            text,
            choice.prompt("python", "a" * 40, tasks, "sdk-pointer", scenario="tickets"),
        )
        for value in (
            "private-pair-seed",
            *(row["id"] for row in data),
            *(row["subject"] for row in data),
        ):
            self.assertNotIn(value, text)
        for required in (
            "/api/tickets/summary",
            "priorityTotal",
            "dispatcher",
            "tickets:read",
            "TICKETS_DATA_FILE",
            "TICKETS_UNAVAILABLE",
            "on each product request",
            "reject any nonempty query",
            "1..5",
            "no pagination",
            "AUTHORIZATION_UNAVAILABLE",
        ):
            self.assertIn(required, text)
        self.assertNotIn("/api/documents", text)
        self.assertNotIn("POST /api/tickets", text)

    def test_membership_provider_schema_is_explicit_in_both_ticket_conditions(self):
        choice = importlib.import_module("choice_tasks_v2")
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        requirements = (
            "Membership provider schema: a JSON object with required subjectId, tenantId and roles fields.",
            "subjectId and tenantId must be strings matching [A-Za-z0-9][A-Za-z0-9._:-]{0,63}.",
            "roles must be a JSON array of at most 16 unique strings, each matching [a-z][a-z0-9_-]{0,63}; [] is valid.",
            "a non-object value, missing/invalid required fields",
            "invalid identifier syntax, duplicate roles, more than 16 roles",
            "=> generic503 AUTHORIZATION_UNAVAILABLE.",
            "Validate provider JSON before authorization; these structural failures are503",
            "regardless of any policy API's invalid-principal403.",
            "For structurally valid membership, subjectId different from the true authenticated user's ID",
            "or no granted role (including [] or an ungranted role such as admin) =>403 FORBIDDEN.",
        )
        for stack in auth_eval.STACKS:
            baseline = choice.prompt(
                stack, "a" * 40, tasks, "baseline", scenario="tickets"
            )
            pointed = choice.prompt(
                stack, "a" * 40, tasks, "sdk-pointer", scenario="tickets"
            )
            with self.subTest(stack=stack):
                self.assertEqual(
                    pointed,
                    baseline
                    + f"\nOPTIONAL: ../docs/ai-entry/{stack}.md describes available SDK entrypoints.\n",
                )
                for text in (baseline, pointed):
                    for requirement in requirements:
                        self.assertIn(requirement, text)
                self.assertEqual(choice.expected_assertions("tickets"), 727)

    def test_seeded_fixture_is_fresh_deterministic_diverse_and_not_aliased(self):
        choice = importlib.import_module("choice_tasks_v2")
        one = choice.ticket_fixture("one")
        self.assertEqual(one, choice.ticket_fixture("one"))
        self.assertNotEqual(one, choice.ticket_fixture("two"))
        self.assertGreaterEqual(len(one), 9)
        self.assertTrue(any(row["ownerId"] != "demo-user" for row in one))
        self.assertTrue(any(row["tenantId"] != "tenant-a" for row in one))
        one[0]["subject"] = "changed"
        self.assertNotEqual(one, choice.ticket_fixture("one"))

    def test_private_fixture_is_created_late_and_uses_safe_private_prefix(self):
        choice = importlib.import_module("choice_tasks_v2")
        with tempfile.TemporaryDirectory(prefix="choice-v2-protocol-") as temporary:
            generated = Path(temporary).resolve()
            data = choice.ticket_fixture("late-private")
            contract = choice.contract_factory("tickets", "baseline", ticket_data=data)
            self.assertEqual(list(generated.iterdir()), [])
            self.assertNotIn("rows", contract.prompt_builder.__code__.co_freevars)
            expected = json.loads(json.dumps(data))
            data[0]["subject"] = "caller mutation after contract construction"
            self.assertIs(contract.artifact_checker, discovery.boundary_check)
            env = {}
            contract.prepare_grader(generated, env)
            self.assertEqual(set(env), {"CORE_MEMBERSHIP_FILE", "TICKETS_DATA_FILE"})
            tickets = Path(env["TICKETS_DATA_FILE"])
            self.assertTrue(tickets.name.startswith(".core-membership-tickets-"))
            self.assertEqual(tickets.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(tickets.read_text()), expected)
            self.assertEqual(
                tickets.read_bytes(), choice.ticket_fixture_bytes(expected)
            )
            self.assertEqual(
                tickets.read_bytes(),
                json.dumps(
                    expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8"),
            )
            self.assertEqual(
                json.loads(Path(env["CORE_MEMBERSHIP_FILE"]).read_text()),
                core_eval.VIEWER,
            )
            self.assertEqual(contract.profile, "guidance-tickets-http-v2")
            self.assertEqual(set(contract.ignored_parts), core_eval.CORE_CACHE_PARTS)

    def test_invalid_choices_and_invalid_fixture_fail_without_side_effects(self):
        choice = importlib.import_module("choice_tasks_v2")
        for scenario, condition in (("unknown", "baseline"), ("tickets", "unknown")):
            with self.subTest(scenario=scenario, condition=condition):
                with self.assertRaises(auth_eval.EvalError):
                    choice.contract_factory(scenario, condition)
                with self.assertRaises(auth_eval.EvalError):
                    choice.prompt(
                        "python", "a" * 40, None, condition, scenario=scenario
                    )
        with self.assertRaises(auth_eval.EvalError):
            choice.prompt("unknown", "a" * 40, None, "baseline", scenario="tickets")
        with self.assertRaises(auth_eval.EvalError):
            choice.contract_factory("tickets", "baseline").prompt_builder(
                "python", "a" * 40, None, "sdk-pointer"
            )
        with self.assertRaises(auth_eval.EvalError):
            choice.expected_assertions("unknown")
        with self.assertRaises(auth_eval.EvalError):
            choice.contract_factory("tickets", "baseline", ticket_data=[{"id": "bad"}])
        for bad_priority in (True, 0, 6, 2.5, float("nan"), float("inf"), 10**1000):
            invalid = choice.ticket_fixture("invalid-fixture")
            invalid[0]["priority"] = bad_priority
            with (
                self.subTest(priority_type=type(bad_priority).__name__),
                self.assertRaises(auth_eval.EvalError),
            ):
                choice.contract_factory("tickets", "baseline", ticket_data=invalid)


class TicketHandler(fixtures.CoreHandler):
    """Independent application fixture with real private-file reads per request."""

    def send_header(self, keyword, value):
        if self.server.fault == "cache-header" and keyword == "Cache-Control":
            return
        super().send_header(keyword, value)

    def error(self, status, code):
        if self.server.fault == "private-error" and code == "INVALID_LIST_QUERY":
            self.reply(
                status, {"error": {"code": code, "message": "private-provider-detail"}}
            )
        else:
            super().error(status, code)

    def do_GET(self):
        self.server.observed_paths.append(self.path)
        self.server.global_requests.append(auth_eval.request)
        cookie = self.headers.get("Cookie")
        if cookie not in self.server.sessions:
            self.error(401, "UNAUTHENTICATED")
            return
        path = urlsplit(self.path)
        if path.path in ("/api/profile", "/auth/me"):
            self.reply(200, {"user": fixtures.USER})
            return
        try:
            member = json.loads(self.server.membership_file.read_text())
            if not isinstance(member, dict) or member.get("unavailable"):
                raise ValueError
            roles = member["roles"]
            if (
                not isinstance(roles, list)
                or len(roles) > 16
                or not all(
                    isinstance(role, str)
                    and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", role)
                    for role in roles
                )
                or len(set(roles)) != len(roles)
                or not all(
                    isinstance(member.get(key), str)
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", member[key])
                    for key in ("subjectId", "tenantId")
                )
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, OSError):
            self.error(503, "AUTHORIZATION_UNAVAILABLE")
            return
        if self.server.fault == "ignore-revoke":
            roles = ["viewer"]
        if (
            self.server.fault == "role-header"
            and self.headers.get("X-Role") == "dispatcher"
        ):
            roles = ["dispatcher"]
        if member["subjectId"] != fixtures.USER["id"] or not {
            "viewer",
            "dispatcher",
        }.intersection(roles):
            self.error(403, "FORBIDDEN")
            return
        try:
            rows = json.loads(self.server.tickets_file.read_text())
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise TypeError
                for key in ("id", "tenantId", "ownerId"):
                    if not isinstance(row.get(key), str) or not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", row[key]
                    ):
                        raise ValueError
                subject, priority = row.get("subject"), row.get("priority")
                if (
                    row["id"] in seen
                    or not isinstance(subject, str)
                    or not 1 <= len(subject) <= 256
                    or len(subject.encode("utf-8")) > 1024
                    or any(ord(char) < 32 or ord(char) == 127 for char in subject)
                    or type(priority) not in (int, float)
                    or not math.isfinite(priority)
                    or priority != int(priority)
                    or not 1 <= priority <= 5
                    or type(row.get("closed")) is not bool
                ):
                    raise ValueError
                seen.add(row["id"])
        except (ValueError, TypeError, KeyError, OSError, UnicodeError):
            if self.server.fault == "cached-data":
                rows = self.server.initial_rows
            else:
                self.error(503, "TICKETS_UNAVAILABLE")
                return
        visible = [
            row
            for row in rows
            if row["tenantId"] == member["tenantId"]
            and ("dispatcher" in roles or row["ownerId"] == fixtures.USER["id"])
        ]
        if self.server.fault == "visibility":
            visible = [row for row in rows if row["tenantId"] == member["tenantId"]]

        def public(row):
            return {key: row[key] for key in ("id", "subject", "priority", "closed")}

        if path.path == "/api/tickets/summary":
            if path.query and self.server.fault != "summary-query":
                self.error(400, "INVALID_LIST_QUERY")
            else:
                values = rows if self.server.fault == "summary" else visible
                self.reply(
                    200,
                    {
                        "total": len(values),
                        "open": sum(not row["closed"] for row in values),
                        "closed": sum(row["closed"] for row in values),
                        "priorityTotal": sum(row["priority"] for row in values),
                    },
                )
        elif path.path == "/api/tickets":
            schema = ListingSchema(
                {
                    "id": "string",
                    "subject": "string",
                    "priority": "integer",
                    "closed": "boolean",
                },
                {"subject": "string", "priority": "integer", "closed": "boolean"},
            )
            try:
                raw = (
                    ""
                    if self.server.fault == "query"
                    and path.query.startswith("limit=01")
                    else path.query
                )
                result = page(
                    [public(row) for row in visible], parse_query(raw, schema), schema
                )
                if self.server.fault == "typed-output" and result["items"]:
                    result["items"][0]["closed"] = int(result["items"][0]["closed"])
                self.reply(200, result)
            except ListingError:
                self.error(400, "INVALID_LIST_QUERY")
        elif path.path.startswith("/api/tickets/"):
            row = next(
                (row for row in visible if row["id"] == path.path.rsplit("/", 1)[1]),
                None,
            )
            self.reply(200, public(row)) if row else self.error(403, "FORBIDDEN")
        else:
            self.error(404, "NOT_FOUND")


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="choice-v2-http-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.choice = importlib.import_module("choice_tasks_v2")
        self.number = 0

    def server(self, scenario="tickets", fault=None, seed="loopback-v2"):
        self.number += 1
        generated = self.root / str(self.number)
        generated.mkdir()
        data = self.choice.ticket_fixture(seed)
        contract = self.choice.contract_factory(scenario, "baseline", ticket_data=data)
        env = {}
        contract.prepare_grader(generated, env)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            TicketHandler if scenario == "tickets" else fixtures.CoreHandler,
        )
        server.sessions = {}
        server.membership_file = Path(env["CORE_MEMBERSHIP_FILE"])
        server.tickets_file = (
            Path(env["TICKETS_DATA_FILE"]) if scenario == "tickets" else None
        )
        server.fault = fault
        server.initial_rows = data
        server.observed_paths = []
        server.global_requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop)
        return server, contract, generated, env

    def grade(self, server, contract, generated, env):
        return contract.http_grader(
            generated,
            env,
            server.server_port,
            f"http://127.0.0.1:{server.server_port}",
            time.monotonic() + 15,
        )

    def test_documents_still_uses_all_143_real_http_assertions(self):
        server, contract, generated, env = self.server("documents")
        checks = self.grade(server, contract, generated, env)
        self.assertEqual(len(checks), 143)
        self.assertEqual(len(checks), self.choice.expected_assertions("documents"))

    def test_ticket_grader_accepts_real_http_for_multiple_fresh_paired_fixtures(self):
        original = auth_eval.request
        for seed in ("loopback-a", "loopback-b"):
            with self.subTest(seed=seed):
                server, contract, generated, env = self.server(seed=seed)
                checks = self.grade(server, contract, generated, env)
                self.assertEqual(len(checks), 727)
                self.assertEqual(
                    len(checks), self.choice.expected_assertions("tickets")
                )
                for required in (
                    "tickets-viewer-summary-body",
                    "tickets-dispatcher-summary-body",
                    "tickets-revoked-status",
                    "tickets-data-recovered-status",
                    "tickets-old-cookie-status",
                ):
                    self.assertIn(required, checks)
                self.assertEqual(
                    checks[:19],
                    auth_eval.http_grade(
                        server.server_port,
                        f"http://127.0.0.1:{server.server_port}",
                        time.monotonic() + 10,
                    ),
                )
                self.assertEqual(
                    server.tickets_file.read_bytes(),
                    self.choice.ticket_fixture_bytes(self.choice.ticket_fixture(seed)),
                )
                self.assertEqual(
                    json.loads(server.membership_file.read_text()), core_eval.VIEWER
                )
                self.assertIs(auth_eval.request, original)
                self.assertTrue(
                    all(request is original for request in server.global_requests)
                )

    def test_ticket_grader_rejects_deliberately_wrong_real_http_behaviors(self):
        for fault, code in (
            ("visibility", "tickets-viewer-list-body"),
            ("summary", "tickets-viewer-summary-body"),
            ("query", "tickets-invalid-query-status"),
            ("summary-query", "tickets-summary-query-status"),
            ("ignore-revoke", "tickets-revoked-status"),
            ("role-header", "tickets-forged-role-status"),
            ("cached-data", "tickets-data-unavailable-status"),
            ("typed-output", "tickets-viewer-list-body"),
            ("private-error", "tickets-invalid-query-body"),
            ("cache-header", "tickets-anonymous-no-store"),
        ):
            with self.subTest(fault=fault):
                server, contract, generated, env = self.server(fault=fault)
                initial_bytes = server.tickets_file.read_bytes()
                with self.assertRaisesRegex(auth_eval.EvalError, code):
                    self.grade(server, contract, generated, env)
                self.assertEqual(server.tickets_file.read_bytes(), initial_bytes)
                self.assertEqual(server.tickets_file.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    json.loads(server.membership_file.read_text()), core_eval.VIEWER
                )

    def test_ticket_requester_is_local_and_keeps_authentication_on_original_request(
        self,
    ):
        server, _, _, _ = self.server()
        original = auth_eval.request
        paths = []

        def requester(*args, **kwargs):
            self.assertIs(auth_eval.request, original)
            paths.append(args[2])
            return original(*args, **kwargs)

        checks = self.choice.tickets_http_grade(
            server.server_port,
            f"http://127.0.0.1:{server.server_port}",
            time.monotonic() + 15,
            server.membership_file,
            server.tickets_file,
            server.initial_rows,
            requester=requester,
        )
        self.assertEqual(len(checks), self.choice.expected_assertions("tickets"))
        self.assertNotIn("/api/profile", paths)
        self.assertNotIn("/auth/me", paths)
        self.assertIs(auth_eval.request, original)


if __name__ == "__main__":
    unittest.main()
