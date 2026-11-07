"""Behavior tests for new-source reading comparisons; no live model calls."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auth_eval
import core_eval
import core_reading_eval as reading
import core_transfer_eval as transfer
import test_reading_orchestration as fixtures


def run(condition, repeat=1, passed=True, input_tokens=100, cached=20, output=10):
    return {
        "stack": "python",
        "condition": condition,
        "repeat": repeat,
        "passed": passed,
        "source_sha256": "same-source",
        "requested_model": "fixture-model",
        "cli_version": "fixture-cli",
        "runner_sha256": "same-runner",
        "auth_runner_sha256": "same-auth",
        "core_runner_sha256": "same-core",
        "trace_runner_sha256": "same-trace",
        "tasks_sha256": "same-task",
        "profile": "auth-rbac-offset-v1",
        "timeout_seconds": 600,
        "agent": {
            "usage_complete": True,
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached,
                "output_tokens": output,
            },
            "models": [],
        },
    }


class ReadingEvaluationTests(unittest.TestCase):
    def test_alternate_conditions_schedule_and_summary_do_not_add_original_conditions(
        self,
    ):
        conditions = ("catalog_compact", "brief")
        trials = reading.schedule(auth_eval.STACKS, 2, conditions=conditions)
        self.assertEqual(len(trials), 16)
        for stack in auth_eval.STACKS:
            first = [c for s, r, c in trials if s == stack and r == 1]
            self.assertEqual(
                [c for s, r, c in trials if s == stack and r == 2], first[::-1]
            )
        report = reading.summarize(
            [run("catalog_compact"), run("brief")],
            {"protocol_id": "fixture-transfer-v1"},
            planned_total=8,
            conditions=conditions,
            limits=["fixture scope"],
        )
        self.assertEqual(report["suite"], "fixture-transfer-v1")
        self.assertEqual(set(report["groups"]), set(conditions))
        self.assertEqual(
            [(c["reference"], c["variant"]) for c in report["comparisons"]],
            [conditions],
        )
        self.assertEqual(report["limits"], ["fixture scope"])

    def test_optional_protocol_or_evidence_identity_prevents_cross_protocol_pairs(self):
        for key in ("protocol_id", "protocol_sha256", "source_evidence_sha256"):
            for other in ("different", None):
                left, right = run("manual"), run("catalog_compact")
                left[key] = "same"
                if other is not None:
                    right[key] = other
                report = reading.comparison([left, right], "manual", "catalog_compact")
                self.assertEqual(report["configuration_mismatch_pairs"], 1, key)
                self.assertEqual(report["all_complete_pairs"]["pairs"], 0)

    def test_invalid_descriptor_cannot_put_paths_into_trial_names(self):
        descriptor = transfer.EXPERIMENT | {"conditions": ("../outside",)}
        with self.assertRaisesRegex(reading.EvalError, "invalid-experiment"):
            reading.experiment_settings(descriptor)

    def test_three_conditions_keep_task_body_and_new_versions_identical(self):
        tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        prompts = [
            reading.prompt("python", "a" * 40, tasks, c) for c in reading.CONDITIONS
        ]
        bodies = [p.split("\n\nCurrent directory", 1)[1] for p in prompts]
        self.assertEqual(len(set(bodies)), 1)
        for text in prompts:
            self.assertIn("0.4.0", text)
            self.assertNotIn("0.3.2", text)
        self.assertIn("--compact", prompts[2].split("\n\nCurrent directory", 1)[0])
        self.assertNotIn("--compact", prompts[1].split("\n\nCurrent directory", 1)[0])

    def test_schedule_reverses_each_stack_and_contains_exactly_24_unique_trials(self):
        schedule = reading.schedule(("python", "go", "java", "rust"), 2)
        self.assertEqual(len(schedule), 24)
        self.assertEqual(len(set(schedule)), 24)
        for stack in ("python", "go", "java", "rust"):
            first = [c for s, r, c in schedule if s == stack and r == 1]
            second = [c for s, r, c in schedule if s == stack and r == 2]
            self.assertEqual(second, first[::-1])
        self.assertGreater(
            len(
                {
                    tuple(c for s, r, c in schedule if s == stack and r == 1)
                    for stack in ("python", "go", "java", "rust")
                }
            ),
            1,
        )

    def test_usage_does_not_double_count_cache_or_zero_fill_missing(self):
        self.assertEqual(
            reading.tokens(run("manual")),
            {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "uncached_input_tokens": 80,
                "output_tokens": 10,
                "total_tokens": 110,
            },
        )
        for item in (run("manual", cached=101), run("manual", input_tokens=True)):
            self.assertIsNone(reading.tokens(item))
        item = run("manual")
        item["agent"]["usage_complete"] = False
        self.assertIsNone(reading.tokens(item))

    def test_savings_use_paired_sums_and_report_failures_separately(self):
        rows = [
            run("manual", input_tokens=100),
            run("catalog_compact", input_tokens=50),
            run("manual", repeat=2, input_tokens=300),
            run("catalog_compact", repeat=2, passed=False, input_tokens=30),
        ]
        report = reading.comparison(rows, "manual", "catalog_compact")
        self.assertEqual(report["all_complete_pairs"]["pairs"], 2)
        self.assertEqual(
            report["all_complete_pairs"]["metrics"]["input_tokens"][
                "reduction_percent"
            ],
            80,
        )
        self.assertEqual(report["joint_success_pairs"]["pairs"], 1)
        self.assertEqual(
            report["joint_success_pairs"]["metrics"]["input_tokens"][
                "reduction_percent"
            ],
            50,
        )
        self.assertEqual(report["variant_failures"], 1)

    def test_missing_usage_and_configuration_changes_are_not_comparable_pairs(self):
        baseline, variant = run("manual"), run("catalog_full")
        variant["source_sha256"] = "other-source"
        report = reading.comparison([baseline, variant], "manual", "catalog_full")
        self.assertEqual(report["configuration_mismatch_pairs"], 1)
        self.assertEqual(report["all_complete_pairs"]["pairs"], 0)
        variant["source_sha256"] = baseline["source_sha256"]
        variant["agent"]["usage_complete"] = False
        report = reading.comparison([baseline, variant], "manual", "catalog_full")
        self.assertEqual(report["missing_usage_pairs"], 1)

    def test_negative_savings_and_zero_denominator_are_explicit(self):
        report = reading.comparison(
            [run("manual"), run("catalog_full", input_tokens=150)],
            "manual",
            "catalog_full",
        )
        self.assertEqual(
            report["all_complete_pairs"]["metrics"]["input_tokens"][
                "reduction_percent"
            ],
            -50,
        )
        report = reading.comparison(
            [
                run("manual", input_tokens=0, cached=0, output=0),
                run("catalog_full", input_tokens=1, cached=0, output=0),
            ],
            "manual",
            "catalog_full",
        )
        self.assertIsNone(
            report["all_complete_pairs"]["metrics"]["input_tokens"]["reduction_percent"]
        )

    def test_known_unexpected_model_is_excluded_even_when_other_trace_is_unknown(self):
        left, right = run("manual"), run("catalog_compact")
        right["agent"]["models"] = ["other-model"]
        report = reading.comparison([left, right], "manual", "catalog_compact")
        self.assertEqual(report["configuration_mismatch_pairs"], 1)
        self.assertEqual(report["all_complete_pairs"]["pairs"], 0)

    def test_terminal_error_classifier_uses_structured_errors_not_tool_output(self):
        with tempfile.TemporaryDirectory() as name:
            trace = Path(name).resolve() / "trace.jsonl"
            trace.write_text(
                json.dumps({"type": "error", "message": "rate_limit_exceeded"})
            )
            self.assertEqual(
                reading.terminal_block_reason(trace, ""), "cli-rate-limited"
            )
            trace.write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "aggregated_output": "401 Unauthorized rate_limit_exceeded",
                        },
                    }
                )
            )
            self.assertIsNone(reading.terminal_block_reason(trace, ""))

    def test_public_summary_omits_private_trace_commands_and_paths(self):
        row = run("manual")
        row.update(
            error_code=None,
            source_unchanged=True,
            checks=["auth", "core"],
            private_path="/private/example",
            command="cat secret",
            reading_evidence={"counts": {"list": 0}},
            static_reuse={"passed": True},
        )
        summary = reading.summarize(
            [row],
            {"source_commit": "a" * 40, "catalog_version": "0.4.0"},
            planned_total=24,
        )
        text = json.dumps(summary)
        self.assertNotIn("/private/example", text)
        self.assertNotIn("cat secret", text)
        self.assertEqual(summary["actual_model_calls"], 1)
        self.assertEqual(summary["planned_model_calls"], 24)

    def test_artifact_refuses_wrong_hash_before_unpacking(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name).resolve() / "candidate.tgz"
            path.write_bytes(b"not-a-tar")
            with self.assertRaisesRegex(reading.EvalError, "artifact-hash"):
                reading.local_artifact(path, "0" * 64, "a" * 40)


class ExperimentHookTests(fixtures.ReadingOrchestrationTests):
    """Use real trial/bookkeeping code while replacing model, grade and Git boundaries."""

    test_24_serial_attempts_share_source_and_preserve_results_with_real_summaries = None
    test_stdout_only_terminal_errors_stop_after_one_preserved_attempt = None
    test_postprocessing_failure_keeps_each_completed_attempt_and_original_bytes = None

    def setUp(self):
        super().setUp()
        self.zero_exit_terminal = False
        self.success_stderr = False
        self.validations = []
        self.reuse_calls = []

    def subprocess_run(self, argv, *args, **kwargs):
        import subprocess

        if argv[:2] == ["codex", "--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"fixture-cli 1.0\n")
        if argv[0] == "git":
            output = "f" * 40 + "\n" if argv[1:3] == ["rev-parse", "HEAD"] else ""
            return subprocess.CompletedProcess(
                argv, 0, stdout=output if kwargs.get("text") else output.encode()
            )
        raise AssertionError("Unexpected external command")

    def model_execute(self, *args, **kwargs):
        code = super().model_execute(*args, **kwargs)
        trace = args[3]
        if self.zero_exit_terminal:
            with trace.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "usage_limit_exceeded /private/never-publish",
                        }
                    )
                    + "\n"
                )
            return 0
        if self.success_stderr:
            kwargs.get("stderr_log", args[6] if len(args) > 6 else None).write_text(
                "ERROR usage limit reached in a normal tool diagnostic"
            )
            return 0
        return code

    def descriptor(self, **overrides):
        def source_validator(template, metadata, stacks):
            self.assertEqual(len(self.executions), 0)
            self.assertTrue((template / "README.md").is_file())
            self.assertEqual(metadata["protocol_id"], "fixture-transfer-v1")
            self.validations.append(tuple(stacks))

        def reuse_checker(generated, source, stack, commit):
            self.assertTrue((generated / "integration.json").is_file())
            self.reuse_calls.append(stack)
            return {
                "passed": True,
                "kind": "fixture-selected-reuse-checker",
                "runtime_causality_proven": False,
            }

        return {
            "id": "fixture-transfer-v1",
            "conditions": ("catalog_compact", "brief"),
            "prompt": transfer.prompt,
            "contract_factory": transfer.contract_factory,
            "source_file": __file__,
            "default_repeats": 1,
            "limits": ["Independent fixture protocol; no pooling."],
            "source_validator": source_validator,
            "reuse_checker": reuse_checker,
        } | overrides

    def invoke_experiment(self, experiment, *, stack="all"):
        actual_write = auth_eval.write_json

        def preserve(path, value):
            actual_write(path, value)
            if path.name == "result.json":
                self.original_results[path] = path.read_bytes()

        argv = [
            "core_reading_eval.py",
            "--artifact",
            str(self.artifact),
            "--artifact-sha256",
            self.artifact_sha256,
            "--source-commit",
            fixtures.COMMIT,
            "--model",
            "fixture-model",
            "--stack",
            stack,
            "--output",
            str(self.output),
        ]
        with ExitStack() as patches:
            patches.enter_context(patch.object(sys, "argv", argv))
            patches.enter_context(
                patch.object(reading.shutil, "which", return_value="/fixture/codex")
            )
            patches.enter_context(
                patch.object(core_eval, "freeze_sources", side_effect=self.freeze)
            )
            patches.enter_context(
                patch.object(auth_eval, "execute", side_effect=self.model_execute)
            )
            patches.enter_context(
                patch.object(auth_eval, "grade", side_effect=self.grade)
            )
            patches.enter_context(
                patch.object(
                    auth_eval.subprocess, "run", side_effect=self.subprocess_run
                )
            )
            patches.enter_context(
                patch.object(auth_eval, "write_json", side_effect=preserve)
            )
            patches.enter_context(redirect_stdout(io.StringIO()))
            return reading.main(experiment=experiment)

    def test_two_condition_protocol_uses_one_template_and_hashes_its_scope(self):
        self.assertEqual(self.invoke_experiment(self.descriptor()), 0)
        report = json.loads((self.output / "summary.json").read_text())
        expected = [
            (s, r, c)
            for s, r, c in reading.schedule(
                auth_eval.STACKS, 1, conditions=("catalog_compact", "brief")
            )
        ]
        self.assertEqual(
            [(r["stack"], r["repeat"], r["condition"]) for r in report["runs"]],
            expected,
        )
        self.assertEqual(report["suite"], "fixture-transfer-v1")
        self.assertEqual(report["actual_model_calls"], 8)
        self.assertEqual(report["repeats"], 1)
        self.assertEqual(report["protocol_id"], "fixture-transfer-v1")
        self.assertEqual(
            report["protocol_sha256"],
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report["source_evidence_sha256"],
            hashlib.sha256(
                (ROOT / "tools/source_evidence.py").read_bytes()
            ).hexdigest(),
        )
        self.assertNotIn(str(self.base), json.dumps(report))
        self.assertEqual(self.validations, [tuple(auth_eval.STACKS)])
        self.assertEqual(self.reuse_calls, [s for s, _, _ in expected])
        self.assertEqual(self.progress_counts, list(range(8)))
        self.assertEqual(len(self.templates), 1)
        self.assertEqual(len(report["comparisons"]), 1)
        self.assertEqual(report["comparisons"][0]["joint_success_pairs"]["pairs"], 4)
        self.assert_originals_preserved()

    def test_single_stack_protocol_rejects_other_stack_before_artifact_or_output_io(
        self,
    ):
        with (
            patch.object(reading, "local_artifact") as artifact,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as rejected,
        ):
            self.invoke_experiment(
                self.descriptor(allowed_stacks=("python",)), stack="go"
            )
        self.assertEqual(rejected.exception.code, 2)
        artifact.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.executions, [])

    def test_all_means_only_allowed_stacks_for_restricted_protocol(self):
        self.assertEqual(
            self.invoke_experiment(self.descriptor(allowed_stacks=("python",))), 0
        )
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(report["actual_model_calls"], 2)
        self.assertEqual({row["stack"] for row in report["runs"]}, {"python"})
        self.assertEqual(self.validations, [("python",)])

    def test_source_validator_cannot_rewrite_frozen_inputs_before_model_call(self):
        def mutating_validator(template, metadata, stacks):
            (template / "README.md").write_text("changed frozen input")

        with self.assertRaisesRegex(
            reading.EvalError, "source-validator-modified-source"
        ):
            self.invoke_experiment(self.descriptor(source_validator=mutating_validator))
        self.assertEqual(self.executions, [])

    def test_zero_exit_terminal_error_stops_after_first_retained_attempt(self):
        self.zero_exit_terminal = True
        self.assertEqual(self.invoke_experiment(self.descriptor()), 1)
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(report["actual_model_calls"], 1)
        self.assertEqual(report["planned_model_calls"], 8)
        self.assertEqual(report["blocked"], "cli-rate-limited")
        self.assertNotIn("/private/never-publish", json.dumps(report))
        self.assert_originals_preserved()

    def test_successful_attempt_does_not_classify_stderr_as_cli_terminal_error(self):
        self.success_stderr = True
        self.assertEqual(self.invoke_experiment(self.descriptor()), 0)
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(report["actual_model_calls"], 8)
        self.assertIsNone(report["blocked"])
        self.assertEqual(report["passed"], 8)

    def test_default_three_condition_main_preserves_24_trial_behavior(self):
        self.assertEqual(self.invoke(), 0)
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(report["suite"], "core-reading-candidate-v1")
        self.assertEqual(report["actual_model_calls"], 24)
        self.assertEqual(set(report["groups"]), set(reading.CONDITIONS))
        self.assertEqual(len(report["comparisons"]), 3)
        self.assertEqual(self.progress_counts, list(range(24)))
        self.assert_originals_preserved()
