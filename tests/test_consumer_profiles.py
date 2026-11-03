"""Focused safety checks for the independent consumer database harness."""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
SPEC = importlib.util.spec_from_file_location(
    "consumer_profiles", ROOT / "tests/consumer_profiles.py"
)
profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiles)


class ConsumerProfileSafety(unittest.TestCase):
    def test_database_name_is_unique_and_test_only(self):
        first = profiles.database_name("go", "browser-session-v3")
        second = profiles.database_name("go", "browser-session-v3")
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^feature_standards_test_consumer_go_v3_[a-f0-9]{12}$")

    def test_invalid_backend_or_profile_is_rejected(self):
        for backend, profile in [("../go", "browser-session-v2"), ("go", "memory")]:
            with self.assertRaises(ValueError):
                profiles.database_name(backend, profile)

    def test_fixture_uri_is_revalidated_before_derivation(self):
        for unsafe in [
            "postgresql://user@remote.example:5432/feature_standards_test",
            "postgresql://user@127.0.0.1:5432/production",
            "postgresql://user@127.0.0.1:5432/feature_standards_test?options=bad",
        ]:
            with self.assertRaises(ValueError):
                profiles.consumer_database_url(unsafe, "go", "browser-session-v2")

    def test_derived_uri_preserves_only_validated_routing(self):
        url = profiles.consumer_database_url(
            "postgresql://feature_test@127.0.0.1:5544/feature_standards_test?sslmode=disable",
            "rust",
            "browser-session-v3",
        )
        self.assertTrue(
            url.startswith(
                "postgresql://feature_test@127.0.0.1:5544/feature_standards_test_consumer_rust_v3_"
            )
        )
        self.assertTrue(url.endswith("?sslmode=disable"))

    def test_existing_database_is_never_reset(self):
        base = "postgresql://feature_test@127.0.0.1:5544/feature_standards_test"
        connection = MagicMock()
        with (
            patch.object(profiles.psycopg, "connect", return_value=connection),
            patch.object(profiles, "migrate") as migrate,
            patch.object(profiles, "seed_demo") as seed,
            profiles.isolated_database(base, "go", "browser-session-v2") as url,
        ):
            self.assertNotEqual(base, url)
            migrate.assert_called_once_with(url)
            seed.assert_called_once_with(url)
        statements = [
            call.args[0].as_string()
            for call in connection.__enter__().execute.call_args_list
        ]
        self.assertEqual(len(statements), 2)
        self.assertTrue(
            statements[0].startswith(
                'CREATE DATABASE "feature_standards_test_consumer_go_v2_'
            )
        )
        self.assertTrue(
            statements[1].startswith(
                'DROP DATABASE "feature_standards_test_consumer_go_v2_'
            )
        )
        self.assertTrue(statements[1].endswith('" WITH (FORCE)'))

    def test_migration_failure_removes_only_new_database(self):
        base = "postgresql://feature_test@127.0.0.1:5544/feature_standards_test"
        connection = MagicMock()
        with (
            patch.object(profiles.psycopg, "connect", return_value=connection),
            patch.object(
                profiles, "migrate_accounts", side_effect=RuntimeError("fixture")
            ),
            self.assertRaisesRegex(RuntimeError, "fixture"),
            profiles.isolated_database(base, "rust", "browser-session-v3"),
        ):
            self.fail("Migration failure must prevent startup")
        statements = [
            call.args[0].as_string()
            for call in connection.__enter__().execute.call_args_list
        ]
        self.assertEqual(len(statements), 2)
        created = statements[0].removeprefix("CREATE DATABASE ")
        self.assertEqual(statements[1], "DROP DATABASE " + created + " WITH (FORCE)")

    def test_failed_creation_never_drops_any_database(self):
        base = "postgresql://feature_test@127.0.0.1:5544/feature_standards_test"
        connection = MagicMock()
        connection.__enter__().execute.side_effect = profiles.psycopg.OperationalError(
            "fixture"
        )
        with (
            patch.object(profiles.psycopg, "connect", return_value=connection),
            self.assertRaises(profiles.psycopg.OperationalError),
            profiles.isolated_database(base, "java", "browser-session-v2"),
        ):
            self.fail("Database creation failure must prevent startup")
        self.assertEqual(connection.__enter__().execute.call_count, 1)

    def test_browser_failure_output_redacts_capabilities(self):
        capability = "x" * 43
        result = SimpleNamespace(
            returncode=1, stdout="Cookie: fs_session=" + capability
        )
        output = io.StringIO()
        with (
            patch.object(profiles.subprocess, "run", return_value=result),
            redirect_stdout(output),
            self.assertRaisesRegex(RuntimeError, "Consumer browser scenarios"),
        ):
            profiles.run_browser({})
        self.assertNotIn(capability, output.getvalue())
        self.assertIn("[REDACTED_CAPABILITY]", output.getvalue())


if __name__ == "__main__":
    unittest.main()
