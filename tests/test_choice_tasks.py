"""Choice-task protocol and real loopback grader checks; no model calls."""

import importlib
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auth_eval
import core_discovery_eval as discovery
import core_eval
import core_transfer_eval as transfer
import test_core_eval as fixtures


class ProductHandler(fixtures.CoreHandler):
    """Serve exactly one product route family through the real HTTP fixture."""

    def do_GET(self):
        self.server.observed_paths.append(self.path)
        self.server.request_functions.append(auth_eval.request)
        if self.server.scenario == "notes":
            prefix = "/api/notes"
            if self.path == prefix or self.path.startswith(
                (prefix + "/", prefix + "?")
            ):
                self.path = "/api/documents" + self.path[len(prefix) :]
            elif self.path == "/api/documents" or self.path.startswith(
                ("/api/documents/", "/api/documents?")
            ):
                self.error(404, "NOT_FOUND")
                return
        super().do_GET()

    def do_POST(self):
        self.server.observed_paths.append(self.path)
        self.server.request_functions.append(auth_eval.request)
        super().do_POST()


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="choice-task-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.servers = 0

    def server(self, scenario="documents", fault=None):
        self.servers += 1
        membership = self.root / f"membership-{self.servers}.json"
        auth_eval.write_json(membership, core_eval.VIEWER)
        server = ThreadingHTTPServer(("127.0.0.1", 0), ProductHandler)
        server.sessions = {}
        server.membership_file = membership
        server.fault = fault
        server.scenario = scenario
        server.observed_paths = []
        server.request_functions = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop)
        return server

    def grade(self, server, grader):
        return grader(
            server.server_port,
            f"http://127.0.0.1:{server.server_port}",
            time.monotonic() + 10,
            server.membership_file,
        )

    def test_core_requester_injection_leaves_auth_grade_and_global_request_unchanged(
        self,
    ):
        server = self.server()
        original = auth_eval.request
        observed = []

        def requester(port, method, path, *args, **kwargs):
            observed.append((method, path))
            self.assertIs(auth_eval.request, original)
            return original(port, method, path, *args, **kwargs)

        checks = self.grade(
            server,
            lambda *args: core_eval.core_http_grade(*args, requester=requester),
        )
        self.assertEqual(len(checks), 143)
        self.assertEqual(observed.count(("POST", "/auth/login")), 1)
        self.assertEqual(observed.count(("POST", "/auth/logout")), 1)
        self.assertNotIn(("GET", "/auth/me"), observed)
        self.assertNotIn(("GET", "/api/profile"), observed)
        self.assertIs(auth_eval.request, original)

    def test_default_core_grader_and_old_transfer_keep_the_same_143_checks(self):
        original = auth_eval.request
        documents = self.server()
        notes = self.server("notes")
        expected = self.grade(documents, core_eval.core_http_grade)
        actual = self.grade(notes, transfer.notes_http_grade)
        self.assertEqual(len(expected), 143)
        self.assertEqual(actual, expected)
        self.assertIs(auth_eval.request, original)

    def test_choice_contracts_grade_both_real_route_families_without_global_changes(
        self,
    ):
        choice = importlib.import_module("choice_tasks")
        original = auth_eval.request
        expected = self.grade(self.server(), core_eval.core_http_grade)
        for scenario in choice.SCENARIOS:
            with self.subTest(scenario=scenario):
                server = self.server(scenario)
                contract = choice.contract_factory(scenario)
                checks = contract.http_grader(
                    self.root,
                    {"CORE_MEMBERSHIP_FILE": str(server.membership_file)},
                    server.server_port,
                    f"http://127.0.0.1:{server.server_port}",
                    time.monotonic() + 10,
                )
                self.assertEqual(checks, expected)
                self.assertEqual(len(checks), 143)
                self.assertIs(auth_eval.request, original)
                self.assertTrue(
                    all(request is original for request in server.request_functions)
                )
                product_paths = [
                    path
                    for path in server.observed_paths
                    if path.startswith(("/api/documents", "/api/notes"))
                ]
                self.assertTrue(product_paths)
                self.assertTrue(
                    all(path.startswith(f"/api/{scenario}") for path in product_paths)
                )

    def test_choice_grader_rejects_real_unscoped_totals_without_global_changes(self):
        choice = importlib.import_module("choice_tasks")
        original = auth_eval.request
        for scenario in choice.SCENARIOS:
            with self.subTest(scenario=scenario):
                server = self.server(scenario, "unscoped-total")
                with self.assertRaisesRegex(auth_eval.EvalError, "core-scoped-total"):
                    self.grade(
                        server,
                        lambda *args, scenario=scenario: choice.http_grade(
                            scenario, *args
                        ),
                    )
                self.assertIs(auth_eval.request, original)
                self.assertTrue(
                    all(request is original for request in server.request_functions)
                )


class ChoiceProtocolTests(unittest.TestCase):
    def test_supported_native_framework_is_fixed_without_prescribing_a_feature_sdk(
        self,
    ):
        contexts = {
            "python": "Python/FastAPI",
            "go": "Go/net/http",
            "java": "Java/Spring Boot",
            "rust": "Rust/Axum",
        }
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        import choice_tasks

        for stack, context in contexts.items():
            for scenario in choice_tasks.SCENARIOS:
                text = choice_tasks.prompt(stack, "a" * 40, tasks, scenario)
                self.assertTrue(
                    text.startswith(f"Build a {context} HTTP application"),
                    text.splitlines()[0],
                )
                self.assertNotIn("importing existing", text)

    def setUp(self):
        self.choice = importlib.import_module("choice_tasks")
        self.tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        self.commit = "a" * 40

    def test_both_prompts_are_neutral_and_ignore_mandatory_stack_instructions(self):
        self.assertEqual(self.choice.SCENARIOS, ("documents", "notes"))
        tasks = self.tasks | {
            "stacks": {
                stack: "MANDATORY_IMPORT_EXISTING_LIBRARIES_SENTINEL"
                for stack in auth_eval.STACKS
            }
        }
        for stack in auth_eval.STACKS:
            for scenario in self.choice.SCENARIOS:
                with self.subTest(stack=stack, scenario=scenario):
                    text = self.choice.prompt(stack, self.commit, tasks, scenario)
                    for unwanted in (
                        "MANDATORY_IMPORT_EXISTING_LIBRARIES_SENTINEL",
                        "reuse",
                        "import",
                        "public api",
                        "first read",
                        "first run",
                        "../README",
                        "catalog/package",
                        "feature_standards",
                    ):
                        self.assertNotIn(unwanted.lower(), text.lower())
                    for required in (
                        f"/api/{scenario}",
                        "2,000,000",
                        ".venv",
                        ".cache",
                        "target",
                        "bin",
                        "offline",
                        "CORE_MEMBERSHIP_FILE",
                        "run.json",
                        self.commit,
                    ):
                        self.assertIn(required, text)
                    if scenario == "notes":
                        self.assertNotIn("/api/documents", text)

    def test_scenarios_change_only_the_product_route_and_common_neutral_guidance(self):
        for stack in auth_eval.STACKS:
            documents = self.choice.prompt(stack, self.commit, self.tasks, "documents")
            notes = self.choice.prompt(stack, self.commit, self.tasks, "notes")
            self.assertEqual(documents.replace("/api/documents", "/api/notes"), notes)
            self.assertTrue(
                documents.partition("\n")[2].startswith(
                    discovery.prompt(
                        stack, self.commit, self.tasks, "discovery"
                    ).partition("\n")[2]
                )
            )

    def test_product_path_preserves_boundaries_and_query_values(self):
        for original, expected in (
            ("/api/documents", "/api/notes"),
            ("/api/documents/own-a", "/api/notes/own-a"),
            (
                "/api/documents?filter.name=/api/documents",
                "/api/notes?filter.name=/api/documents",
            ),
            ("/api/documents/own-a?x=1", "/api/notes/own-a?x=1"),
            ("/api/documents2", "/api/documents2"),
            ("/api/documents-other", "/api/documents-other"),
            ("/api/documents%2Fown-a", "/api/documents%2Fown-a"),
            ("/auth/login", "/auth/login"),
            ("/api/profile", "/api/profile"),
            ("/api/notes", "/api/notes"),
        ):
            with self.subTest(path=original):
                self.assertEqual(self.choice.product_path("notes", original), expected)
                self.assertEqual(
                    self.choice.product_path("documents", original), original
                )

    def test_contracts_keep_the_neutral_boundary_and_private_provider_fixture(self):
        for scenario in self.choice.SCENARIOS:
            with self.subTest(scenario=scenario):
                contract = self.choice.contract_factory(scenario)
                self.assertEqual(contract.profile, f"choice-{scenario}-http-v1")
                self.assertIs(contract.prompt_builder, self.choice.prompt)
                self.assertIs(contract.artifact_checker, discovery.boundary_check)
                self.assertIs(contract.prepare_grader, core_eval.create_membership_file)
                self.assertEqual(
                    set(contract.ignored_parts), core_eval.CORE_CACHE_PARTS
                )

    def test_invalid_selections_fail_before_prompt_grader_or_fixture_work(self):
        with (
            patch.object(
                discovery, "prompt", side_effect=AssertionError("prompt used")
            ),
            patch.object(
                core_eval, "core_http_grade", side_effect=AssertionError("graded")
            ),
            patch.object(
                core_eval, "trial_contract", side_effect=AssertionError("fixture")
            ),
        ):
            for stack, scenario in (("python", "unknown"), ("unknown", "notes")):
                with (
                    self.subTest(stack=stack, scenario=scenario),
                    self.assertRaises(auth_eval.EvalError),
                ):
                    self.choice.prompt(stack, self.commit, None, scenario)
            for call in (
                lambda: self.choice.product_path("unknown", "/api/documents"),
                lambda: self.choice.http_grade("unknown", 1, "origin", 2, None),
                lambda: self.choice.contract_factory("unknown"),
            ):
                with self.assertRaises(auth_eval.EvalError):
                    call()


if __name__ == "__main__":
    unittest.main()
