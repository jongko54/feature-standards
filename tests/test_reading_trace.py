"""Synthetic traces test evidence classification, not model performance."""

from __future__ import annotations

import hashlib
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from reading_trace import reading_evidence

CLI = "node ../catalog/package/src/cli.mjs"


def context(
    feature="auth", profile="browser-session-v1", stack="python", compact=False
):
    return f"{CLI} context --feature {feature} --profile {profile} --stack {stack}" + (
        " --compact" if compact else ""
    )


class ReadingTraceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.snapshot = Path(self.directory.name).resolve() / "snapshot"
        (self.snapshot / "generated").mkdir(parents=True)
        self.trace = self.snapshot.parent / "trace.jsonl"
        self.events = []

    def command(self, text, *, code=0, status="completed", event_type="item.completed"):
        item = {
            "id": str(len(self.events)),
            "type": "command_execution",
            "command": "/bin/zsh -lc " + shlex.quote(text),
            "exit_code": code,
            "aggregated_output": "not exported",
        }
        if status is not None:
            item["status"] = status
        self.events.append({"type": event_type, "item": item})

    def evidence(self):
        self.trace.write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        return reading_evidence(self.trace, "python", self.snapshot)

    def document(self, name, text="public guide"):
        path = self.snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_actual_cli_commands_are_counted_by_selection_and_mode(self):
        self.command(f"{CLI} list && {context()}")
        self.command(context("authorization", "rbac-v1", compact=True))
        self.command(context("listing", "offset-list-v1"))
        result = self.evidence()
        self.assertEqual(
            (result["list"], result["full_context"], result["compact_context"]),
            (1, 2, 1),
        )
        self.assertEqual(result["by_feature"]["auth"]["full_context"], 1)
        self.assertEqual(result["by_feature"]["authorization"]["compact_context"], 1)
        self.assertEqual(result["by_feature"]["listing"]["full_context"], 1)

    def test_echo_printf_heredoc_and_indirect_code_are_not_cli_calls(self):
        for command in (
            f"echo {shlex.quote(context())}",
            f"printf '%s' {shlex.quote(context())}",
            f"cat <<'EOF'\n{context()}\nEOF",
            f"node -e {shlex.quote('console.log(' + json.dumps(context()) + ')')}",
            "python3 invoke_catalog.py",
            "node ../other/catalog/package/src/cli.mjs list",
        ):
            self.command(command)
        result = self.evidence()
        self.assertEqual(
            result["list"] + result["full_context"] + result["compact_context"], 0
        )
        self.assertGreater(result["unclassified_commands"], 0)

    def test_failed_attempts_and_exact_success_types_are_separate(self):
        self.command(context(), code=1, status="failed")
        self.command(context(), code=0, status="failed")
        self.command(context(), code="0")
        self.command(context(), code=True)
        self.command(context(), status=None)
        self.command(context(), event_type="item.started")
        result = self.evidence()
        self.assertEqual(result["failed_cli_attempts"], 2)
        self.assertEqual(result["full_context"], 1)

    def test_wrong_selection_duplicate_flags_and_missing_selection_do_not_match(self):
        for command in (
            context(stack="rust"),
            context(profile="browser-session-v2"),
            context(feature="unknown"),
            context() + " --compact --compact",
            f"{CLI} context --stack python",
            f"{CLI} list --compact",
        ):
            self.command(command)
        result = self.evidence()
        self.assertEqual(
            result["full_context"] + result["compact_context"] + result["list"], 0
        )
        self.assertEqual(result["unmatched_cli_attempts"], 6)

    def test_ambiguous_shell_success_does_not_prove_each_subcommand_succeeded(self):
        for suffix in ("; true", " || true", " | cat", " > /dev/null", "\ntrue"):
            self.command(context() + suffix)
        result = self.evidence()
        self.assertEqual(result["full_context"], 0)
        self.assertEqual(result["unclassified_commands"], 5)

    def test_known_read_paths_searches_categories_and_hashes_are_separate(self):
        self.document("README.md")
        self.document("libraries/python/README.md")
        self.document("examples/core-python/app.py")
        self.document("skills/integrate-core/SKILL.md")
        self.document("features/listing/specification.md")
        self.command("cat ../README.md")
        self.command("sed -n '1,80p' ../libraries/python/README.md")
        self.command("head -n 40 ../examples/core-python/app.py")
        self.command("tail -20 ../skills/integrate-core/SKILL.md")
        self.command("rg -n Policy ../features/listing/specification.md")
        self.command("rg --files ../examples/core-python")
        result = self.evidence()
        self.assertEqual(
            (result["doc_read_commands"], result["doc_search_commands"]), (4, 1)
        )
        docs = {d["path"]: d for d in result["documents"]}
        self.assertEqual(docs["README.md"]["kind"], "manual_readme")
        self.assertEqual(docs["libraries/python/README.md"]["kind"], "public_api_guide")
        self.assertEqual(docs["examples/core-python/app.py"]["kind"], "consumer")
        self.assertEqual(docs["skills/integrate-core/SKILL.md"]["kind"], "skill")
        self.assertEqual(
            docs["features/listing/specification.md"]["kind"], "specification"
        )
        self.assertEqual(
            docs["README.md"]["sha256"], hashlib.sha256(b"public guide").hexdigest()
        )

    def test_literals_and_failed_readers_are_not_doc_reads(self):
        self.command("echo ../README.md")
        self.command("printf '%s' ../libraries/python/README.md")
        self.command("cat ../README.md", code=1, status="failed")
        self.command("sed -i 's/x/y/' ../README.md")
        self.command("cat ./README.md")
        self.command("cat ../docs/*.md")
        result = self.evidence()
        self.assertEqual(result["doc_read_commands"], 0)
        self.assertEqual(result["documents"], [])

    def test_packaged_documents_and_absolute_paths_are_sanitized(self):
        path = self.document("catalog/package/snapshot/docs/core-standards.md")
        self.command("cat " + shlex.quote(str(path)))
        self.command("cat /outside/private/README.md")
        result = self.evidence()
        self.assertEqual(
            result["documents"][0]["path"],
            "catalog/package/snapshot/docs/core-standards.md",
        )
        self.assertEqual(result["documents"][0]["kind"], "documentation")
        self.assertNotIn(str(self.snapshot.parent), json.dumps(result))
        self.assertNotIn("not exported", json.dumps(result))

    def test_document_hash_does_not_follow_symlinks(self):
        target = self.snapshot.parent / "private.txt"
        target.write_text("never hash this")
        (self.snapshot / "README.md").symlink_to(target)
        self.command("cat ../README.md")
        result = self.evidence()
        self.assertIsNone(result["documents"][0]["sha256"])

    def test_old_absolute_document_root_needs_independent_pwd_evidence(self):
        self.document("README.md")
        old = "/benchmark/feature-auth-eval-abcdefgh/snapshot"
        self.command(f"cat {old}/README.md")
        self.assertEqual(self.evidence()["documents"], [])
        self.command("pwd")
        self.events[-1]["item"]["aggregated_output"] = old + "/generated\n"
        self.assertEqual(self.evidence()["documents"][0]["path"], "README.md")

    def test_failed_compound_and_cwd_changes_remain_unclassified(self):
        self.command(
            f"{context()} && {context('listing', 'offset-list-v1')}",
            code=1,
            status="failed",
        )
        self.command("cd /elsewhere && cat ../README.md")
        result = self.evidence()
        self.assertEqual(result["failed_cli_attempts"], 0)
        self.assertEqual(result["doc_read_commands"], 0)
        self.assertEqual(result["unclassified_commands"], 2)

    def test_duplicate_terminal_events_do_not_inflate_evidence(self):
        self.command(context())
        self.events.append(self.events[0])
        result = self.evidence()
        self.assertEqual(result["full_context"], 1)
        self.assertTrue(result["limits"])
        self.assertIn("evidence", result["evidence_kind"])

    def test_unknown_stack_is_rejected_without_reading_trace(self):
        with self.assertRaises(ValueError):
            reading_evidence(self.trace, "unknown")
