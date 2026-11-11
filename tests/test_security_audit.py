"""Security receipts must distinguish coverage, findings and scanner failure."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from security_audit import (
    cyclonedx,
    mapping_check,
    normalize_gitleaks,
    normalize_osv,
    normalize_semgrep,
    overall_status,
    record_setup_failure,
    scan_environment,
)


class SecurityReceiptTests(unittest.TestCase):
    def test_scanners_do_not_inherit_account_or_application_tokens(self):
        env = scan_environment(
            {
                "PATH": "/tools",
                "HOME": "/home/user",
                "LANG": "C.UTF-8",
                "OPENAI_API_KEY": "synthetic",
                "GH_TOKEN": "synthetic",
                "GITHUB_TOKEN": "synthetic",
                "SEMGREP_APP_TOKEN": "synthetic",
                "AUTH_DATABASE_URL": "synthetic",
            }
        )
        self.assertEqual(env["HOME"], "/home/user")
        self.assertEqual(env["SEMGREP_SEND_METRICS"], "off")
        self.assertNotIn("synthetic", env.values())

    def test_mapping_validation_is_not_runtime_or_certification_evidence(self):
        result = mapping_check()
        self.assertFalse(result["runtimeTestsExecuted"])
        self.assertIsNone(result["asvsLevelClaim"])

    def test_setup_failure_receipt_is_unverified_and_existing_evidence_is_preserved(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "evidence"
            record_setup_failure(out)
            path = out / "security-report.json"
            data = json.loads(path.read_text())
            self.assertEqual(data["status"], "error")
            self.assertTrue(
                all(not check["executed"] for check in data["checks"].values())
            )
            before = path.read_bytes()
            record_setup_failure(out)
            self.assertEqual(path.read_bytes(), before)

    def test_empty_or_missing_checks_cannot_pass(self):
        self.assertEqual(overall_status({}), "error")
        self.assertEqual(
            overall_status({"dependencies": {"status": "passed"}}), "error"
        )
        checks = {
            name: {"status": "passed"} for name in ("dependencies", "static", "secrets")
        }
        self.assertEqual(overall_status(checks), "passed")
        checks["static"]["status"] = "error"
        self.assertEqual(overall_status(checks), "error")
        checks["static"]["status"] = "findings"
        self.assertEqual(overall_status(checks), "findings")

    def test_osv_zero_packages_and_non_result_exit_are_errors(self):
        self.assertEqual(normalize_osv({"results": []}, 0)["status"], "error")
        self.assertEqual(normalize_osv({"results": []}, 127)["status"], "error")
        with self.assertRaises(TypeError):
            normalize_osv({"results": "invalid"}, 0)

    def test_osv_packages_and_vulnerabilities_are_preserved(self):
        data = {
            "results": [
                {
                    "source": {"path": "libraries/rust/Cargo.lock", "type": "lockfile"},
                    "packages": [
                        {
                            "package": {
                                "name": "sample",
                                "version": "1.0.0",
                                "ecosystem": "crates.io",
                            },
                            "vulnerabilities": [
                                {"id": "GHSA-example", "aliases": ["CVE-example"]}
                            ],
                        }
                    ],
                }
            ]
        }
        result = normalize_osv(data, 1)
        self.assertEqual(result["status"], "findings")
        self.assertEqual(result["packagesScanned"], 1)
        self.assertEqual(result["findings"][0]["id"], "GHSA-example")
        self.assertEqual(len(cyclonedx(result["inventory"])["components"]), 1)
        self.assertEqual(normalize_osv(data, 127)["status"], "error")

    def test_semgrep_zero_coverage_or_parse_error_cannot_pass(self):
        empty = {"results": [], "errors": [], "paths": {"scanned": []}}
        self.assertEqual(normalize_semgrep(empty, 0)["status"], "error")
        empty["paths"]["scanned"] = ["app.py"]
        self.assertEqual(normalize_semgrep(empty, 0)["status"], "passed")
        self.assertEqual(normalize_semgrep(empty, 1)["status"], "error")
        empty["errors"] = [{"type": "ParseError", "message": "private source line"}]
        result = normalize_semgrep(empty, 0)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("private source line", json.dumps(result))

    def test_secret_output_never_contains_secret_or_source_line(self):
        raw = [
            {
                "RuleID": "generic-api-key",
                "File": "app.py",
                "StartLine": 7,
                "Secret": "sensitive-test-value",
                "Match": "private source line",
                "Commit": "a" * 40,
                "Author": "private@example.invalid",
            }
        ]
        result = normalize_gitleaks(raw, 1)
        self.assertEqual(result["status"], "findings")
        self.assertEqual(result["findings"][0]["line"], 7)
        for private in (
            "sensitive-test-value",
            "private source line",
            "private@example.invalid",
        ):
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual(normalize_gitleaks([], 2)["status"], "error")

    def test_inventory_deduplicates_components_and_keeps_origins(self):
        package = {
            "name": "example",
            "version": "1.2",
            "ecosystem": "PyPI",
            "source": "a/uv.lock",
        }
        bom = cyclonedx([package, {**package, "source": "b/uv.lock"}])
        self.assertEqual(bom["bomFormat"], "CycloneDX")
        self.assertEqual(len(bom["components"]), 1)
        self.assertEqual(bom["components"][0]["purl"], "pkg:pypi/example@1.2")
        scoped = cyclonedx(
            [{**package, "ecosystem": "npm", "name": "@example/package"}]
        )
        self.assertEqual(
            scoped["components"][0]["purl"], "pkg:npm/%40example/package@1.2"
        )


if __name__ == "__main__":
    unittest.main()
