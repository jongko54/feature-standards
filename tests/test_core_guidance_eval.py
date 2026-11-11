"""Guidance A/B orchestration with fake external CLI and independent HTTP results."""

from __future__ import annotations

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
import choice_tasks_v2 as tasks
import core_eval
import core_guidance_eval as guidance
import test_reading_orchestration as fixtures

COMMIT = fixtures.COMMIT


class GuidanceMeasurements(unittest.TestCase):
    def test_balanced_rotated_conditions_and_reverse_second_repeat(self):
        assignments = guidance.schedule(
            "provider/arbitrary-model", auth_eval.STACKS, tasks.SCENARIOS, 2
        )
        self.assertEqual(len(assignments), 32)
        self.assertEqual(len({row["trial"] for row in assignments}), 32)
        orders = []
        for stack in auth_eval.STACKS:
            first = [
                (r["scenario"], r["condition"])
                for r in assignments
                if r["stack"] == stack and r["repeat"] == 1
            ]
            second = [
                (r["scenario"], r["condition"])
                for r in assignments
                if r["stack"] == stack and r["repeat"] == 2
            ]
            self.assertEqual(second, first[::-1])
            orders.append(tuple(first))
        self.assertEqual(len(set(orders)), 4)
        self.assertTrue(all(row["trial"].startswith("m01-") for row in assignments))

    def rows(self):
        assignments = guidance.schedule("model", ("python",), ("tickets",), 1)
        rows = []
        for assignment in assignments:
            rows.append(
                assignment
                | {
                    "original_result_sha256": "a" * 64,
                    "original_http_passed": True,
                    "source_unchanged": True,
                    "retained_source_unchanged": True,
                    "source_sha256": "source",
                    "fixture_sha256": "fixture",
                    "cli_version": "fixture-cli 1.0",
                    "ticket_fixture_integrity": {
                        "state": "injected",
                        "sha256": "fixture",
                        "matches_expected": True,
                    },
                    "checks": ["ok"] * tasks.expected_assertions("tickets"),
                    "started_state": {"supported_started": True},
                    "agent": {
                        "completed": True,
                        "usage_complete": True,
                        "models": [],
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                        },
                    },
                }
            )
        return assignments, rows

    def review(self, row, classification):
        return {
            "trial": row["trial"],
            "original_result_sha256": row["original_result_sha256"],
            "features": {
                feature: {"classification": classification, "evidence": []}
                for feature in ("auth", "authorization", "listing")
            },
        }

    def test_unknown_choices_are_null_and_failures_remain_usage_pairs(self):
        assignments, rows = self.rows()
        rows[1]["original_http_passed"] = False
        result = guidance.summarize(rows, {}, assignments)
        self.assertEqual(result["all_attempts"], 2)
        self.assertEqual(result["choice_unknown"], 2)
        self.assertIsNone(result["rates"]["confirmed_full_reuse_lower_bound"])
        self.assertEqual(result["usage_pairs"]["included_pairs"], 1)
        self.assertEqual(result["usage_pairs"]["joint_working_pairs"], 0)
        self.assertEqual(
            result["usage_pairs"]["paired_totals"]["difference"]["total_tokens"], 0
        )
        self.assertEqual(result["suite"], "core-guidance-v2")
        uncertain = {r["trial"]: self.review(r, "uncertain") for r in rows}
        self.assertIsNone(
            guidance.summarize(rows, {}, assignments, uncertain)["rates"][
                "verified_full_reuse_lower_bound"
            ]
        )

    def test_task_specific_assertions_and_copied_vs_original_api_use(self):
        assignments, rows = self.rows()
        reviews = {
            rows[0]["trial"]: self.review(rows[0], "library_connected"),
            rows[1]["trial"]: self.review(rows[1], "copied_runtime_source"),
        }
        result = guidance.summarize(rows, {}, assignments, reviews)
        self.assertEqual(result["verified_full_reuse"], 1)
        self.assertEqual(result["provided_api_use_full"], 2)
        self.assertEqual(result["copied_runtime_source_any"], 1)
        rows[0]["checks"].pop()
        self.assertEqual(
            guidance.summarize(rows, {}, assignments, reviews)["verified_full_reuse"], 0
        )

    def test_original_http_success_needs_actual_ticket_fixture_for_verified_reuse(self):
        assignments, rows = self.rows()
        reviews = {row["trial"]: self.review(row, "library_connected") for row in rows}
        rows[0]["ticket_fixture_integrity"] = {
            "state": "unknown",
            "sha256": None,
            "matches_expected": None,
        }
        result = guidance.summarize(rows, {}, assignments, reviews)
        self.assertEqual(result["http_passed"], 2)
        self.assertEqual(result["working_http_verified"], 1)
        self.assertEqual(result["verified_full_reuse"], 1)
        self.assertEqual(
            result["usage_pairs"]["pairs"][0]["excluded_reason"],
            "fixture-integrity-unverified",
        )

    def test_incomplete_mismatched_missing_pairs_are_explicit(self):
        assignments, rows = self.rows()
        rows[1]["agent"]["usage_complete"] = False
        result = guidance.summarize(rows, {}, assignments)
        self.assertEqual(result["usage_pairs"]["included_pairs"], 0)
        self.assertIsNone(result["usage_pairs"]["paired_totals"])
        self.assertEqual(
            result["usage_pairs"]["pairs"][0]["excluded_reason"], "incomplete-usage"
        )
        rows[1]["agent"]["usage_complete"] = True
        rows[1]["fixture_sha256"] = "different"
        self.assertEqual(
            guidance.summarize(rows, {}, assignments)["usage_pairs"]["pairs"][0][
                "excluded_reason"
            ],
            "fixture-mismatch",
        )
        self.assertEqual(
            guidance.summarize(rows[:1], {}, assignments)["usage_pairs"]["pairs"][0][
                "excluded_reason"
            ],
            "missing-attempt",
        )

    def test_public_metadata_uses_allowlist_and_changed_source_is_not_comparable(self):
        assignments, rows = self.rows()
        result = guidance.summarize(
            rows,
            {
                "source_commit": COMMIT,
                "private_seed": "secret-value",
                "fixtures": {"seed": "private"},
            },
            assignments,
        )
        self.assertNotIn("private_seed", result)
        self.assertNotIn("fixtures", result)
        self.assertEqual(result["source_commit"], COMMIT)
        rows[0]["source_unchanged"] = False
        result = guidance.summarize(rows, {}, assignments)
        self.assertEqual(
            result["usage_pairs"]["pairs"][0]["excluded_reason"],
            "reference-source-changed",
        )

    def test_timed_out_cli_with_only_partial_completed_turn_usage_is_null(self):
        assignments, rows = self.rows()
        rows[0]["agent"]["completed"] = False
        result = guidance.summarize(rows, {}, assignments)
        self.assertIsNone(result["runs"][0]["tokens"])
        self.assertEqual(
            result["usage_pairs"]["pairs"][0]["excluded_reason"], "incomplete-usage"
        )

    def test_pair_provenance_requires_verified_reference_and_same_known_cli_version(
        self,
    ):
        assignments, rows = self.rows()
        for key, value, reason in (
            ("source_unchanged", None, "reference-source-unverified"),
            ("retained_source_unchanged", None, "reference-source-unverified"),
            ("cli_version", None, "cli-version-unknown"),
            ("cli_version", "other-cli 2.0", "cli-version-mismatch"),
        ):
            with self.subTest(key=key, value=value):
                saved = rows[1][key]
                rows[1][key] = value
                self.assertEqual(
                    guidance.summarize(rows, {}, assignments)["usage_pairs"]["pairs"][
                        0
                    ]["excluded_reason"],
                    reason,
                )
                rows[1][key] = saved


class GuidanceOrchestration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="guidance-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.artifact = self.base / "candidate.tgz"
        self.artifact.write_bytes(fixtures.archive_bytes())
        self.output = self.base / "runs"
        self.calls = []
        self.templates = []
        self.fixtures = {}
        self.originals = {}
        self.active = False
        self.mode = "success"

    def freeze(self, root, destination, catalog, *, commit):
        destination.mkdir()
        (destination / "README.md").write_text("Same source for both conditions.\n")
        for source in [
            *guidance.MODULE_PATHS.values(),
            *guidance.GUIDE_PATHS.values(),
            "docs/ai-entry/README.md",
            "evals/core/tasks.json",
        ]:
            target = destination / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / source).read_bytes())
        core_eval.extract_archive(catalog, destination / "catalog")
        fingerprint = auth_eval.fingerprint(destination)
        self.templates.append(fingerprint)
        return {
            "source_commit": commit,
            "source_dirty": False,
            "source_sha256": auth_eval.digest_hashes(fingerprint),
            "implementation_source_sha256": auth_eval.digest_hashes(fingerprint),
            "catalog_snapshot_sha256": auth_eval.digest_hashes(
                auth_eval.fingerprint(destination / "catalog")
            ),
        }

    def subprocess(self, argv, *args, **kwargs):
        if argv[:2] == ["codex", "--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"fixture-cli 1.0\n")
        if argv[:1] == ["git"] and "init" in argv:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"Unexpected subprocess {argv!r}")

    def execute(self, argv, cwd, env, log, deadline, stdin=None, stderr_log=None):
        self.assertFalse(self.active)
        self.active = True
        try:
            manifest = json.loads((self.output / "manifest.json").read_text())
            assignment = manifest["trials"][len(self.calls)]
            prompt = stdin.decode()
            self.assertEqual(
                hashlib.sha256(stdin).hexdigest(), assignment["prompt_sha256"]
            )
            self.assertNotIn("TICKETS_DATA_FILE", env)
            self.assertFalse(list(cwd.glob(".core-membership-*")))
            for fixture in manifest["fixtures"].values():
                self.assertNotIn(fixture["seed"], prompt)
                for row in tasks.ticket_fixture(fixture["seed"]):
                    self.assertNotIn(row["id"], prompt)
            snapshot = auth_eval.digest_hashes(auth_eval.fingerprint(cwd.parent))
            self.calls.append((assignment, snapshot, prompt))
            self.assertEqual(snapshot, manifest["metadata"]["source_sha256"])
            self.assertEqual(
                json.loads((self.output / "progress.json").read_text())[
                    "actual_model_calls"
                ],
                len(self.calls) - 1,
            )
            (cwd / "app.py").write_text(
                "# private generated marker\ndef route(): return 1\n"
            )
            auth_eval.write_json(
                cwd / "integration.json",
                {
                    "stack": assignment["stack"],
                    "profile": "browser-session-v1",
                    "source_commit": COMMIT,
                },
            )
            auth_eval.write_json(
                cwd / "run.json",
                {"build": [], "start": {"argv": ["fake-server"], "cwd": "."}},
            )
            events = [] if self.mode == "unknown" else [{"type": "turn.started"}]
            if self.mode == "prework":
                events.append(
                    {"type": "error", "message": "401 Unauthorized private-secret"}
                )
            elif self.mode not in {"unknown", "timeout"}:
                events.append(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                        },
                    }
                )
            log.write_text("".join(json.dumps(e) + "\n" for e in events))
            stderr_log.write_text(
                "error 401 private-secret\n" if self.mode == "build-failed" else ""
            )
            if self.mode == "timeout":
                raise auth_eval.EvalError("timeout")
            return 1 if self.mode == "prework" else 0
        finally:
            self.active = False

    def grade(self, generated, output, env, port, origin, deadline, **kwargs):
        assignment = self.calls[-1][0]
        if assignment["scenario"] == "tickets":
            data_path = Path(env["TICKETS_DATA_FILE"])
            self.assertEqual(data_path.stat().st_mode & 0o777, 0o600)
            data = json.loads(data_path.read_text())
            self.assertEqual(
                hashlib.sha256(data_path.read_bytes()).hexdigest(),
                assignment["fixture_sha256"],
            )
            self.fixtures[assignment["trial"]] = data
        if self.mode == "build-failed":
            raise auth_eval.EvalError("build-failed")
        return [
            f"check-{i}"
            for i in range(tasks.expected_assertions(assignment["scenario"]))
        ]

    def invoke(self, extra=()):
        original_write = auth_eval.write_json

        def write(path, value):
            original_write(path, value)
            if path.name in {"result.json", "trace.jsonl"}:
                self.originals[path] = path.read_bytes()

        with ExitStack() as patches:
            patches.enter_context(
                patch.object(guidance.shutil, "which", return_value="/fixture/codex")
            )
            patches.enter_context(
                patch.object(core_eval, "freeze_sources", side_effect=self.freeze)
            )
            patches.enter_context(
                patch.object(auth_eval, "execute", side_effect=self.execute)
            )
            patches.enter_context(
                patch.object(auth_eval, "grade", side_effect=self.grade)
            )
            patches.enter_context(
                patch.object(auth_eval.subprocess, "run", side_effect=self.subprocess)
            )
            patches.enter_context(
                patch.object(guidance.subprocess, "check_output", return_value=COMMIT)
            )
            patches.enter_context(
                patch.object(auth_eval, "write_json", side_effect=write)
            )
            patches.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "TICKETS_DATA_FILE": "/private/pre-agent-fixture",
                        "OPENAI_API_KEY": "private-key",
                        "CODEX_HOME": "/private/codex-home",
                    },
                )
            )
            patches.enter_context(redirect_stdout(io.StringIO()))
            return guidance.main(
                [
                    "run",
                    "--artifact",
                    str(self.artifact),
                    "--artifact-sha256",
                    hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
                    "--source-commit",
                    COMMIT,
                    "--model",
                    "provider/requested-model",
                    "--output",
                    str(self.output),
                    *extra,
                ]
            )

    def summary(self):
        return json.loads((self.output / "summary.json").read_text())

    def test_32_serial_calls_identical_source_cards_paired_private_data_and_public_export(
        self,
    ):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(len(self.calls), 32)
        self.assertEqual(len(self.templates), 1)
        self.assertEqual(len({snapshot for _, snapshot, _ in self.calls}), 1)
        summary = self.summary()
        self.assertEqual(summary["all_attempts"], 32)
        self.assertEqual(summary["choice_unknown"], 32)
        self.assertEqual(summary["http_passed"], 32)
        self.assertEqual(summary["usage_pairs"]["included_pairs"], 16)
        self.assertEqual(summary["guide_sha256"].keys(), set(auth_eval.STACKS))
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(len(manifest["fixtures"]), 8)
        self.assertEqual(len({f["seed"] for f in manifest["fixtures"].values()}), 8)
        for pair in {
            r["pair_id"] for r, _, _ in self.calls if r["scenario"] == "tickets"
        }:
            assignments = [r for r, _, _ in self.calls if r["pair_id"] == pair]
            self.assertEqual(
                self.fixtures[assignments[0]["trial"]],
                self.fixtures[assignments[1]["trial"]],
            )
        public = json.dumps(summary)
        for secret in (
            str(self.base),
            "private-key",
            "private-secret",
            "private generated marker",
            *[f["seed"] for f in manifest["fixtures"].values()],
        ):
            self.assertNotIn(secret, public)
        for trial in manifest["trials"]:
            inventory = summary["runs"][trial["sequence"] - 1]["source_inventory"]
            self.assertFalse(
                any(
                    ".core-membership-tickets-" in f["path"] for f in inventory["files"]
                )
            )
        retained, _, assignments, _ = guidance.retained_rows(self.output)
        self.assertEqual((len(retained), len(assignments)), (32, 32))
        for path, original in self.originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_completed_cli_build_failure_stderr_401_does_not_stop_protocol(self):
        self.mode = "build-failed"
        self.assertEqual(self.invoke(("--stack", "python", "--repeats", "1")), 0)
        self.assertEqual(self.summary()["all_attempts"], 4)
        self.assertEqual(self.summary()["supported_started"], 4)
        self.assertEqual(self.summary()["http_passed"], 0)
        self.assertIsNone(self.summary()["blocked"])

    def test_unknown_and_prework_are_preserved_in_separate_denominators(self):
        self.mode = "unknown"
        self.assertEqual(self.invoke(("--stack", "python", "--repeats", "1")), 0)
        self.assertEqual(self.summary()["start_unknown"], 4)
        self.assertEqual(self.summary()["choice_unknown"], 0)
        self.output = self.base / "prework"
        self.calls.clear()
        self.mode = "prework"
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.summary()["prework_infrastructure"], 1)
        self.assertEqual(self.summary()["actual_model_calls"], 1)
        self.assertEqual(self.summary()["usage_pairs"]["included_pairs"], 0)

    def test_timeout_remains_supported_without_usage_or_working_http(self):
        self.mode = "timeout"
        self.assertEqual(self.invoke(("--stack", "python", "--repeats", "1")), 0)
        result = self.summary()
        self.assertEqual((result["all_attempts"], result["supported_started"]), (4, 4))
        self.assertEqual(result["choice_unknown"], 4)
        self.assertEqual(result["http_passed"], 0)
        self.assertTrue(all(row["tokens"] is None for row in result["runs"]))

    def test_retained_ticket_fixture_body_deletion_permissions_and_private_name(self):
        self.assertEqual(
            self.invoke(
                ("--stack", "python", "--scenarios", "tickets", "--repeats", "1")
            ),
            0,
        )
        summary = self.summary()
        for row in summary["runs"]:
            self.assertEqual(
                row["ticket_fixture_integrity"],
                {
                    "state": "injected",
                    "sha256": row["fixture_sha256"],
                    "matches_expected": True,
                },
            )
        self.assertNotIn(".core-membership-tickets-", json.dumps(summary))
        trial = self.calls[0][0]["trial"]
        retained = self.output / trial
        (path,) = (retained / "snapshot/generated").glob(
            ".core-membership-tickets-*.json"
        )
        original = path.read_bytes()
        raw = (retained / "result.json").read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(auth_eval.EvalError, "fixture-integrity"):
            guidance.retained_rows(self.output)
        path.write_bytes(original)
        path.unlink()
        with self.assertRaisesRegex(auth_eval.EvalError, "fixture-integrity"):
            guidance.retained_rows(self.output)
        path.write_bytes(original)
        path.chmod(0o644)
        with self.assertRaisesRegex(auth_eval.EvalError, "fixture"):
            guidance.retained_rows(self.output)
        path.chmod(0o600)
        hardlink = self.base / "fixture-hardlink.json"
        os.link(path, hardlink)
        with self.assertRaisesRegex(auth_eval.EvalError, "unsafe-ticket-fixture"):
            guidance.retained_rows(self.output)
        hardlink.unlink()
        duplicate = path.with_name(
            ".core-membership-tickets-"
            + ("f" if "f" * 24 not in path.name else "e") * 24
            + ".json"
        )
        duplicate.write_bytes(original)
        duplicate.chmod(0o600)
        with self.assertRaisesRegex(auth_eval.EvalError, "unsafe-ticket-fixture-set"):
            guidance.retained_rows(self.output)
        duplicate.unlink()
        target = self.base / "fixture-target.json"
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(auth_eval.EvalError, "unsafe-ticket-fixture"):
            guidance.retained_rows(self.output)
        path.unlink()
        path.write_bytes(original)
        path.chmod(0o600)
        guidance.retained_rows(self.output)
        self.assertEqual((retained / "result.json").read_bytes(), raw)

    def test_timeout_before_prepare_records_absence_and_remains_reportable(self):
        self.mode = "timeout"
        self.assertEqual(
            self.invoke(
                ("--stack", "python", "--scenarios", "tickets", "--repeats", "1")
            ),
            0,
        )
        result = self.summary()
        self.assertTrue(
            all(
                row["ticket_fixture_integrity"]
                == {"state": "not-created", "sha256": None, "matches_expected": None}
                for row in result["runs"]
            )
        )
        rows, _, _, _ = guidance.retained_rows(self.output)
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(
                row["original_error_code"] == "timeout"
                and row["original_http_passed"] is False
                for row in rows
            )
        )

    def test_report_preserves_raw_evidence_and_rejects_hash_tampering(self):
        self.assertEqual(
            self.invoke(
                ("--stack", "python", "--scenarios", "documents", "--repeats", "1")
            ),
            0,
        )
        before = {p: p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(
            guidance.main(
                [
                    "report",
                    "--input",
                    str(self.output),
                    "--output",
                    str(self.base / "report"),
                ]
            ),
            0,
        )
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
        trial = self.calls[0][0]["trial"]
        candidates = [
            self.output / "manifest.json",
            self.output / trial / "result.json",
            self.output / trial / "trace.jsonl",
            self.output / trial / "agent.log",
            self.output / trial / "analysis.json",
            self.output / trial / "snapshot/generated/app.py",
            self.output / trial / "snapshot/docs/ai-entry/python.md",
            self.output / "prompts" / (trial + ".txt"),
        ]
        for path in candidates:
            with self.subTest(path=path.relative_to(self.output)):
                saved = path.read_bytes()
                path.write_bytes(saved + b"\n ")
                with self.assertRaises(auth_eval.EvalError):
                    guidance.retained_rows(self.output)
                path.write_bytes(saved)

    def test_invalid_selection_rejected_before_output_or_cli(self):
        for args in [
            ("--model", "unsafe model"),
            ("--scenarios", "documents", "documents"),
            ("--timeout", "601"),
            ("--source-commit", "not-a-commit"),
        ]:
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(args)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.calls, [])

    def test_fixture_ledger_tampering_and_source_reviews_are_checked(self):
        self.assertEqual(
            self.invoke(
                ("--stack", "python", "--scenarios", "tickets", "--repeats", "1")
            ),
            0,
        )
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["fixtures"][next(iter(manifest["fixtures"]))]["seed"] = "changed-seed"
        manifest_path.write_text(json.dumps(manifest))
        summary = self.summary()
        summary["manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        (self.output / "summary.json").write_text(json.dumps(summary))
        with self.assertRaisesRegex(auth_eval.EvalError, "fixture-hash"):
            guidance.retained_rows(self.output)

    def test_report_attaches_validated_reviews_and_rejects_bad_evidence_before_output(
        self,
    ):
        self.assertEqual(
            self.invoke(
                ("--stack", "python", "--scenarios", "tickets", "--repeats", "1")
            ),
            0,
        )
        reviews = []
        for row in self.summary()["runs"]:
            source = self.output / row["trial"] / "snapshot/generated/app.py"
            evidence = {
                "path": "app.py",
                "line": 2,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            reviews.append(
                {
                    "trial": row["trial"],
                    "original_result_sha256": row["original_result_sha256"],
                    "features": {
                        feature: {
                            "classification": "direct_independent",
                            "evidence": [evidence.copy()],
                        }
                        for feature in ("auth", "authorization", "listing")
                    },
                }
            )
        review_path = self.base / "reviews.json"
        review_path.write_text(json.dumps({"reviews": reviews}))
        report_output = self.base / "reviewed"
        argv = [
            "report",
            "--input",
            str(self.output),
            "--reviews",
            str(review_path),
            "--output",
            str(report_output),
        ]
        self.assertEqual(guidance.main(argv), 0)
        result = json.loads((report_output / "summary.json").read_text())
        self.assertEqual(result["complete_choice_reviews"], 2)
        self.assertEqual(result["direct_independent_full"], 2)
        self.assertTrue(
            all(
                row["expected_http_assertions"] == tasks.expected_assertions("tickets")
                for row in result["runs"]
            )
        )
        reviews[0]["features"]["auth"]["evidence"][0]["line"] = 999999
        review_path.write_text(json.dumps({"reviews": reviews}))
        invalid_output = self.base / "invalid-reviewed"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(guidance.main([*argv[:-1], str(invalid_output)]), 2)
        self.assertFalse(invalid_output.exists())

    def test_artifact_content_hash_mismatch_creates_no_output(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke(("--artifact-sha256", "0" * 64)), 2)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])


class GraderCredentialBoundary(unittest.TestCase):
    def test_real_grade_strips_cli_credentials_from_build_and_child_process(self):
        temporary = tempfile.TemporaryDirectory(prefix="guidance-secret-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        generated, output = root / "generated", root / "retained"
        generated.mkdir()
        output.mkdir()
        marker = root / "child-env.json"
        (generated / "server.py").write_text(
            "import json, os, sys\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "with open(sys.argv[2], 'w') as f: json.dump(dict(os.environ), f)\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n  self.send_response(200); self.end_headers(); self.wfile.write(b'{}')\n"
            " def log_message(self, *args): pass\n"
            "HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()\n"
        )
        import socket
        import time

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        auth_eval.write_json(
            generated / "run.json",
            {
                "build": [{"argv": ["fake-build"], "cwd": "."}],
                "start": {
                    "argv": [sys.executable, "server.py", str(port), str(marker)],
                    "cwd": ".",
                },
            },
        )
        env = auth_eval.environment(port, f"http://127.0.0.1:{port}") | {
            "OPENAI_API_KEY": "private-key",
            "CODEX_HOME": "/private/codex-home",
            "TICKETS_DATA_FILE": "/private/grader-only-file",
        }
        build_environments = []

        def build(argv, cwd, environment, log, deadline):
            build_environments.append(environment)
            return 0

        with patch.object(auth_eval, "execute", side_effect=build):
            self.assertEqual(
                auth_eval.grade(
                    generated,
                    output,
                    env,
                    port,
                    env["AUTH_ALLOWED_ORIGIN"],
                    time.monotonic() + 5,
                    http_grader=lambda *args: ["independent-check"],
                ),
                ["independent-check"],
            )
        child_environment = json.loads(marker.read_text())
        for environment in [*build_environments, child_environment]:
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("CODEX_HOME", environment)
            self.assertEqual(
                environment["TICKETS_DATA_FILE"], "/private/grader-only-file"
            )


if __name__ == "__main__":
    unittest.main()
