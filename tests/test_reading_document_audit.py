"""Synthetic whole-output matches are harness tests, not agent performance results."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from reading_document_audit import document_output_evidence


class DocumentOutputAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.snapshot = Path(self.directory.name).resolve() / "snapshot"
        self.snapshot.mkdir()
        self.trace = self.snapshot.parent / "trace.jsonl"
        self.events = []

    def document(self, path="README.md", content=b"Complete public guide.\n"):
        location = self.snapshot / path
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(content)
        return location

    def event(
        self,
        output,
        *,
        code=0,
        status="completed",
        kind="item.completed",
        identifier=None,
    ):
        self.events.append(
            {
                "type": kind,
                "item": {
                    "type": "command_execution",
                    "id": identifier or str(len(self.events)),
                    "command": "raw command must never be returned",
                    "aggregated_output": output,
                    "exit_code": code,
                    "status": status,
                },
            }
        )

    def audit(self):
        self.trace.write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        return document_output_evidence(self.trace, self.snapshot, "python")

    def test_whole_document_inside_output_records_hash_and_relative_path_only(self):
        content = "Complete public guide.\n"
        self.document(content=content.encode())
        self.event("prefix\n" + content + "suffix")
        result = self.audit()
        self.assertEqual(result["evidence_kind"], "whole_document_output_observed")
        self.assertEqual(result["events_with_whole_document_output"], 1)
        self.assertEqual(result["content_event_matches"], 1)
        self.assertEqual(
            result["documents"],
            [
                {
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "paths": ["README.md"],
                    "output_event_counts": {"successful": 1, "failed": 0, "unknown": 0},
                }
            ],
        )
        serialized = json.dumps(result)
        for private in (
            "Complete public guide.",
            "raw command",
            str(self.snapshot),
            "aggregated_output",
        ):
            self.assertNotIn(private, serialized)

    def test_failed_compound_output_is_evidence_but_not_successful_command(self):
        self.document()
        self.event(
            "Complete public guide.\nmissing later file", code=1, status="failed"
        )
        self.event("Complete public guide.\n", code="0", status="completed")
        result = self.audit()
        self.assertEqual(
            result["documents"][0]["output_event_counts"],
            {"successful": 0, "failed": 1, "unknown": 1},
        )

    def test_duplicate_terminal_ids_and_started_events_do_not_inflate_counts(self):
        self.document()
        self.event("Complete public guide.\n", identifier="same")
        self.events.append(self.events[0])
        self.event("Complete public guide.\n", kind="item.started")
        result = self.audit()
        self.assertEqual(result["events_with_whole_document_output"], 1)
        self.assertEqual(result["documents"][0]["output_event_counts"]["successful"], 1)

    def test_partial_truncated_normalized_line_endings_and_empty_files_do_not_match(
        self,
    ):
        self.document(content=b"First line\r\nSecond line\r\n")
        self.document("docs/core-standards.md", b"")
        self.event("First line\r\n...truncated...")
        self.event("First line\nSecond line\n")
        self.event("First line\r\nSecond line")
        self.assertEqual(self.audit()["documents"], [])

    def test_source_and_packaged_identical_bytes_share_one_content_record(self):
        self.document()
        self.document("catalog/package/snapshot/README.md")
        self.event("Complete public guide.\n")
        result = self.audit()
        self.assertEqual(result["candidate_content_count"], 1)
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(result["content_event_matches"], 1)
        self.assertEqual(
            result["documents"][0]["paths"],
            ["README.md", "catalog/package/snapshot/README.md"],
        )

    def test_only_small_selected_stack_whitelist_documents_are_candidates(self):
        self.document("libraries/python/README.md", b"Python API guide\n")
        self.document("libraries/go/README.md", b"Other stack guide\n")
        self.document("generated/README.md", b"Generated guide\n")
        self.document("docs/unrelated.md", b"Unrelated guide\n")
        self.document("README.md", b"x" * 2_000_000)
        self.event(
            "Python API guide\nOther stack guide\nGenerated guide\nUnrelated guide\n"
            + "x" * 2_000_000
        )
        result = self.audit()
        self.assertEqual(result["candidate_content_count"], 1)
        self.assertEqual(
            result["documents"][0]["paths"], ["libraries/python/README.md"]
        )

    def test_symlink_leaf_and_directory_and_invalid_utf8_are_not_read(self):
        outside = self.snapshot.parent / "private"
        outside.mkdir()
        (outside / "README.md").write_text("Private content\n")
        (self.snapshot / "README.md").symlink_to(outside / "README.md")
        (self.snapshot / "libraries").mkdir()
        (self.snapshot / "libraries/python").symlink_to(
            outside, target_is_directory=True
        )
        self.document("docs/core-standards.md", b"\xff invalid UTF8")
        self.event("Private content\n")
        result = self.audit()
        self.assertEqual(result["candidate_content_count"], 0)
        self.assertEqual(result["documents"], [])

    def test_three_specs_and_two_skills_are_included(self):
        paths = [
            f"features/{feature}/specification.md"
            for feature in ("auth", "authorization", "listing")
        ]
        paths += [f"skills/integrate-{skill}/SKILL.md" for skill in ("auth", "core")]
        for path in paths:
            self.document(path, ("Unique guide: " + path + "\n").encode())
        self.event("".join("Unique guide: " + path + "\n" for path in paths))
        self.assertEqual(len(self.audit()["documents"]), 5)

    def test_unknown_stack_rejected_before_any_file_is_read(self):
        with self.assertRaises(ValueError):
            document_output_evidence(self.trace, self.snapshot, "unknown")

    def test_nonregular_file_is_not_opened_and_cannot_block_audit(self):
        os.mkfifo(self.snapshot / "README.md")
        self.trace.write_text("")
        with patch(
            "reading_document_audit.os.open",
            side_effect=AssertionError("nonregular file opened"),
        ):
            result = document_output_evidence(self.trace, self.snapshot, "python")
        self.assertEqual(result["candidate_content_count"], 0)

    def test_malformed_utf8_json_and_noncommand_items_are_excluded(self):
        self.document()
        self.trace.write_bytes(
            b"\xff\nnot-json\n[]\n"
            + json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "aggregated_output": "Complete public guide.\n",
                    },
                }
            ).encode()
            + b"\n"
        )
        result = document_output_evidence(self.trace, self.snapshot, "python")
        self.assertEqual(result["malformed_events"], 3)
        self.assertEqual(result["documents"], [])
