import os
import unittest
from unittest.mock import patch

from pg_support import assert_test_database, database
from psycopg.conninfo import conninfo_to_dict


class DatabaseTargetGuard(unittest.TestCase):
    def test_accepts_explicit_local_test_database(self):
        with patch.dict(os.environ, {}, clear=True):
            assert_test_database(
                "postgresql://test@127.0.0.1:5432/feature_standards_test?sslmode=disable"
            )
            assert_test_database(
                "postgresql://test@[::1]:5432/feature_standards_test_example"
            )

    def test_canonical_uri_matches_driver_target(self):
        with patch.dict(os.environ, {}, clear=True):
            safe = assert_test_database(
                "postgresql://test:p%40ss@localhost:5432/feature_standards_test"
            )
            parsed = conninfo_to_dict(safe)
            self.assertEqual(parsed["host"], "127.0.0.1")
            self.assertEqual(parsed["port"], "5432")
            self.assertEqual(parsed["dbname"], "feature_standards_test")
            self.assertEqual(parsed["password"], "p@ss")
            self.assertEqual(parsed["sslmode"], "disable")

    def test_rejects_url_overrides_before_connecting(self):
        with patch.dict(os.environ, {}, clear=True):
            for query in (
                "host=production.example",
                "dbname=production",
                "hostaddr=198.51.100.1",
                "service=production",
                "sslmode=disable&host=other",
                "sslmode=disable&sslmode=require",
            ):
                with self.subTest(query=query), self.assertRaises(ValueError):
                    assert_test_database(
                        "postgresql://test@127.0.0.1:5432/feature_standards_test?"
                        + query
                    )

    def test_rejects_environment_routing_before_connecting(self):
        for name in (
            "PGHOSTADDR",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOST",
            "PGPORT",
            "PGDATABASE",
            "PGOPTIONS",
            "PGSSLCERT",
        ):
            with (
                patch.dict(os.environ, {name: "unexpected"}, clear=True),
                self.subTest(name=name),
                self.assertRaises(ValueError),
            ):
                assert_test_database(
                    "postgresql://test@127.0.0.1:5432/feature_standards_test"
                )

    def test_rejects_non_test_or_ambiguous_targets(self):
        with patch.dict(os.environ, {}, clear=True):
            for url in (
                "postgresql://test@127.0.0.1:5432/production",
                "postgresql://test@production.example:5432/feature_standards_test",
                "postgresql://test@127.0.0.1/feature_standards_test",
                "postgresql://test@127.0.0.1:5432/feature_standards_test#fragment",
                "postgresql://test@127.0.0.1:5432/feature_standards_test%2Fproduction",
                "postgresql://test@127.0.0.1:5432/feature_standards_test%C3%A9",
            ):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    assert_test_database(url)

    def test_native_fixture_rejects_routing_before_any_subprocess(self):
        with (
            patch.dict(os.environ, {"PGHOSTADDR": "198.51.100.1"}, clear=True),
            patch("pg_support.subprocess.run") as run,
            self.assertRaises(ValueError),
            database(),
        ):
            self.fail("fixture must reject the environment before yielding")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
