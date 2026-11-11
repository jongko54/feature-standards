import copy
import hashlib
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from security_release import release_report


class SecurityReleaseTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.artifacts = Path(self.work.name)
        (self.artifacts / "sample.tgz").write_bytes(b"reviewed-artifact")
        self.commit = "a" * 40
        self.now = datetime(2026, 11, 11, 12, tzinfo=UTC)
        self.receipt = {
            "kind": "verified-source-workflow-references",
            "status": "passed",
            "sourceCommit": self.commit,
            "repository": "jongko54/feature-standards",
            "verifiedAt": self.now.isoformat(),
            "checks": {
                label: {
                    "runId": i,
                    "workflow": workflow,
                    "createdAt": self.now.isoformat(),
                    "conclusion": "success",
                    "url": f"https://github.com/jongko54/feature-standards/actions/runs/{i}",
                }
                for label, workflow, i in (
                    ("functional", "ci.yml", 10),
                    ("security", "security.yml", 20),
                )
            },
        }

    def test_exact_artifact_bytes_and_workflow_references_are_bound(self):
        result = release_report(self.receipt, self.artifacts, self.commit, now=self.now)
        self.assertEqual(result["artifacts"][0]["bytes"], 17)
        self.assertEqual(
            result["artifacts"][0]["sha256"],
            hashlib.sha256(b"reviewed-artifact").hexdigest(),
        )
        (self.artifacts / "sample.tgz").write_bytes(b"modified-artifact")
        changed = release_report(
            self.receipt, self.artifacts, self.commit, now=self.now
        )
        self.assertNotEqual(
            changed["artifacts"][0]["sha256"], result["artifacts"][0]["sha256"]
        )
        self.assertFalse(result["registryPublished"])
        self.assertFalse(result["signedAttestation"])
        self.assertFalse(result["externalSecurityAudit"])

    def test_wrong_failed_missing_or_expired_source_evidence_is_rejected(self):
        for mutate in (
            lambda r: r.update(sourceCommit="b" * 40),
            lambda r: r.update(status="findings"),
            lambda r: r["checks"].pop("security"),
            lambda r: r.update(verifiedAt="2026-11-10T00:00:00+00:00"),
            lambda r: r["checks"]["security"].update(
                url="https://example.invalid/untrusted"
            ),
        ):
            receipt = copy.deepcopy(self.receipt)
            mutate(receipt)
            with self.assertRaises((ValueError, KeyError)):
                release_report(receipt, self.artifacts, self.commit, now=self.now)

    def test_linked_empty_or_unexpected_artifacts_are_rejected(self):
        link = self.artifacts / "linked.tgz"
        link.symlink_to(self.artifacts / "sample.tgz")
        with self.assertRaises(ValueError):
            release_report(self.receipt, self.artifacts, self.commit, now=self.now)
        link.unlink()
        (self.artifacts / ".env").write_text("synthetic")
        with self.assertRaises(ValueError):
            release_report(self.receipt, self.artifacts, self.commit, now=self.now)
