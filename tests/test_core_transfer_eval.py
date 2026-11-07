"""Pure transfer-protocol checks, without network, models or builds."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auth_eval
import core_eval
import core_reading_eval as reading
import core_transfer_eval as transfer


class TransferProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tasks = json.loads((ROOT / "evals/core/tasks.json").read_text())
        self.commit = "a" * 40

    def test_conditions_have_identical_notes_body_and_original_compact_header(self):
        for stack in auth_eval.STACKS:
            with self.subTest(stack=stack):
                original = reading.prompt(
                    stack, self.commit, self.tasks, "catalog_compact"
                )
                compact = transfer.prompt(
                    stack, self.commit, self.tasks, "catalog_compact"
                )
                brief = transfer.prompt(stack, self.commit, self.tasks, "brief")
                original_head, original_body = original.split(
                    "\n\nCurrent directory", 1
                )
                compact_head, compact_body = compact.split("\n\nCurrent directory", 1)
                brief_head, brief_body = brief.split("\n\nCurrent directory", 1)
                self.assertEqual(compact_head, original_head)
                self.assertEqual(compact_body, brief_body)
                self.assertEqual(
                    compact_body,
                    original_body.replace("/api/documents", "/api/notes")
                    .replace("documents:list", "notes:list")
                    .replace("documents:read", "notes:read"),
                )
                self.assertIn(
                    f"../catalog/package/snapshot/docs/ai-briefs/{stack}.md", brief_head
                )
                self.assertNotIn("/api/documents", brief_body)
                self.assertIn("/api/notes", brief_body)
                self.assertIn("notes:list", brief_body)
                self.assertIn("notes:read", brief_body)
                self.assertIn('"profile":"browser-session-v1"', brief_body)

    def test_path_mapping_respects_prefix_boundaries_auth_and_query_values(self):
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
            ("/auth/me", "/auth/me"),
            ("/auth/logout", "/auth/logout"),
            ("/api/profile", "/api/profile"),
            ("/api/notes", "/api/notes"),
        ):
            with self.subTest(path=original):
                self.assertEqual(transfer.notes_path(original), expected)

    def test_private_adapter_changes_only_path_and_restores_request_after_success(self):
        body, headers = {"email": "unchanged"}, {"X-Role": "unchanged"}
        checks = ["unchanged-http-check"]

        def grader(port, origin, deadline, membership):
            self.assertEqual(membership, Path("membership.json"))
            auth_eval.request(port, "POST", "/auth/login", origin, deadline, body=body)
            auth_eval.request(
                port,
                "GET",
                "/api/documents?limit=1",
                origin,
                deadline,
                cookie="unchanged-cookie",
                csrf="unchanged-csrf",
                extra_headers=headers,
            )
            auth_eval.request(port, "GET", "/api/documents2", origin, deadline)
            return checks

        with (
            patch.object(auth_eval, "request") as request,
            patch.object(core_eval, "core_http_grade", side_effect=grader),
        ):
            self.assertIs(
                transfer.notes_http_grade(1, "origin", 2, Path("membership.json")),
                checks,
            )
            self.assertIs(auth_eval.request, request)
            self.assertEqual(
                request.call_args_list,
                [
                    call(1, "POST", "/auth/login", "origin", 2, body=body),
                    call(
                        1,
                        "GET",
                        "/api/notes?limit=1",
                        "origin",
                        2,
                        cookie="unchanged-cookie",
                        csrf="unchanged-csrf",
                        extra_headers=headers,
                    ),
                    call(1, "GET", "/api/documents2", "origin", 2),
                ],
            )

    def test_private_adapter_restores_request_when_grading_raises(self):
        with (
            patch.object(auth_eval, "request") as request,
            patch.object(
                core_eval,
                "core_http_grade",
                side_effect=auth_eval.EvalError("fixture-failure"),
            ),
        ):
            with self.assertRaisesRegex(auth_eval.EvalError, "fixture-failure"):
                transfer.notes_http_grade(1, "origin", 2, Path("membership.json"))
            self.assertIs(auth_eval.request, request)

    def test_contract_keeps_auth_core_checks_but_uses_notes_profile_and_adapter(self):
        contract = transfer.contract_factory()
        self.assertEqual(contract.profile, "notes-auth-rbac-offset-v1")
        self.assertIs(contract.prompt_builder, transfer.prompt)
        self.assertIs(contract.artifact_checker, core_eval.core_reuse_check)
        self.assertIs(contract.prepare_grader, core_eval.create_membership_file)
        self.assertEqual(set(contract.ignored_parts), core_eval.CORE_CACHE_PARTS)
        with patch.object(
            transfer, "notes_http_grade", return_value=["fixture"]
        ) as grader:
            result = contract.http_grader(
                Path("generated"),
                {"CORE_MEMBERSHIP_FILE": "membership.json"},
                1,
                "origin",
                2,
            )
            self.assertEqual(result, ["fixture"])
            grader.assert_called_once_with(1, "origin", 2, Path("membership.json"))

    def test_protocol_descriptor_is_hashable_scoped_and_thin_main_only_delegates(self):
        experiment = transfer.EXPERIMENT
        self.assertEqual(
            set(experiment),
            {
                "id",
                "conditions",
                "prompt",
                "contract_factory",
                "source_file",
                "default_repeats",
                "limits",
                "source_validator",
            },
        )
        self.assertEqual(experiment["conditions"], ("catalog_compact", "brief"))
        self.assertEqual(experiment["default_repeats"], 1)
        self.assertEqual(len(auth_eval.STACKS) * len(experiment["conditions"]), 8)
        self.assertEqual(
            Path(experiment["source_file"]).resolve(), Path(transfer.__file__).resolve()
        )
        self.assertEqual(
            len(
                hashlib.sha256(Path(experiment["source_file"]).read_bytes()).hexdigest()
            ),
            64,
        )
        scope = " ".join(experiment["limits"]).lower()
        for required in (
            "notes",
            "similar",
            "not randomized",
            "24",
            "one observation",
            "generalization",
        ):
            self.assertIn(required, scope)
        with patch.object(reading, "main", return_value=7) as main:
            self.assertEqual(transfer.main(), 7)
            main.assert_called_once_with(experiment=experiment)

    def test_brief_preflight_requires_identical_packaged_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = "docs/ai-briefs/python.md"
            original = root / relative
            packaged = root / "catalog/package/snapshot" / relative
            for path in (original, packaged):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Python brief\n")
            metadata = {"catalog_version": "0.4.0"}
            transfer.source_validator(root, metadata, ("python",))
            for data in (b"", b"different", b"\xff"):
                packaged.write_bytes(data)
                with self.assertRaisesRegex(
                    auth_eval.EvalError, "transfer-brief-source-mismatch"
                ):
                    transfer.source_validator(root, metadata, ("python",))
            packaged.unlink()
            packaged.symlink_to(original)
            with self.assertRaises(auth_eval.EvalError):
                transfer.source_validator(root, metadata, ("python",))
            with self.assertRaises(auth_eval.EvalError):
                transfer.source_validator(
                    root, {"catalog_version": "0.3.2"}, ("python",)
                )

    def test_unsupported_conditions_or_stacks_do_not_select_an_arbitrary_brief(self):
        for stack, condition in (("python", "manual"), ("../../private", "brief")):
            with (
                self.subTest(stack=stack, condition=condition),
                self.assertRaises(auth_eval.EvalError),
            ):
                transfer.prompt(stack, self.commit, self.tasks, condition)


if __name__ == "__main__":
    unittest.main()
