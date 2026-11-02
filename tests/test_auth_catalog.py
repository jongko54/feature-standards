"""Catalog failures must be detected before an agent follows stale instructions."""

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from auth_catalog import _package, load_catalog, select, validate_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT)

    def test_current_catalog_binds_to_real_source_and_package_metadata(self):
        validate_catalog(self.catalog, ROOT)

    def test_all_backends_offer_the_three_profiles(self):
        for stack in ("python", "go", "java", "rust"):
            plan = select(self.catalog, stack, "browser-session-v3")
            self.assertEqual(plan["stack"]["id"], stack)
            self.assertIn("features/auth/openapi-v3.json", plan["read"])
            self.assertNotIn("features/auth/mail-delivery-v1.md", plan["read"])

    def test_rejects_unknown_selection(self):
        with self.assertRaises(ValueError):
            select(self.catalog, "ruby", "browser-session-v1")

    def test_rejects_path_escape(self):
        broken = copy.deepcopy(self.catalog)
        broken["stacks"][0]["root"] = "../outside"
        with self.assertRaises(ValueError):
            validate_catalog(broken, ROOT)

    def test_rejects_missing_entrypoint(self):
        broken = copy.deepcopy(self.catalog)
        broken["stacks"][0]["entrypoints"][0]["path"] = "missing.py"
        with self.assertRaises(ValueError):
            validate_catalog(broken, ROOT)

    def test_rejects_openapi_profile_mismatch(self):
        broken = copy.deepcopy(self.catalog)
        broken["profiles"][0]["openapi"] = "features/auth/openapi-v3.json"
        with self.assertRaises(ValueError):
            validate_catalog(broken, ROOT)

    def test_schema_rejects_unsupported_fields(self):
        broken = copy.deepcopy(self.catalog)
        broken["invented_capability"] = True
        with self.assertRaises(ValueError):
            validate_catalog(broken, ROOT)

    def test_output_is_serializable(self):
        json.dumps(select(self.catalog, "python", "browser-session-v1"))

    def test_rejects_drift_in_emitted_npm_javascript_or_types(self):
        stack = next(s for s in self.catalog["stacks"] if s["id"] == "react")
        for field, wrong in (
            ("import", "./lib/missing.js"),
            ("types", "./lib/missing.d.ts"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = root / stack["root"]
                (directory / "src").mkdir(parents=True)
                for relative in ("package.json", "tsconfig.lib.json", "src/api.ts"):
                    shutil.copy2(ROOT / stack["root"] / relative, directory / relative)
                metadata = json.loads((directory / "package.json").read_text())
                metadata["exports"]["./api"][field] = wrong
                (directory / "package.json").write_text(json.dumps(metadata))
                with self.assertRaisesRegex(ValueError, "npm API export"):
                    _package(root, stack)

    def test_rejects_account_profile_using_memory_storage(self):
        broken = copy.deepcopy(self.catalog)
        broken["profiles"][2]["environment"]["AUTH_STORE"] = "memory"
        with self.assertRaisesRegex(ValueError, "environment"):
            validate_catalog(broken, ROOT)

    def test_rejects_account_profile_missing_required_migration(self):
        broken = copy.deepcopy(self.catalog)
        broken["profiles"][2]["migrations"] = []
        with self.assertRaisesRegex(ValueError, "migration"):
            validate_catalog(broken, ROOT)

    def test_rejects_nonexistent_command_script_or_maven_project(self):
        for command in (
            {"cwd": ".", "argv": ["python3", "tests/DOES_NOT_EXIST.py"]},
            {
                "cwd": ".",
                "argv": [
                    "implementations/java-spring/mvnw",
                    "-f",
                    "missing/pom.xml",
                    "test",
                ],
            },
        ):
            with self.subTest(command=command):
                broken = copy.deepcopy(self.catalog)
                broken["profiles"][0]["checks"] = [command]
                with self.assertRaisesRegex(ValueError, "command"):
                    validate_catalog(broken, ROOT)

    def test_rejects_nonexistent_public_entrypoint_symbols_for_each_stack(self):
        for stack in self.catalog["stacks"]:
            with self.subTest(stack=stack["id"]):
                broken = copy.deepcopy(self.catalog)
                target = next(s for s in broken["stacks"] if s["id"] == stack["id"])
                target["entrypoints"][0]["symbol"] = "DOES_NOT_EXIST"
                with self.assertRaisesRegex(ValueError, "symbol"):
                    validate_catalog(broken, ROOT)

    def test_rejects_unknown_mail_addon_profile(self):
        broken = copy.deepcopy(self.catalog)
        broken["addons"][0]["requires_profile"] = "DOES_NOT_EXIST"
        with self.assertRaisesRegex(ValueError, "addon.*profile"):
            validate_catalog(broken, ROOT)

    def test_rejects_private_symbols_even_when_they_exist_in_source(self):
        for stack_id, symbol in (
            ("go", "normalizeEmail"),
            ("rust", "service_with_clock"),
            ("react", "isSession"),
        ):
            with self.subTest(stack=stack_id):
                broken = copy.deepcopy(self.catalog)
                target = next(s for s in broken["stacks"] if s["id"] == stack_id)
                target["entrypoints"][0]["symbol"] = symbol
                with self.assertRaisesRegex(ValueError, "symbol"):
                    validate_catalog(broken, ROOT)

    def test_rejects_wrong_package_coordinates_for_each_stack(self):
        for stack in self.catalog["stacks"]:
            with self.subTest(stack=stack["id"]):
                broken = copy.deepcopy(self.catalog)
                target = next(s for s in broken["stacks"] if s["id"] == stack["id"])
                target["package"]["name"] = "DOES_NOT_EXIST"
                with self.assertRaisesRegex(ValueError, "package"):
                    validate_catalog(broken, ROOT)


if __name__ == "__main__":
    unittest.main()
