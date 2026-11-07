"""Exercise real reading-run bookkeeping without models, servers or builds."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import auth_eval
import core_eval
import core_reading_eval as reading
import reading_trace

COMMIT = "a" * 40
PRIVATE_MESSAGE = "private-provider-token /private/reading-fixture/account-secret"


def archive_bytes(*, version="0.4.0", package_name="feature-standards",
                  source_commit=COMMIT, source_dirty=False, snapshot_dirty=False,
                  source_modified=False, document_hash=None):
    document = b"Selected public API guide.\n"
    provenance = {
        "sourceCommit": source_commit,
        "sourceDirty": source_dirty,
        "snapshotDirty": snapshot_dirty,
        "files": {
            "docs/selected.md": {
                "sourceModified": source_modified,
                "sha256": document_hash or hashlib.sha256(document).hexdigest(),
            }
        },
    }
    files = {
        "package/package.json": json.dumps({
            "name": package_name, "version": version,
        }).encode(),
        "package/snapshot/provenance.json": json.dumps(provenance).encode(),
        "package/snapshot/docs/selected.md": document,
        "package/src/cli.mjs": b"// candidate fixture; never executed\n",
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return stream.getvalue()


def application_sources(stack):
    """Small static-evidence fixtures; the independent grader is an external fake."""
    return {
        "python": {
            "app.py": "from feature_auth import create_app, current_user\n"
            "from feature_standards.authorization import Policy\n"
            "from feature_standards.listing import parse_query, page\n"
            "app = create_app()\n"
            "def profile(request): return current_user(request)\n"
            "def product(): return page([], parse_query('', None), Policy([]))\n",
        },
        "go": {
            "main.go": 'package main\nimport (\n'
            '"github.com/jongko54/feature-standards/implementations/go-net-http/auth"\n'
            '"github.com/jongko54/feature-standards/libraries/go/authorization"\n'
            '"github.com/jongko54/feature-standards/libraries/go/listing"\n)\n'
            'func route() { auth.CurrentUser(); authorization.NewPolicy(); '
            'policy.Decide(); listing.ParseQuery(); listing.Page() }\n',
        },
        "java": {
            "Main.java": "import dev.featurestandards.auth.AuthService;\n"
            "import dev.featurestandards.core.authorization.AuthorizationPolicy;\n"
            "import dev.featurestandards.core.listing.Listing;\n"
            "class Main { void route() { policy.decide(); Listing.parseQuery(); Listing.page(); } }\n",
            "pom.xml": '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<dependencies><dependency><artifactId>java-spring-auth</artifactId></dependency>'
            '<dependency><artifactId>feature-standards-core</artifactId></dependency>'
            '</dependencies></project>',
        },
        "rust": {
            "Cargo.toml": '[dependencies]\nfeature-standards-auth = { path = "../auth" }\n'
            'feature-standards-core = { path = "../core" }\n',
            "main.rs": "use feature_standards_auth::current_user;\n"
            "use feature_standards_core::{Policy, parse_query, page};\n"
            "fn route() { current_user(); Policy::new(); policy.decide(); parse_query(); page(); }\n",
        },
    }[stack]


class ReadingOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reading-orchestration-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.artifact = self.base / "candidate.tgz"
        self.artifact.write_bytes(archive_bytes())
        self.artifact_sha256 = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.output = self.base / "results"
        self.executions = []
        self.original_results = {}
        self.templates = []
        self.progress_counts = []
        self.model_active = False
        self.terminal = None
        self.stderr = ""
        self.real_subprocess_run = subprocess.run

    def freeze(self, root, destination, catalog, *, commit):
        self.assertEqual(commit, COMMIT)
        self.assertEqual(hashlib.sha256(catalog).hexdigest(), self.artifact_sha256)
        destination.mkdir(mode=0o700)
        (destination / "README.md").write_text("Fixed source for all 24 trials.\n")
        implementation = auth_eval.fingerprint(destination)
        core_eval.extract_archive(catalog, destination / "catalog")
        self.templates.append(destination)
        return {
            "source_commit": commit,
            "source_dirty": False,
            "implementation_source_sha256": auth_eval.digest_hashes(implementation),
            "source_sha256": auth_eval.digest_hashes(auth_eval.fingerprint(destination)),
            "catalog_snapshot_sha256": auth_eval.digest_hashes(
                auth_eval.fingerprint(destination / "catalog")
            ),
        }

    def subprocess_run(self, argv, *args, **kwargs):
        if argv[:2] == ["codex", "--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"fixture-cli 1.0\n")
        return self.real_subprocess_run(argv, *args, **kwargs)

    def model_execute(self, argv, cwd, env, log, deadline, stdin=None, stderr_log=None):
        self.assertFalse(self.model_active, "Model attempts must run serially")
        self.model_active = True
        try:
            self.assertEqual(argv[:2], ["codex", "exec"])
            task = stdin.decode()
            stack = next(stack for stack in auth_eval.STACKS
                         if f'"stack":"{stack}"' in task)
            condition = (
                "catalog_compact" if " --compact" in task
                else "catalog_full" if "First run node" in task else "manual"
            )
            self.executions.append((stack, condition, task))
            self.progress_counts.append(json.loads(
                (self.output / "progress.json").read_text()
            )["actual_model_calls"])
            for name, content in application_sources(stack).items():
                (cwd / name).write_text(content)
            auth_eval.write_json(cwd / "integration.json", {
                "stack": stack, "profile": "browser-session-v1", "source_commit": COMMIT,
            })
            auth_eval.write_json(cwd / "run.json", {
                "build": [], "start": {"argv": ["fixture-server"], "cwd": "."},
            })
            events = [{"type": "item.completed", "item": {
                "type": "command_execution", "command": "cat ../README.md",
                "exit_code": 0, "aggregated_output": "Fixed source.\n",
            }}]
            if self.terminal:
                events.append({"type": "error", "message": self.terminal})
            else:
                events.append({"type": "turn.completed", "model": "fixture-model", "usage": {
                    "input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10,
                }})
            log.write_text("".join(json.dumps(event) + "\n" for event in events))
            stderr_log.write_text(self.stderr)
            return 1 if self.terminal or self.stderr else 0
        finally:
            self.model_active = False

    def grade(self, generated, output, env, port, origin, deadline, *, http_grader):
        return [f"fixture-check-{index}" for index in range(143)]

    def invoke(self, *, evidence=None):
        actual_write_json = auth_eval.write_json

        def preserve_original(path, value):
            actual_write_json(path, value)
            if path.name == "result.json":
                self.original_results[path] = path.read_bytes()

        argv = [
            "core_reading_eval.py", "--artifact", str(self.artifact),
            "--artifact-sha256", self.artifact_sha256, "--source-commit", COMMIT,
            "--model", "fixture-model", "--stack", "all", "--repeats", "2",
            "--timeout", "600", "--output", str(self.output),
        ]
        with ExitStack() as patches:
            patches.enter_context(patch.object(sys, "argv", argv))
            patches.enter_context(patch.object(reading.shutil, "which", return_value="/fixture/codex"))
            patches.enter_context(patch.object(core_eval, "freeze_sources", side_effect=self.freeze))
            patches.enter_context(patch.object(auth_eval, "execute", side_effect=self.model_execute))
            patches.enter_context(patch.object(auth_eval, "grade", side_effect=self.grade))
            patches.enter_context(patch.object(auth_eval.subprocess, "run", side_effect=self.subprocess_run))
            patches.enter_context(patch.object(auth_eval, "write_json", side_effect=preserve_original))
            if evidence is not None:
                patches.enter_context(patch.object(reading_trace, "reading_evidence", side_effect=evidence))
            patches.enter_context(redirect_stdout(io.StringIO()))
            return reading.main()

    def assert_originals_preserved(self):
        self.assertTrue(self.original_results)
        for path, original in self.original_results.items():
            self.assertEqual(path.read_bytes(), original)
            analysis = json.loads(path.with_name("analysis.json").read_text())
            self.assertEqual(analysis["original_result_sha256"], hashlib.sha256(original).hexdigest())

    def test_24_serial_attempts_share_source_and_preserve_results_with_real_summaries(self):
        self.assertEqual(self.invoke(), 0)
        summary = json.loads((self.output / "summary.json").read_text())
        progress = json.loads((self.output / "progress.json").read_text())
        expected = reading.schedule(auth_eval.STACKS, 2)
        self.assertEqual([(stack, condition) for stack, condition, _ in self.executions],
                         [(stack, condition) for stack, _, condition in expected])
        self.assertEqual(self.progress_counts, list(range(24)))
        self.assertEqual(len(self.templates), 1)
        self.assertEqual(summary["actual_model_calls"], 24)
        self.assertEqual(summary["planned_model_calls"], 24)
        self.assertEqual(summary["passed"], 24)
        self.assertTrue(summary["complete"])
        self.assertIsNone(summary["blocked"])
        self.assertEqual(progress["actual_model_calls"], 24)
        self.assertEqual(len({row["original_result_sha256"] for row in summary["runs"]}), 24)
        self.assertEqual(len({row["source_sha256"] for row in map(json.loads, self.original_results.values())}), 1)
        self.assertEqual([(row["stack"], row["repeat"], row["condition"]) for row in summary["runs"]], expected)
        for comparison in summary["comparisons"]:
            self.assertEqual(comparison["all_complete_pairs"]["pairs"], 8)
            self.assertEqual(comparison["joint_success_pairs"]["pairs"], 8)
            self.assertEqual(comparison["all_complete_pairs"]["metrics"]["total_tokens"]["reference_sum"], 880)
        self.assert_originals_preserved()

    def test_stdout_only_terminal_errors_stop_after_one_preserved_attempt(self):
        cases = (
            ("usage limit reached", "cli-rate-limited"),
            ("authentication required", "cli-authentication-failed"),
            ("model fixture-model is not supported", "cli-model-unavailable"),
        )
        for index, (message, expected) in enumerate(cases):
            with self.subTest(error=expected):
                self.output = self.base / f"terminal-{index}"
                self.executions.clear()
                self.original_results.clear()
                self.terminal = message + " " + PRIVATE_MESSAGE
                self.assertEqual(self.invoke(), 1)
                summary = json.loads((self.output / "summary.json").read_text())
                progress = json.loads((self.output / "progress.json").read_text())
                self.assertEqual(len(self.executions), 1)
                self.assertEqual(summary["actual_model_calls"], 1)
                self.assertEqual(summary["planned_model_calls"], 24)
                self.assertEqual(summary["blocked"], expected)
                self.assertFalse(summary["complete"])
                self.assertEqual(progress["blocked"], expected)
                self.assertEqual(summary["runs"][0]["error_code"], "agent-failed")
                self.assertNotIn(PRIVATE_MESSAGE, json.dumps(summary))
                self.assertEqual(json.loads(next(iter(self.original_results.values())))["error_code"], "agent-failed")
                self.assert_originals_preserved()

    def test_postprocessing_failure_keeps_each_completed_attempt_and_original_bytes(self):
        def unavailable(*args):
            raise ValueError(PRIVATE_MESSAGE)

        self.invoke(evidence=unavailable)
        summary = json.loads((self.output / "summary.json").read_text())
        progress = json.loads((self.output / "progress.json").read_text())
        self.assertEqual(summary["actual_model_calls"], len(self.executions))
        self.assertGreaterEqual(summary["actual_model_calls"], 1)
        self.assertEqual(progress["actual_model_calls"], len(self.executions))
        self.assertEqual(len(summary["runs"]), len(self.executions))
        self.assertEqual(summary["passed"], 0)
        self.assertTrue(all(not row["passed"] and row["error_code"] for row in summary["runs"]))
        self.assertNotIn(PRIVATE_MESSAGE, json.dumps(summary))
        self.assertTrue(all(json.loads(data)["passed"] for data in self.original_results.values()))
        self.assert_originals_preserved()


class CandidateArtifactBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reading-artifact-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve() / "candidate.tgz"

    def check(self, **changes):
        data = archive_bytes(**changes)
        self.path.write_bytes(data)
        return reading.local_artifact(self.path, hashlib.sha256(data).hexdigest(), COMMIT)

    def test_clean_new_candidate_validates_document_bytes_and_remains_unpublished(self):
        data, metadata = self.check()
        self.assertEqual(data, self.path.read_bytes())
        self.assertEqual(metadata["catalog_version"], "0.4.0")
        self.assertEqual(metadata["candidate_source_commit"], COMMIT)
        self.assertEqual(metadata["catalog_kind"], "local-source-candidate")
        self.assertFalse(metadata["catalog_public_download_verified"])
        self.assertEqual(metadata["catalog_sha256"], hashlib.sha256(data).hexdigest())

    def test_other_package_versions_commits_and_dirty_candidates_are_rejected(self):
        for changes in (
            {"version": "0.3.2"}, {"version": "0.4.1"},
            {"package_name": "another-package"}, {"source_commit": "b" * 40},
            {"source_dirty": True}, {"snapshot_dirty": True},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                auth_eval.EvalError, "candidate-provenance-mismatch"
            ):
                self.check(**changes)

    def test_document_hash_or_source_modified_mismatch_is_rejected_despite_valid_archive_hash(self):
        for changes in ({"document_hash": "0" * 64}, {"source_modified": True}):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                auth_eval.EvalError, "candidate-document-hash-mismatch"
            ):
                self.check(**changes)


if __name__ == "__main__":
    unittest.main()
