"""Behavioral checks for observation denominators; no live model calls."""

import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
observation = importlib.import_module("discovery_observation")


def record(identifier="a", stage="unbranded", **changes):
    row = {
        "id": identifier,
        "provider": "example",
        "interface": "cli",
        "requestedModel": "explicit-model",
        "observedModel": None,
        "caseId": "web-features-ko",
        "stage": stage,
        "sessionId": identifier,
        "freshSession": True,
        "startedAt": "2026-11-16T13:00:00Z",
        "outcome": "completed",
        "promptSha256": "",
        "transcriptSha256": "a" * 64,
        "review": {
            "status": "reviewed",
            "mentioned": False,
            "recommended": False,
            "sourceUrls": [],
            "readEvidence": None,
            "integrationEvidence": None,
        },
    }
    row.update(changes)
    return row


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.protocol = observation.load_protocol(ROOT / "evals/discovery/prompts.json")

    def row(self, *args, **kwargs):
        row = record(*args, **kwargs)
        text = self.protocol["cases"][0]["prompts"][row["stage"]]
        import hashlib

        row["promptSha256"] = hashlib.sha256(text.encode()).hexdigest()
        return row

    def test_mention_alone_is_neither_official_recommendation_nor_read_or_execution(
        self,
    ):
        row = self.row()
        row["review"]["mentioned"] = True
        group = observation.summarize([row], self.protocol)["groups"][0]
        self.assertEqual(group["mentions"], 1)
        for metric in ("officialRecommendations", "documentOutputs", "sdkConnections"):
            self.assertEqual(group[metric], 0)

    def test_recommendation_needs_a_real_official_url(self):
        row = self.row()
        row["review"].update(
            mentioned=True,
            recommended=True,
            sourceUrls=[
                "https://github.com/jongko54/feature-standards/blob/main/README.md"
            ],
        )
        group = observation.summarize([row], self.protocol)["groups"][0]
        self.assertEqual(group["officialRecommendations"], 1)
        self.assertEqual(group["documentOutputs"], 0)

    def test_same_conversation_cannot_be_counted_as_independent_trials(self):
        first, second = self.row(), self.row("b", "named", sessionId="a")
        with self.assertRaisesRegex(ValueError, "session"):
            observation.summarize([first, second], self.protocol)

    def test_nonfresh_blocked_and_unreviewed_are_visible_but_not_measured_zero(self):
        rows = [
            self.row("followup", freshSession=False),
            self.row("auth", outcome="blocked", transcriptSha256=None, review=None),
            self.row("pending", review={"status": "pending"}),
        ]
        group = observation.summarize(rows, self.protocol)["groups"][0]
        self.assertEqual(group["attempts"], 3)
        self.assertEqual(group["nonIndependent"], 1)
        self.assertEqual(group["blocked"], 1)
        self.assertEqual(group["pendingReview"], 1)
        self.assertEqual(group["reviewedIndependentCompleted"], 0)
        self.assertIsNone(group["officialRecommendationRate"])

    def test_interfaces_stages_and_models_are_not_pooled(self):
        rows = [
            self.row(),
            self.row("b", "named"),
            self.row("c", interface="web-app"),
            self.row("d", requestedModel="different-model"),
        ]
        self.assertEqual(len(observation.summarize(rows, self.protocol)["groups"]), 4)

    def test_wrong_prompt_hash_and_unknown_fields_are_rejected(self):
        for changes in ({"promptSha256": "b" * 64}, {"unexpected": "value"}):
            row = self.row()
            row.update(changes)
            with self.assertRaises(ValueError):
                observation.summarize([row], self.protocol)

    def test_sdk_connection_requires_integration_stage_and_independent_evidence(self):
        row = self.row(stage="integration")
        row["review"]["integrationEvidence"] = {"httpPassed": True}
        with self.assertRaises(ValueError):
            observation.summarize([row], self.protocol)

    def test_read_evidence_requires_tool_output_hash_and_official_source(self):
        row = self.row(stage="supplied_url")
        row["review"]["readEvidence"] = {
            "sourceUrl": "https://github.com/jongko54/feature-standards",
            "kind": "model-claim",
            "sha256": "a" * 64,
        }
        with self.assertRaises(ValueError):
            observation.summarize([row], self.protocol)

    def test_official_urls_reject_lookalikes_and_credentials(self):
        for url in (
            "https://github.com/jongko54/feature-standards-evil",
            "https://github.com.evil/jongko54/feature-standards",
            "https://token@github.com/jongko54/feature-standards",
            "http://github.com/jongko54/feature-standards",
            "https://github.com/jongko54/feature-standards/%2e%2e/%2e%2e/other/repo",
            "https://github.com/jongko54/feature-standards?token=do-not-retain",
        ):
            self.assertFalse(observation.official_url(url), url)

    def test_valid_reading_and_integration_evidence_stay_separate(self):
        read, app = self.row("read", "supplied_url"), self.row("app", "integration")
        read["review"]["readEvidence"] = {
            "kind": "tool-output",
            "sourceUrl": "https://github.com/jongko54/feature-standards/blob/main/README.md",
            "sha256": "b" * 64,
        }
        app["review"]["integrationEvidence"] = {
            "httpPassed": True,
            "httpReceiptSha256": "c" * 64,
            "originEvidenceSha256": "d" * 64,
            "appSourceSha256": "e" * 64,
        }
        summary = observation.summarize([read, app], self.protocol)
        groups = {g["stage"]: g for g in summary["groups"]}
        self.assertEqual(groups["supplied_url"]["documentOutputs"], 1)
        self.assertEqual(groups["supplied_url"]["sdkConnections"], 0)
        self.assertEqual(groups["integration"]["sdkConnections"], 1)

    def test_noncompleted_reviews_and_completed_missing_transcripts_are_rejected(self):
        for row in (self.row(outcome="blocked"), self.row(transcriptSha256=None)):
            with self.assertRaises(ValueError):
                observation.summarize([row], self.protocol)

    def test_duplicate_record_ids_and_naive_timestamps_are_rejected(self):
        for rows in (
            [self.row(), self.row("a", "named", sessionId="new-session")],
            [self.row(startedAt="2026-11-16T13:00:00")],
        ):
            with self.assertRaises(ValueError):
                observation.summarize(rows, self.protocol)

    def test_unnamed_questions_cannot_contain_brand_or_urls(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["cases"][0]["prompts"]["unbranded"] += " feature-standards"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompts.json"
            path.write_text(json.dumps(protocol))
            with self.assertRaisesRegex(ValueError, "unbranded"):
                observation.load_protocol(path)

    def test_empty_study_has_no_claimed_success_or_zero_adoption_rate(self):
        summary = observation.summarize([], self.protocol)
        self.assertEqual(summary["groups"], [])
        self.assertEqual(summary["records"], 0)
        self.assertEqual(summary["unobservedStages"], self.protocol["stages"])


if __name__ == "__main__":
    unittest.main()
