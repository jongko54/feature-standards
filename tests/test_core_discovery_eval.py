"""Discovery bookkeeping and guard tests; no models, servers or toolchain builds."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auth_eval
import core_discovery_eval as discovery
import core_eval
import test_reading_orchestration as fixtures

COMMIT = fixtures.COMMIT


class DiscoveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="discovery-boundary-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.generated = self.root / "generated"
        self.generated.mkdir()
        auth_eval.write_json(
            self.generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": COMMIT,
            },
        )
        auth_eval.write_json(
            self.generated / "run.json",
            {
                "build": [],
                "start": {"argv": ["python", "app.py"], "cwd": "."},
            },
        )
        (self.generated / "app.py").write_text("print('independent implementation')\n")

    def test_prompt_and_instructions_offer_no_forced_reuse_or_starting_path(self):
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        for stack in auth_eval.STACKS:
            text = discovery.prompt(stack, COMMIT, tasks, "discovery")
            for unwanted in (
                "import",
                "reuse",
                "existing",
                "core parser",
                "public api",
                "consumer",
                "../README",
                "catalog/package",
                "feature_standards",
            ):
                self.assertNotIn(unwanted.lower(), text.lower())
            for required in (
                "/auth/login",
                "/auth/logout",
                "/api/profile",
                "/auth/me",
                "/api/documents",
                "CORE_MEMBERSHIP_FILE",
                "INVALID_LIST_QUERY",
                "run.json",
                "integration.json",
                COMMIT,
            ):
                self.assertIn(required, text)
        for unwanted in ("reuse", "import", "existing", "package"):
            self.assertNotIn(unwanted, discovery.INSTRUCTIONS.lower())

    def test_independent_implementation_passes_boundary_without_library_imports(self):
        discovery.boundary_check(self.generated, "python", {}, COMMIT)
        with self.assertRaisesRegex(auth_eval.EvalError, "library-reuse"):
            core_eval.core_reuse_check(self.generated, "python", {}, COMMIT)

    def test_wrong_provenance_and_unsafe_program_shapes_fail_closed(self):
        path = self.generated / "integration.json"
        original = path.read_bytes()
        path.write_text(
            json.dumps(
                {
                    "stack": "python",
                    "profile": "browser-session-v1",
                    "source_commit": "b" * 40,
                }
            )
        )
        with self.assertRaises(auth_eval.EvalError):
            discovery.boundary_check(self.generated, "python", {}, COMMIT)
        path.write_bytes(original)
        source = self.generated / "app.py"
        source.unlink()
        source.symlink_to(self.root / "outside.py")
        with self.assertRaisesRegex(auth_eval.EvalError, "symlink"):
            discovery.boundary_check(self.generated, "python", {}, COMMIT)
        source.unlink()
        os.mkfifo(source)
        with self.assertRaises(auth_eval.EvalError):
            discovery.boundary_check(self.generated, "python", {}, COMMIT)

    def test_reference_bytes_and_file_sizes_are_still_guarded(self):
        (self.root / "reference.py").write_text("changed reference")
        with self.assertRaisesRegex(auth_eval.EvalError, "source-modified"):
            discovery.boundary_check(self.generated, "python", {}, COMMIT)
        reference = auth_eval.fingerprint(self.root)
        (self.generated / "app.py").write_bytes(b"x" * 2_000_001)
        with self.assertRaisesRegex(auth_eval.EvalError, "too-large"):
            discovery.boundary_check(self.generated, "python", reference, COMMIT)

    def test_run_shape_and_working_directory_cannot_escape_program(self):
        path = self.generated / "run.json"
        for command in (
            {"argv": "python app.py", "cwd": "."},
            {"argv": ["python", "app.py"], "cwd": ".."},
        ):
            path.write_text(json.dumps({"build": [], "start": command}))
            with self.subTest(command=command), self.assertRaises(auth_eval.EvalError):
                discovery.boundary_check(self.generated, "python", {}, COMMIT)

    def test_auth_only_reuse_is_visible_without_claiming_core_route_connections(self):
        (self.generated / "app.py").write_text(
            "from feature_auth import create_app, current_user\n"
            "app=create_app()\ndef profile(request): return current_user(request)\n"
        )
        evidence = discovery.feature_evidence(self.generated, {}, "python", COMMIT)
        self.assertTrue(evidence["auth"]["passed"])
        self.assertIs(evidence["authorization"], False)
        self.assertIs(evidence["listing"], False)
        self.assertFalse(
            discovery.reading.static_reuse(self.generated, {}, "python", COMMIT)[
                "passed"
            ]
        )
        (self.generated / "hints.py").write_text(
            "# Policy and parse_query names alone are weak candidates\n"
        )
        evidence = discovery.feature_evidence(self.generated, {}, "python", COMMIT)
        self.assertEqual(evidence["authorization"], "candidate")
        self.assertEqual(evidence["listing"], "candidate")
        self.assertEqual(evidence["route_review"], "pending-independent-source-review")

    def test_exact_source_copy_is_reported_without_blocking_http_eligibility(self):
        content = ("# source implementation\n" * 20).encode()
        (self.generated / "app.py").write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        source = {
            "libraries/python/feature_standards/listing.py": digest,
            "implementations/python-fastapi/feature_auth/auth.py": digest,
            "libraries/go/authorization/policy_test.go": digest,
            "implementations/go-net-http/store_test.go": digest,
        }
        discovery.boundary_check(self.generated, "python", {}, COMMIT)
        evidence = discovery.copy_evidence(self.generated, source)
        self.assertEqual(len(evidence["auth"]), 1)
        self.assertEqual(len(evidence["core"]), 1)
        self.assertFalse(evidence["api_reuse_proven"])
        (self.generated / "app.py").rename(
            self.generated / "renamed-implementation.txt"
        )
        self.assertEqual(discovery.copy_evidence(self.generated, source), evidence)

    def test_public_summary_does_not_emit_raw_commands_outputs_or_file_paths(self):
        row = {
            "stack": "python",
            "passed": True,
            "checks": ["http"],
            "copy_evidence": {"auth": ["/private/do-not-publish"], "core": []},
            "reading_evidence": {
                "documents": [{"path": "/private/do-not-publish"}],
                "command": "cat /private/do-not-publish",
            },
            "static_reuse": {"passed": False, "error_code": "/private/do-not-publish"},
        }
        report = discovery.summarize([row], {"source_commit": COMMIT}, 4)
        self.assertNotIn("/private/do-not-publish", json.dumps(report))
        self.assertNotIn("comparisons", report)
        self.assertEqual(report["runs"][0]["exact_copy_counts"], {"auth": 1, "core": 0})

    def test_instruction_overlay_recomputes_effective_source_and_agents_hashes(self):
        instructions = self.root / "AGENTS.md"
        instructions.write_text("Reuse existing packages.\n")
        upstream = auth_eval.digest_hashes(auth_eval.fingerprint(self.root))
        metadata = discovery.neutralize(
            self.root,
            {
                "source_sha256": upstream,
                "implementation_source_sha256": upstream,
            },
        )
        self.assertEqual(instructions.read_text(), discovery.INSTRUCTIONS)
        self.assertEqual(metadata["upstream_source_sha256"], upstream)
        self.assertNotEqual(metadata["source_sha256"], upstream)
        self.assertEqual(
            metadata["source_sha256"],
            auth_eval.digest_hashes(auth_eval.fingerprint(self.root)),
        )
        self.assertEqual(
            metadata["discovery_agents_sha256"],
            hashlib.sha256(instructions.read_bytes()).hexdigest(),
        )


class DiscoveryOrchestrationTests(fixtures.ReadingOrchestrationTests):
    """Borrow only the external model/source fixtures, not the other suite's tests."""

    # The inherited reading tests have a different contract and must not run here.
    test_24_serial_attempts_share_source_and_preserve_results_with_real_summaries = None
    test_stdout_only_terminal_errors_stop_after_one_preserved_attempt = None
    test_postprocessing_failure_keeps_each_completed_attempt_and_original_bytes = None

    def model_execute(self, argv, cwd, env, log, deadline, stdin=None, stderr_log=None):
        self.assertFalse(self.model_active)
        task = stdin.decode()
        stack = next(s for s in auth_eval.STACKS if f'"stack":"{s}"' in task)
        self.executions.append((stack, "discovery", task))
        self.progress_counts.append(
            json.loads((self.output / "progress.json").read_text())[
                "actual_model_calls"
            ]
        )
        (cwd / "app.py").write_text("# independent HTTP fixture\n")
        auth_eval.write_json(
            cwd / "integration.json",
            {
                "stack": stack,
                "profile": "browser-session-v1",
                "source_commit": COMMIT,
            },
        )
        auth_eval.write_json(
            cwd / "run.json",
            {
                "build": [],
                "start": {"argv": ["fixture-server"], "cwd": "."},
            },
        )
        event = (
            {"type": "error", "message": self.terminal}
            if self.terminal
            else {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 20,
                    "output_tokens": 10,
                },
            }
        )
        log.write_text(json.dumps(event) + "\n")
        stderr_log.write_text("")
        return 1 if self.terminal else 0

    def invoke_discovery(self):
        actual_write = auth_eval.write_json

        def preserve(path, value):
            actual_write(path, value)
            if path.name == "result.json":
                self.original_results[path] = path.read_bytes()

        argv = [
            "core_discovery_eval.py",
            "--artifact",
            str(self.artifact),
            "--artifact-sha256",
            self.artifact_sha256,
            "--source-commit",
            COMMIT,
            "--model",
            "fixture-model",
            "--output",
            str(self.output),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(discovery.shutil, "which", return_value="/fixture/codex"),
            patch.object(core_eval, "freeze_sources", side_effect=self.freeze),
            patch.object(auth_eval, "execute", side_effect=self.model_execute),
            patch.object(auth_eval, "grade", side_effect=self.grade) as grade,
            patch.object(auth_eval.subprocess, "run", side_effect=self.subprocess_run),
            patch.object(auth_eval, "write_json", side_effect=preserve),
            redirect_stdout(StringIO()),
        ):
            result = discovery.main()
        return result, grade.call_count

    def test_four_nonreuse_apps_receive_same_http_checks_and_separate_summary(self):
        status, graded = self.invoke_discovery()
        self.assertEqual(status, 0)
        self.assertEqual(graded, 4)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["suite"], "core-discovery-v1")
        self.assertEqual(summary["actual_model_calls"], 4)
        self.assertEqual(summary["passed"], 4)
        self.assertNotIn("comparisons", summary)
        self.assertEqual(self.progress_counts, [0, 1, 2, 3])
        self.assertEqual(len(self.templates), 1)
        for row in summary["runs"]:
            self.assertEqual(row["http_assertions"], 143)
            self.assertFalse(row["static_reuse"]["passed"])
            self.assertEqual(row["tokens"]["total_tokens"], 110)
        self.assert_originals_preserved()

    def test_stdout_terminal_error_stops_and_preserves_original_result(self):
        self.terminal = "usage limit reached /private/do-not-publish"
        status, graded = self.invoke_discovery()
        self.assertEqual(status, 1)
        self.assertEqual(graded, 0)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["actual_model_calls"], 1)
        self.assertEqual(summary["planned_model_calls"], 4)
        self.assertEqual(summary["blocked"], "cli-rate-limited")
        self.assertNotIn("/private/do-not-publish", json.dumps(summary))
        self.assert_originals_preserved()

    def test_zero_exit_stdout_terminal_error_stops_and_preserves_original_outcome(self):
        self.terminal = "usage limit reached"
        write_terminal_trace = self.model_execute

        def zero_exit(*args, **kwargs):
            write_terminal_trace(*args, **kwargs)
            return 0

        with patch.object(self, "model_execute", side_effect=zero_exit):
            status, graded = self.invoke_discovery()
        self.assertEqual(status, 1)
        self.assertEqual(graded, 0)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["actual_model_calls"], 1)
        self.assertEqual(summary["planned_model_calls"], 4)
        self.assertEqual(summary["blocked"], "cli-rate-limited")
        self.assertFalse(summary["complete"])
        self.assertEqual(
            summary["runs"][0]["original_error_code"], "agent-trace-incomplete"
        )
        self.assertEqual(self.progress_counts, [0])
        self.assert_originals_preserved()

    def test_postprocessing_error_preserves_http_outcome_and_completed_attempts(self):
        with patch.object(
            discovery,
            "reading_evidence",
            side_effect=ValueError("/private/do-not-publish"),
        ):
            status, graded = self.invoke_discovery()
        self.assertEqual(status, 0)
        self.assertEqual(graded, 4)
        summary = json.loads((self.output / "summary.json").read_text())
        progress = json.loads((self.output / "progress.json").read_text())
        self.assertEqual(summary["actual_model_calls"], 4)
        self.assertEqual(progress["actual_model_calls"], 4)
        self.assertEqual(summary["passed"], 0)
        self.assertTrue(all(row["original_http_passed"] for row in summary["runs"]))
        self.assertTrue(
            all(row["error_code"] == "postprocessing-failed" for row in summary["runs"])
        )
        self.assertNotIn("/private/do-not-publish", json.dumps(summary))
        self.assert_originals_preserved()


if __name__ == "__main__":
    unittest.main()
