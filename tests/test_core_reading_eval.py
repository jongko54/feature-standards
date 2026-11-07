"""Behavior tests for new-source reading comparisons; no live model calls."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import core_reading_eval as reading


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
