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
from reading_document_audit import catalog_output_evidence, document_output_evidence


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

    def test_selected_stack_brief_output_is_audited_without_other_stack_credit(self):
        selected = b"# Selected Python brief\nUse public APIs.\n"
        other = b"# Rust brief\nOther API.\n"
        self.document("docs/ai-briefs/python.md", selected)
        self.document("catalog/package/snapshot/docs/ai-briefs/python.md", selected)
        self.document("docs/ai-briefs/rust.md", other)
        self.event(selected.decode() + other.decode())
        result = self.audit()
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(
            result["documents"][0]["paths"],
            [
                "catalog/package/snapshot/docs/ai-briefs/python.md",
                "docs/ai-briefs/python.md",
            ],
        )
        self.assertEqual(
            result["documents"][0]["sha256"], hashlib.sha256(selected).hexdigest()
        )

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


class CatalogOutputAuditTests(unittest.TestCase):
    document = DocumentOutputAuditTests.document
    event = DocumentOutputAuditTests.event

    def setUp(self):
        DocumentOutputAuditTests.setUp(self)
        self.commit = "a" * 40
        self.digest = hashlib.sha256(b"Captured guide\n").hexdigest()
        self.provenance = {
            "schemaVersion": 1,
            "sourceCommit": self.commit,
            "sourceDirty": False,
            "snapshotDirty": False,
            "files": {
                "docs/core-standards.md": {
                    "sha256": self.digest,
                    "sourceModified": False,
                }
            },
        }
        self.document(
            "catalog/package/snapshot/provenance.json",
            json.dumps(self.provenance).encode(),
        )

    def context(self, feature="auth", *, compact=False):
        reference = {
            "readPath": "/captured/snapshot/catalog/package/snapshot/docs/core-standards.md",
            "sha256": self.digest,
            "sourceModified": False,
        }
        result = {
            "schemaVersion": 1,
            "package": {"name": "feature-standards", "version": "0.4.0"},
            "feature": feature,
            "profile": {
                "auth": "browser-session-v1",
                "authorization": "rbac-v1",
                "listing": "offset-list-v1",
            }[feature],
            "stack": {"id": "python"},
            "optionalAddons": [],
            "limits": ["Captured context"],
        }
        if compact:
            result.update(
                mode="compact",
                readOnly=True,
                readFirst=[reference.copy() for _ in range(3)],
                contract={
                    key: reference.copy()
                    for key in (
                        "specification",
                        "openapi",
                        "scenarios",
                        "profileGuide",
                        "manifest",
                    )
                },
                relatedSpecifications=[],
                migrations=[],
                packageMetadata={},
                source={
                    "required": True,
                    "commit": self.commit,
                    "sourceDirty": False,
                    "snapshotDirty": False,
                    "entrypoints": [],
                },
                fullContext={"executed": False, "argv": []},
            )
            if feature != "auth":
                result["contract"]["releaseReceipt"] = reference.copy()
        else:
            full_reference = reference | {
                "sourcePath": "docs/core-standards.md",
                "packagePath": "snapshot/docs/core-standards.md",
            }
            documents = {
                key: full_reference.copy()
                for key in (
                    "manifest",
                    "specification",
                    "openapi",
                    "scenarios",
                    "profileGuide",
                    "apiGuide",
                    "consumerGuide",
                    "integrationSkill",
                    "integrationGuide",
                )
            }
            documents["generatorGuide" if feature == "auth" else "releaseReceipt"] = (
                full_reference.copy()
            )
            documents.update(
                relatedSpecifications=[], migrations=[], profileReferences=[]
            )
            result.update(
                provenance={
                    key: value
                    for key, value in self.provenance.items()
                    if key != "files"
                },
                packagedDocuments=documents,
                sourceCheckout={
                    "required": True,
                    "entrypoints": [],
                    "install": [],
                    "checks": [],
                    "environment": {},
                },
            )
        return result

    def audit(self):
        self.trace.write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        return catalog_output_evidence(self.trace, self.snapshot, "python")

    def test_three_concatenated_contexts_are_one_event_and_three_selections(self):
        self.event(
            "progress\n"
            + "\n".join(
                json.dumps(self.context(feature))
                for feature in ("auth", "authorization", "listing")
            )
        )
        result = self.audit()
        self.assertTrue(result["snapshot_provenance_available"])
        self.assertEqual(
            result["full_context"], {"successful": 1, "failed": 0, "unknown": 0}
        )
        self.assertEqual(result["unique_selected_contexts"], 3)
        for feature in ("auth", "authorization", "listing"):
            self.assertEqual(
                result["by_feature"][feature]["full_context"]["successful"], 1
            )

    def test_compact_failed_command_and_repeated_json_event_are_counted_once(self):
        payload = json.dumps(self.context(compact=True))
        self.event(payload + "\n" + payload, code=1, status="failed", identifier="same")
        self.events.append(self.events[0])
        self.event(payload, code="0")
        result = self.audit()
        self.assertEqual(
            result["compact_context"], {"successful": 0, "failed": 1, "unknown": 1}
        )
        self.assertEqual(result["unique_selected_contexts"], 1)

    def test_echo_data_is_output_evidence_and_never_cli_execution_proof(self):
        self.event(json.dumps(self.context()))
        self.events[0]["item"]["command"] = "echo complete JSON data"
        result = self.audit()
        self.assertEqual(result["full_context"]["successful"], 1)
        self.assertEqual(
            result["evidence_kind"], "complete_selected_context_output_observed"
        )
        encoded = json.dumps(result)
        for private in (
            "/captured/",
            "readPath",
            "sourceCommit",
            "echo complete JSON data",
            self.commit,
            self.digest,
        ):
            self.assertNotIn(private, encoded)
        self.assertTrue(any("CLI execution" in limit for limit in result["limits"]))

    def test_wrong_package_version_selection_commit_and_compact_flags_are_rejected(
        self,
    ):
        mutations = [
            ("package", "name", "other-package"),
            ("package", "version", "0.3.2"),
            ("stack", "id", "go"),
            ("provenance", "sourceCommit", "b" * 40),
            (None, "profile", "browser-session-v2"),
            (None, "feature", "other"),
        ]
        for container, key, value in mutations:
            context = self.context()
            (context[container] if container else context)[key] = value
            self.event(json.dumps(context))
        for container, key, value in (
            (None, "readOnly", False),
            ("source", "commit", "b" * 40),
        ):
            context = self.context(compact=True)
            (context[container] if container else context)[key] = value
            self.event(json.dumps(context))
        result = self.audit()
        self.assertEqual(result["unique_selected_contexts"], 0)

    def test_truncation_quoted_json_strings_malformed_and_similar_examples_are_not_contexts(
        self,
    ):
        encoded = json.dumps(self.context())
        for output in (
            encoded[:-1],
            json.dumps(encoded),
            '{"package":{"name":"feature-standards"}}',
            encoded.replace('"profile":', "profile:"),
            encoded.replace('"schemaVersion": 1', '"schemaVersion": true'),
        ):
            self.event(output)
        result = self.audit()
        self.assertEqual(result["full_context"]["successful"], 0)
        self.assertEqual(result["unique_selected_contexts"], 0)

    def test_document_reference_hashes_must_match_captured_packaged_provenance(self):
        context = self.context(compact=True)
        context["readFirst"][0]["sha256"] = "c" * 64
        self.event(json.dumps(context))
        full = self.context()
        full["packagedDocuments"]["apiGuide"]["sourcePath"] = "docs/other.md"
        self.event(json.dumps(full))
        self.assertEqual(self.audit()["unique_selected_contexts"], 0)

    def test_missing_or_symlinked_provenance_makes_reference_unavailable(self):
        path = self.snapshot / "catalog/package/snapshot/provenance.json"
        path.unlink()
        self.event(json.dumps(self.context()))
        self.assertFalse(self.audit()["snapshot_provenance_available"])
        outside = self.snapshot.parent / "outside.json"
        outside.write_text(json.dumps(self.provenance))
        path.symlink_to(outside)
        self.assertFalse(self.audit()["snapshot_provenance_available"])

    def test_unknown_stack_is_rejected_before_trace_io(self):
        with self.assertRaises(ValueError):
            catalog_output_evidence(self.trace, self.snapshot, "unknown")
