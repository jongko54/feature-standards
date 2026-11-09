"""Choice denominator and scheduling tests; no live model invocations."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auth_eval
import core_choice_eval as choice
import core_eval
import test_reading_orchestration as fixtures

COMMIT = fixtures.COMMIT


class ChoiceMeasurementTests(unittest.TestCase):
    def test_32_cells_are_balanced_and_repeat_order_is_reversed(self):
        models = ("first-model", "second-model")
        stacks = ("python", "go", "java", "rust")
        cases = choice.schedule(models, stacks, ("documents", "notes"), 2)
        self.assertEqual(len(cases), 32)
        self.assertEqual(len(set(cases)), 32)
        for stack in stacks:
            first = [(m, s) for m, b, s, r in cases if b == stack and r == 1]
            second = [(m, s) for m, b, s, r in cases if b == stack and r == 2]
            self.assertEqual(second, first[::-1])
        self.assertEqual(
            len(
                {
                    tuple((m, s) for m, b, s, r in cases if b == stack and r == 1)
                    for stack in stacks
                }
            ),
            4,
        )

    def trace(self, events):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name).resolve() / "trace.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events))
        return path

    def test_started_timeout_or_failed_build_is_still_a_supported_opportunity(self):
        trace = self.trace([{"type": "turn.started"}])
        self.assertIs(choice.started_state(trace)["supported_started"], True)

    def test_prework_model_error_is_infrastructure_but_midwork_rate_limit_stays_started(
        self,
    ):
        unsupported = self.trace(
            [
                {"type": "turn.started"},
                {"type": "error", "message": "model not supported"},
            ]
        )
        state = choice.started_state(unsupported)
        self.assertIs(state["supported_started"], False)
        self.assertEqual(state["infrastructure_error"], "cli-model-unavailable")
        midwork = self.trace(
            [
                {"type": "turn.started"},
                {"type": "item.completed", "item": {"type": "command_execution"}},
                {"type": "error", "message": "rate_limit_exceeded"},
            ]
        )
        state = choice.started_state(midwork)
        self.assertIs(state["supported_started"], True)
        self.assertEqual(state["infrastructure_error"], "cli-rate-limited")

    def test_missing_trace_start_is_unknown_not_a_zero_choice(self):
        trace = self.trace([])
        self.assertIsNone(choice.started_state(trace)["supported_started"])

    def test_tool_output_is_not_a_terminal_error_and_completed_turn_is_a_start(self):
        trace = self.trace(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": "error: model not supported; rate_limit_exceeded",
                    },
                },
                {"type": "turn.completed"},
            ]
        )
        state = choice.started_state(trace)
        self.assertIs(state["supported_started"], True)
        self.assertIsNone(state["infrastructure_error"])
        self.assertFalse(state["terminal_error"])

    def test_missing_trace_and_malformed_event_types_remain_unknown(self):
        self.assertIsNone(
            choice.started_state(Path("/nonexistent-choice-test-trace"))[
                "supported_started"
            ]
        )
        trace = self.trace([{"type": []}, "not an event"])
        self.assertIsNone(choice.started_state(trace)["supported_started"])

    def test_explicit_auth_and_model_unavailable_before_work_are_not_choices(self):
        for message, expected in (
            ("Unauthorized", "cli-authentication-failed"),
            ("authentication required", "cli-authentication-failed"),
            ("model unavailable", "cli-model-unavailable"),
            ("unsupported model", "cli-model-unavailable"),
        ):
            with self.subTest(message=message):
                trace = self.trace(
                    [{"type": "turn.started"}, {"type": "error", "message": message}]
                )
                result = choice.started_state(trace)
                self.assertIs(result["supported_started"], False)
                self.assertEqual(result["infrastructure_error"], expected)

    def test_completed_agent_does_not_promote_stderr_to_a_terminal_cli_error(self):
        trace = self.trace(
            [
                {"type": "turn.started"},
                {"type": "item.completed", "item": {"type": "command_execution"}},
                {"type": "turn.completed"},
            ]
        )
        result = choice.started_state(trace, "error 401 rate limit reached")
        self.assertIs(result["supported_started"], True)
        self.assertIsNone(result["infrastructure_error"])
        self.assertIsNone(result["terminal_reason_source"])

    def test_terminal_classification_retains_its_trace_or_stderr_origin(self):
        trace = self.trace(
            [
                {"type": "turn.started"},
                {"type": "error", "message": "model not supported"},
            ]
        )
        result = choice.started_state(trace, "error 401")
        self.assertEqual(result["infrastructure_error"], "cli-model-unavailable")
        self.assertEqual(result["terminal_reason_source"], "trace")
        trace = self.trace([{"type": "turn.started"}])
        result = choice.started_state(trace, "error 401")
        self.assertIs(result["supported_started"], False)
        self.assertEqual(result["infrastructure_error"], "cli-authentication-failed")
        self.assertEqual(result["terminal_reason_source"], "stderr")

    def row(self, sequence, *, started=True, passed=True):
        return {
            "trial": f"m01-python-documents-trial-{sequence}",
            "requested_model": "first-model",
            "stack": "python",
            "condition": "documents",
            "repeat": sequence,
            "sequence": sequence,
            "passed": passed,
            "original_http_passed": passed,
            "original_result_sha256": f"{sequence:064x}",
            "original_error_code": None if passed else "build-failed",
            "checks": list(range(143)) if passed else [],
            "source_unchanged": True,
            "retained_source_unchanged": True,
            "started_state": {"supported_started": started},
            "source_inventory": {"files": [], "excluded": [], "reviewable": True},
        }

    def review(self, row, *classes):
        return {
            "trial": row["trial"],
            "original_result_sha256": row["original_result_sha256"],
            "features": {
                feature: {"classification": classification, "evidence": []}
                for feature, classification in zip(
                    choice.FEATURES, classes, strict=True
                )
            },
        }

    def test_unreviewed_supported_attempts_have_unknown_choices_and_null_rates(self):
        rows = [self.row(1), self.row(2, passed=False)]
        result = choice.summarize(rows, {}, 32)
        self.assertEqual(result["all_attempts"], 2)
        self.assertEqual(result["supported_started"], 2)
        self.assertEqual(result["choice_unknown"], 2)
        self.assertEqual(result["library_connected_full"], 0)
        self.assertIsNone(result["rates"]["confirmed_full_reuse_lower_bound"])
        self.assertIsNone(result["rates"]["verified_full_reuse_lower_bound"])
        self.assertIsNone(result["runs"][0]["choice_review"])

    def test_all_uncertain_reviews_do_not_turn_unknown_rates_into_zero(self):
        row = self.row(1)
        review = self.review(row, *("uncertain",) * 3)
        result = choice.summarize([row], {}, 1, {row["trial"]: review})
        self.assertEqual(result["reviewed_supported"], 1)
        self.assertEqual(result["complete_choice_reviews"], 0)
        self.assertEqual(result["choice_unknown"], 1)
        for key in (
            "confirmed_full_reuse_lower_bound",
            "verified_full_reuse_lower_bound",
            "full_reuse_among_complete_reviews",
        ):
            self.assertIsNone(result["rates"][key])

    def test_partial_feature_evidence_does_not_claim_a_complete_choice_rate(self):
        row = self.row(1)
        review = self.review(row, "library_connected", "uncertain", "uncertain")
        result = choice.summarize([row], {}, 1, {row["trial"]: review})
        self.assertEqual(result["partial_library_connected"], 1)
        self.assertEqual(result["feature_classes"]["auth"]["library_connected"], 1)
        self.assertEqual(result["choice_unknown"], 1)
        self.assertIsNone(result["rates"]["confirmed_full_reuse_lower_bound"])
        self.assertIsNone(result["rates"]["verified_full_reuse_lower_bound"])
        review["features"]["authorization"]["classification"] = "direct_independent"
        review["features"]["listing"]["classification"] = "direct_independent"
        result = choice.summarize([row], {}, 1, {row["trial"]: review})
        self.assertEqual(result["partial_library_connected"], 1)
        self.assertEqual(result["choice_unknown"], 0)
        self.assertEqual(result["rates"]["confirmed_full_reuse_lower_bound"], 0.0)

    def test_full_partial_working_and_infrastructure_denominators_are_distinct(self):
        rows = [
            self.row(1),
            self.row(2, passed=False),
            self.row(3),
            self.row(4),
            self.row(5, started=False, passed=False),
            self.row(6, started=None, passed=False),
        ]
        reviews = {
            row["trial"]: self.review(row, *classes)
            for row, classes in (
                (rows[0], ("library_connected",) * 3),
                (rows[1], ("transitive_library_connected",) * 3),
                (
                    rows[2],
                    ("library_connected", "direct_independent", "direct_independent"),
                ),
            )
        }
        result = choice.summarize(rows, {}, 32, reviews)
        for key, expected in {
            "all_attempts": 6,
            "supported_started": 4,
            "start_unknown": 1,
            "prework_infrastructure": 1,
            "choice_unknown": 1,
            "library_connected_full": 2,
            "partial_library_connected": 1,
            "verified_full_reuse": 1,
        }.items():
            self.assertEqual(result[key], expected, key)
        self.assertEqual(result["rates"]["confirmed_full_reuse_lower_bound"], 0.5)
        self.assertEqual(result["rates"]["verified_full_reuse_lower_bound"], 0.25)
        self.assertEqual(result["rates"]["full_reuse_among_complete_reviews"], 2 / 3)

    def test_mixed_and_uncertain_features_do_not_become_verified_full_reuse(self):
        row = self.row(1)
        review = self.review(row, "mixed", "library_connected", "uncertain")
        result = choice.summarize([row], {}, 1, {row["trial"]: review})
        self.assertEqual(result["mixed_sessions"], 1)
        self.assertEqual(result["partial_library_connected"], 1)
        self.assertEqual(result["choice_unknown"], 1)
        self.assertEqual(result["verified_full_reuse"], 0)
        self.assertEqual(result["feature_classes"]["auth"]["mixed"], 1)

    def test_zero_supported_denominator_is_null_even_with_a_review(self):
        row = self.row(1, started=False, passed=False)
        review = self.review(row, *("library_connected",) * 3)
        result = choice.summarize([row], {}, 32, {row["trial"]: review})
        self.assertEqual(result["supported_started"], 0)
        self.assertIsNone(result["rates"]["confirmed_full_reuse_lower_bound"])

    def test_full_review_and_http_pass_do_not_override_changed_reference_source(self):
        row = self.row(1)
        row["retained_source_unchanged"] = False
        review = self.review(row, *("library_connected",) * 3)
        result = choice.summarize([row], {}, 1, {row["trial"]: review})
        self.assertEqual(result["library_connected_full"], 1)
        self.assertEqual(result["verified_full_reuse"], 0)


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="choice-inventory-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.generated = self.root / "generated"
        self.generated.mkdir()

    def test_inventory_publishes_metadata_only_and_excludes_unsafe_or_large_files(self):
        (self.generated / "app.py").write_text("private source marker\nsecond line\n")
        (self.generated / "go.mod").write_text("module example.test\n")
        (self.generated / "large.py").write_bytes(b"x" * 2_000_001)
        (self.generated / "server").write_bytes(b"binary")
        (self.generated / "link.py").symlink_to(self.generated / "app.py")
        os.mkfifo(self.generated / "pipe.py")
        (self.generated / ".env").write_text("secret-value")
        (self.generated / "bin").mkdir()
        (self.generated / "bin/server").write_bytes(b"binary")
        inventory = choice.source_inventory(self.generated)
        self.assertTrue(inventory["reviewable"])
        self.assertEqual(
            [item["path"] for item in inventory["files"]], ["app.py", "go.mod"]
        )
        self.assertEqual(inventory["files"][0]["lines"], 2)
        self.assertEqual(
            inventory["files"][0]["sha256"],
            hashlib.sha256((self.generated / "app.py").read_bytes()).hexdigest(),
        )
        reasons = {item["path"]: item["reason"] for item in inventory["excluded"]}
        self.assertEqual(reasons["large.py"], "oversized")
        self.assertEqual(reasons["link.py"], "symlink")
        self.assertEqual(reasons["pipe.py"], "nonregular")
        self.assertEqual(reasons["bin"], "cache-or-build-output")
        self.assertEqual(reasons[".env"], "private-fixture-or-environment")
        public = json.dumps(inventory)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("private source marker", public)
        self.assertNotIn("secret-value", public)


class ChoiceOrchestrationTests(unittest.TestCase):
    """Real run_trial bookkeeping with only external execution boundaries replaced."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="choice-orchestration-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.artifact = self.base / "candidate.tgz"
        self.artifact.write_bytes(fixtures.archive_bytes())
        self.artifact_hash = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.output = self.base / "runs"
        self.models = ("provider/first-model", "second-model")
        self.calls = []
        self.templates = []
        self.originals = {}
        self.progress = []
        self.active = False
        self.terminal = None
        self.prework = False
        self.stderr = ""

    def freeze(self, root, destination, catalog, *, commit):
        self.assertEqual(commit, COMMIT)
        destination.mkdir(mode=0o700)
        (destination / "README.md").write_text("Fixed reference bytes.\n")
        implementation = auth_eval.fingerprint(destination)
        core_eval.extract_archive(catalog, destination / "catalog")
        self.templates.append(destination)
        return {
            "source_commit": commit,
            "source_dirty": False,
            "implementation_source_sha256": auth_eval.digest_hashes(implementation),
            "source_sha256": auth_eval.digest_hashes(
                auth_eval.fingerprint(destination)
            ),
            "catalog_snapshot_sha256": auth_eval.digest_hashes(
                auth_eval.fingerprint(destination / "catalog")
            ),
        }

    def fake_subprocess(self, argv, *args, **kwargs):
        if argv[:2] == ["codex", "--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"fixture-cli 0.167.0\n")
        if argv[:1] == ["git"] and "init" in argv:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError("Unexpected external subprocess")

    def execute(self, argv, cwd, env, log, deadline, stdin=None, stderr_log=None):
        self.assertFalse(self.active)
        self.active = True
        try:
            self.assertEqual(argv[:2], ["codex", "exec"])
            model = argv[argv.index("--model") + 1]
            prompt = stdin.decode()
            stack = next(
                stack for stack in auth_eval.STACKS if f'"stack":"{stack}"' in prompt
            )
            scenario = "notes" if "/api/notes" in prompt else "documents"
            self.calls.append((model, stack, scenario))
            self.progress.append(
                json.loads((self.output / "progress.json").read_text())[
                    "actual_model_calls"
                ]
            )
            extension = dict(zip(auth_eval.STACKS, ("py", "go", "java", "rs")))[stack]
            (cwd / f"app.{extension}").write_text(
                "// private generated source marker\nroute calls a function\n"
            )
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
                {"build": [], "start": {"argv": ["fake-server"], "cwd": "."}},
            )
            events = [{"type": "turn.started"}]
            if not self.prework:
                events.append(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "cat ../README.md",
                            "aggregated_output": "private tool output marker",
                            "exit_code": 0,
                        },
                    }
                )
            if self.terminal:
                events.append({"type": "error", "message": self.terminal})
            else:
                events.append(
                    {
                        "type": "turn.completed",
                        "model": model,
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                        },
                    }
                )
            log.write_text("".join(json.dumps(event) + "\n" for event in events))
            stderr_log.write_text(self.stderr)
            return 1 if self.terminal else 0
        finally:
            self.active = False

    def invoke(self, *, evidence=None, grade_error=None, extra=()):
        write_json = auth_eval.write_json

        def record(path, value):
            write_json(path, value)
            if path.name == "result.json":
                self.originals[path] = path.read_bytes()

        argv = [
            "--artifact",
            str(self.artifact),
            "--artifact-sha256",
            self.artifact_hash,
            "--source-commit",
            COMMIT,
            "--models",
            *self.models,
            "--output",
            str(self.output),
            *extra,
        ]
        with ExitStack() as patches:
            patches.enter_context(
                patch.object(choice.shutil, "which", return_value="/fixture/codex")
            )
            patches.enter_context(
                patch.object(core_eval, "freeze_sources", side_effect=self.freeze)
            )
            patches.enter_context(
                patch.object(auth_eval, "execute", side_effect=self.execute)
            )
            patches.enter_context(
                patch.object(
                    auth_eval,
                    "grade",
                    return_value=[f"fixture-{index}" for index in range(143)],
                    side_effect=grade_error,
                )
            )
            patches.enter_context(
                patch.object(
                    auth_eval.subprocess, "run", side_effect=self.fake_subprocess
                )
            )
            patches.enter_context(
                patch.object(choice.subprocess, "check_output", return_value=COMMIT)
            )
            patches.enter_context(
                patch.object(auth_eval, "write_json", side_effect=record)
            )
            if evidence is not None:
                patches.enter_context(
                    patch.object(
                        choice.reading_trace, "reading_evidence", side_effect=evidence
                    )
                )
            patches.enter_context(redirect_stdout(io.StringIO()))
            return choice.main(argv)

    def assert_originals(self):
        self.assertTrue(self.originals)
        for path, data in self.originals.items():
            self.assertEqual(path.read_bytes(), data)
            analysis = json.loads(path.with_name("analysis.json").read_text())
            self.assertEqual(
                analysis["original_result_sha256"], hashlib.sha256(data).hexdigest()
            )

    def test_32_serial_calls_share_one_source_and_preserve_originals_without_claiming_reuse(
        self,
    ):
        self.assertEqual(self.invoke(), 0)
        summary = json.loads((self.output / "summary.json").read_text())
        expected = choice.schedule(
            self.models, auth_eval.STACKS, ("documents", "notes"), 2
        )
        self.assertEqual(
            self.calls,
            [(model, stack, scenario) for model, stack, scenario, _ in expected],
        )
        self.assertEqual(len(self.templates), 1)
        self.assertEqual(self.progress, list(range(32)))
        self.assertEqual(summary["all_attempts"], 32)
        self.assertEqual(summary["supported_started"], 32)
        self.assertEqual(summary["choice_unknown"], 32)
        self.assertEqual(summary["passed"], 32)
        self.assertTrue(summary["complete"])
        self.assertFalse(summary["availability_probes_included"])
        self.assertEqual(len(summary["groups"]), 16)
        self.assertTrue(all(group["all_attempts"] == 2 for group in summary["groups"]))
        self.assertIsNone(summary["rates"]["confirmed_full_reuse_lower_bound"])
        self.assertTrue(
            all(row["trial"].startswith(("m01-", "m02-")) for row in summary["runs"])
        )
        self.assertEqual(
            len(
                {
                    row["source_sha256"]
                    for row in map(json.loads, self.originals.values())
                }
            ),
            1,
        )
        public = json.dumps(summary)
        for private in (
            str(self.base),
            "private generated source marker",
            "private tool output marker",
        ):
            self.assertNotIn(private, public)
        rows, _, planned, blocked = choice.retained_rows(self.output)
        self.assertEqual((len(rows), planned, blocked), (32, 32, None))
        self.assert_originals()

    def test_postprocessing_failure_does_not_replace_successful_http_outcomes(self):
        self.assertEqual(
            self.invoke(
                evidence=ValueError("private evidence failure"),
                extra=("--stack", "python", "--repeats", "1"),
            ),
            0,
        )
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["all_attempts"], 4)
        self.assertEqual(summary["http_passed"], 4)
        self.assertTrue(all(row["original_http_passed"] for row in summary["runs"]))
        self.assertTrue(all(not row["analysis_complete"] for row in summary["runs"]))
        self.assertNotIn("private evidence failure", json.dumps(summary))
        for path in self.originals:
            analysis = json.loads(path.with_name("analysis.json").read_text())
            self.assertTrue(analysis["passed"])
            self.assertIsNone(analysis["error_code"])
        self.assert_originals()

    def test_prework_and_midwork_terminal_errors_stop_without_losing_the_attempt(self):
        for prework in (True, False):
            with self.subTest(prework=prework):
                self.output = self.base / f"terminal-{prework}"
                self.terminal = "rate_limit_exceeded private terminal marker"
                self.prework = prework
                self.assertEqual(self.invoke(), 1)
                summary = json.loads((self.output / "summary.json").read_text())
                self.assertEqual(summary["all_attempts"], 1)
                self.assertEqual(summary["supported_started"], 0 if prework else 1)
                self.assertEqual(summary["prework_infrastructure"], 1 if prework else 0)
                self.assertEqual(summary["blocked"], "cli-rate-limited")
                self.assertFalse(summary["complete"])
                self.assertNotIn("private terminal marker", json.dumps(summary))
        self.assert_originals()

    def test_successful_original_http_does_not_classify_stderr_as_terminal(self):
        self.stderr = "error 401 rate limit reached from ordinary stderr text"
        self.assertEqual(self.invoke(extra=("--stack", "python", "--repeats", "1")), 0)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["all_attempts"], 4)
        self.assertIsNone(summary["blocked"])

    def test_post_agent_build_or_http_failure_does_not_turn_stderr_into_cli_stop(self):
        self.stderr = "error 401 rate limit reached from ordinary stderr text"
        for index, failure in enumerate(("build-failed", "core-list-200")):
            with self.subTest(failure=failure):
                self.output = self.base / f"post-agent-failure-{index}"
                self.assertEqual(
                    self.invoke(
                        grade_error=auth_eval.EvalError(failure),
                        extra=("--stack", "python", "--repeats", "1"),
                    ),
                    0,
                )
                summary = json.loads((self.output / "summary.json").read_text())
                self.assertEqual(summary["all_attempts"], 4)
                self.assertEqual(summary["supported_started"], 4)
                self.assertEqual(summary["http_passed"], 0)
                self.assertTrue(summary["complete"])
                self.assertIsNone(summary["blocked"])
                for row in summary["runs"]:
                    self.assertEqual(row["original_error_code"], failure)
                    self.assertTrue(row["started_state"]["turn_completed"])
                    self.assertIsNone(row["started_state"]["infrastructure_error"])
                    self.assertIsNone(row["started_state"]["terminal_reason_source"])
        self.assert_originals()

    def review_document(self):
        rows, _, _, _ = choice.retained_rows(self.output)
        row = rows[0]
        source = next(
            item
            for item in row["source_inventory"]["files"]
            if item["path"] == "app.py"
        )
        review = {
            "trial": row["trial"],
            "original_result_sha256": row["original_result_sha256"],
            "features": {
                feature: {
                    "classification": "library_connected",
                    "evidence": [
                        {"path": source["path"], "line": 2, "sha256": source["sha256"]}
                    ],
                }
                for feature in choice.FEATURES
            },
        }
        return rows, {"reviews": [review]}

    def test_report_validates_reviews_and_writes_only_a_new_output(self):
        self.assertEqual(
            self.invoke(
                extra=(
                    "--stack",
                    "python",
                    "--scenarios",
                    "documents",
                    "--repeats",
                    "1",
                )
            ),
            0,
        )
        rows, document = self.review_document()
        review_path = self.base / "review.json"
        review_path.write_text(json.dumps(document))
        report_output = self.base / "reviewed"
        before = {
            path: path.read_bytes() for path in self.output.rglob("*") if path.is_file()
        }
        self.assertEqual(
            choice.main(
                [
                    "report",
                    "--input",
                    str(self.output),
                    "--reviews",
                    str(review_path),
                    "--output",
                    str(report_output),
                ]
            ),
            0,
        )
        result = json.loads((report_output / "summary.json").read_text())
        self.assertEqual(result["library_connected_full"], 1)
        self.assertEqual(result["verified_full_reuse"], 1)
        self.assertEqual(result["choice_unknown"], 1)
        self.assertEqual(result["rates"]["confirmed_full_reuse_lower_bound"], 0.5)
        self.assertEqual(result["runs"][0]["classification_source"], "source-review")
        self.assertFalse(result["runs"][0]["runtime_causality_proven"])
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(
                choice.main(
                    [
                        "report",
                        "--input",
                        str(self.output),
                        "--output",
                        str(report_output),
                    ]
                ),
                2,
            )
        self.assertEqual(len(rows), 2)

    def test_review_evidence_rejects_wrong_hash_line_path_original_and_symlink(self):
        self.assertEqual(
            self.invoke(
                extra=(
                    "--stack",
                    "python",
                    "--scenarios",
                    "documents",
                    "--repeats",
                    "1",
                )
            ),
            0,
        )
        rows, document = self.review_document()
        for key, value in (
            ("sha256", "0" * 64),
            ("line", 999),
            ("line", True),
            ("path", "../app.py"),
            ("path", "/private/app.py"),
        ):
            with self.subTest(key=key, value=value):
                changed = json.loads(json.dumps(document))
                changed["reviews"][0]["features"]["auth"]["evidence"][0][key] = value
                with self.assertRaises(auth_eval.EvalError):
                    choice.validate_reviews(changed, rows, self.output)
        changed = json.loads(json.dumps(document))
        changed["reviews"][0]["original_result_sha256"] = "0" * 64
        with self.assertRaisesRegex(auth_eval.EvalError, "review-original-result"):
            choice.validate_reviews(changed, rows, self.output)
        source = self.output / rows[0]["trial"] / "snapshot/generated/app.py"
        outside = self.base / "outside.py"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
        with self.assertRaises(auth_eval.EvalError):
            choice.validate_reviews(document, rows, self.output)

    def test_report_rejects_generated_reference_original_trace_or_analysis_changes(
        self,
    ):
        for index, relative in enumerate(
            (
                "snapshot/generated/app.py",
                "snapshot/README.md",
                "result.json",
                "trace.jsonl",
                "analysis.json",
            )
        ):
            with self.subTest(relative=relative):
                self.output = self.base / f"tampered-{index}"
                self.assertEqual(
                    self.invoke(
                        extra=(
                            "--stack",
                            "python",
                            "--scenarios",
                            "documents",
                            "--repeats",
                            "1",
                        )
                    ),
                    0,
                )
                rows, _, _, _ = choice.retained_rows(self.output)
                path = self.output / rows[0]["trial"] / relative
                path.write_bytes(path.read_bytes() + b"\nchanged")
                report_output = self.base / f"rejected-{index}"
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        choice.main(
                            [
                                "report",
                                "--input",
                                str(self.output),
                                "--output",
                                str(report_output),
                            ]
                        ),
                        2,
                    )
                self.assertFalse(report_output.exists())

    def test_retained_original_provenance_must_match_the_frozen_manifest(self):
        self.assertEqual(
            self.invoke(
                extra=(
                    "--stack",
                    "python",
                    "--scenarios",
                    "documents",
                    "--repeats",
                    "1",
                )
            ),
            0,
        )
        summary_path = self.output / "summary.json"
        summary = json.loads(summary_path.read_text())
        retained = self.output / summary["runs"][0]["trial"]
        original_path = retained / "result.json"
        original = json.loads(original_path.read_text())
        original["source_sha256"] = "0" * 64
        original_path.write_text(json.dumps(original))
        analysis_path = retained / "analysis.json"
        analysis = json.loads(analysis_path.read_text())
        analysis["original_result_sha256"] = hashlib.sha256(
            original_path.read_bytes()
        ).hexdigest()
        analysis_path.write_text(json.dumps(analysis))
        summary["runs"][0]["analysis_sha256"] = hashlib.sha256(
            analysis_path.read_bytes()
        ).hexdigest()
        summary_path.write_text(json.dumps(summary))
        with self.assertRaisesRegex(
            auth_eval.EvalError, "retained-provenance-mismatch"
        ):
            choice.retained_rows(self.output)

    def test_cli_validation_precedes_output_artifact_or_model_work(self):
        with (
            patch.object(
                auth_eval, "prepare_output", side_effect=AssertionError("output")
            ),
            patch.object(
                choice.reading, "local_artifact", side_effect=AssertionError("artifact")
            ),
            patch.object(auth_eval, "run_trial", side_effect=AssertionError("model")),
            redirect_stderr(io.StringIO()),
        ):
            base = [
                "--artifact",
                "/missing",
                "--artifact-sha256",
                "a" * 64,
                "--source-commit",
                COMMIT,
                "--models",
                *self.models,
                "--output",
                str(self.output),
            ]
            for extra in (
                ("--timeout", "0"),
                ("--timeout", "601"),
                ("--repeats", "0"),
                ("--stack", "unknown"),
                ("--scenarios", "documents", "documents"),
                ("--source-commit", "bad"),
                ("--artifact-sha256", "bad"),
                ("--models", "duplicate", "duplicate"),
                ("--models", "model with spaces", "second"),
            ):
                with self.subTest(extra=extra), self.assertRaises(SystemExit) as error:
                    choice.main([*base, *extra])
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
