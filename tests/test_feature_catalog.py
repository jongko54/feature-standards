"""Reject stale cross-feature guidance before a coding agent follows it."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from feature_catalog import (
    checked_path,
    load_catalog,
    load_index,
    select,
    validate_catalog,
    validate_index,
)


class FeatureCatalogTests(unittest.TestCase):
    def test_publication_requires_matching_public_download_and_consumer_receipt(self):
        from feature_catalog import _publication

        stack = copy.deepcopy(load_catalog("authorization", ROOT)["stacks"][0])
        stack["package"]["published"] = True
        entry = {
            "name": stack["package"]["name"],
            "version": "0.1.0",
            "sourceCommit": "a" * 40,
            "artifactSha256": "b" * 64,
            "metadataUrl": "https://pypi.org/pypi/feature-standards-core/0.1.0/json",
            "registryVerified": True,
            "publicDownloadVerified": True,
            "freshConsumerVerified": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            receipt = root / "docs/core-release-0.1.0.json"
            with self.assertRaises(ValueError):
                _publication(root, stack)
            receipt.write_text(json.dumps({"targets": {"python": entry}}))
            _publication(root, stack)
            for field in (
                "registryVerified",
                "publicDownloadVerified",
                "freshConsumerVerified",
                "name",
                "version",
                "artifactSha256",
            ):
                broken = {
                    **entry,
                    field: False if field.endswith("Verified") else "wrong",
                }
                receipt.write_text(json.dumps({"targets": {"python": broken}}))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    _publication(root, stack)

    def setUp(self):
        self.index = load_index(ROOT)

    def test_current_index_and_all_25_contexts_bind_to_real_source(self):
        validate_index(self.index, ROOT)
        count = 0
        for feature in self.index["features"]:
            catalog = load_catalog(feature["id"], ROOT)
            for stack in catalog["stacks"]:
                for profile in stack["profiles"]:
                    result = select(catalog, stack["id"], profile)
                    self.assertEqual(result["feature"], feature["id"])
                    self.assertEqual(result["stack"]["id"], stack["id"])
                    json.dumps(result)
                    count += 1
        self.assertEqual(count, 25)

    def test_duplicate_or_unknown_feature_cannot_mask_an_existing_feature(self):
        for identifier in ("auth", "invented"):
            broken = copy.deepcopy(self.index)
            broken["features"][1]["id"] = identifier
            with self.assertRaisesRegex(ValueError, "feature"):
                validate_index(broken, ROOT)

    def test_index_rejects_wrong_default_or_escaping_catalog(self):
        for key, value in (
            ("default_profile", "browser-session-v1"),
            ("catalog", "../outside.json"),
        ):
            broken = copy.deepcopy(self.index)
            broken["features"][1][key] = value
            with self.assertRaises(ValueError):
                validate_index(broken, ROOT)

    def test_core_catalog_rejects_profile_drift_or_fake_publication(self):
        for feature in ("authorization", "listing"):
            catalog = load_catalog(feature, ROOT)
            for mutation in ("profile", "published", "unknown"):
                with self.subTest(feature=feature, mutation=mutation):
                    broken = copy.deepcopy(catalog)
                    if mutation == "profile":
                        broken["profiles"][0]["openapi"] = "features/auth/openapi.json"
                    elif mutation == "published":
                        current = broken["stacks"][0]["package"]["published"]
                        broken["stacks"][0]["package"]["published"] = not current
                    else:
                        broken["invented_capability"] = True
                    with self.assertRaises(ValueError):
                        validate_catalog(broken, ROOT)

    def test_core_catalog_rejects_missing_symbols_and_wrong_coordinates(self):
        for feature in ("authorization", "listing"):
            catalog = load_catalog(feature, ROOT)
            for index, stack in enumerate(catalog["stacks"]):
                for field in ("symbol", "package"):
                    with self.subTest(feature=feature, stack=stack["id"], field=field):
                        broken = copy.deepcopy(catalog)
                        if field == "symbol":
                            broken["stacks"][index]["entrypoints"][0]["symbol"] = (
                                "DOES_NOT_EXIST"
                            )
                        else:
                            broken["stacks"][index]["package"]["name"] = (
                                "DOES_NOT_EXIST"
                            )
                        with self.assertRaisesRegex(ValueError, field):
                            validate_catalog(broken, ROOT)

    def test_core_catalog_rejects_nonexistent_command_or_path_escape(self):
        for feature in ("authorization", "listing"):
            catalog = load_catalog(feature, ROOT)
            for mutation in ("command", "path"):
                broken = copy.deepcopy(catalog)
                if mutation == "command":
                    broken["profiles"][0]["checks"] = [
                        {"cwd": ".", "argv": ["python3", "missing.py"]}
                    ]
                else:
                    broken["stacks"][0]["root"] = "../outside"
                with self.assertRaises(ValueError):
                    validate_catalog(broken, ROOT)

    def test_core_browser_role_is_advisory_client(self):
        for feature in ("authorization", "listing"):
            catalog = load_catalog(feature, ROOT)
            stack = next(stack for stack in catalog["stacks"] if stack["id"] == "react")
            self.assertEqual(stack["role"], "client")
            broken = copy.deepcopy(catalog)
            next(stack for stack in broken["stacks"] if stack["id"] == "react")[
                "role"
            ] = "backend"
            with self.assertRaisesRegex(ValueError, "role"):
                validate_catalog(broken, ROOT)

    def test_unknown_feature_stack_and_profile_have_no_fallback(self):
        with self.assertRaisesRegex(ValueError, "feature"):
            load_catalog("../secrets", ROOT)
        for feature in ("authorization", "listing"):
            catalog = load_catalog(feature, ROOT)
            for stack, profile in (
                ("unknown", catalog["profiles"][0]["id"]),
                ("python", "browser-session-v1"),
            ):
                with self.assertRaises(ValueError):
                    select(catalog, stack, profile)

    def test_paths_reject_links_even_when_the_target_is_inside_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").mkdir()
            (root / "source" / "api.py").write_text("public = True\n")
            (root / "linked").symlink_to(root / "source", target_is_directory=True)
            self.assertTrue(checked_path(root, "source/api.py").is_file())
            for path in ("linked/api.py", "../outside.py", str(root / "source/api.py")):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    checked_path(root, path)


if __name__ == "__main__":
    unittest.main()
