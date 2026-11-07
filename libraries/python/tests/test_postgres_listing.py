"""Public-boundary checks do not require the optional database driver."""

import dataclasses
import os
import subprocess
import sys
import unittest
from pathlib import Path

from feature_standards.listing import ListingError, ListingSchema
from feature_standards.postgres_listing import PostgresListing, VisibilityScope

SCHEMA = ListingSchema(
    {"id": "string", "name": "string", "score": "integer"}, {"score": "integer"}
)


def adapter(**changes):
    settings = {
        "schema": SCHEMA,
        "table": ("public", "documents"),
        "columns": {"id": "id", "name": "name", "score": "score"},
        "tenant_column": "tenant_id",
        "owner_column": "owner_id",
    }
    settings.update(changes)
    return PostgresListing(**settings)


class PostgresListingBoundaryTests(unittest.TestCase):
    def test_visibility_requires_explicit_valid_tenant_and_owner_choice(self):
        with self.assertRaises(TypeError):
            VisibilityScope("tenant-a")
        for tenant, owner in (
            (None, None),
            ("", None),
            ("tenant a", None),
            ("t", ""),
            ("t", "x' OR true--"),
            ("t", False),
        ):
            with (
                self.subTest(tenant=tenant, owner=owner),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_SCOPE$"),
            ):
                VisibilityScope(tenant, owner)
        self.assertIsNone(VisibilityScope("tenant-a", None).owner_id)
        self.assertEqual(VisibilityScope("tenant-a", "user-1").owner_id, "user-1")

    def test_only_explicit_relation_and_typed_projection_are_accepted(self):
        for changes in (
            {"table": "public.documents"},
            {"table": ("public", "documents; DROP TABLE users")},
            {"table": ("public", "documents", "extra")},
            {"columns": {"id": "id", "name": "name"}},
            {
                "columns": {
                    "id": "id",
                    "name": "name",
                    "score": "score",
                    "secret": "secret",
                }
            },
            {"columns": {"id": "id", "name": "name", "score": "score desc"}},
            {"tenant_column": "tenant_id OR true"},
            {"owner_column": None},
            {"schema": {}},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_SCHEMA$"),
            ):
                adapter(**changes)

    def test_configuration_is_an_immutable_copy(self):
        columns = {"id": "id", "name": "name", "score": "score"}
        value = adapter(columns=columns)
        columns["name"] = "secret"
        self.assertEqual(value.columns["name"], "name")
        with self.assertRaises(TypeError):
            value.columns["name"] = "secret"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.table = ("public", "secret")

    def test_bad_query_is_rejected_before_connection_or_driver_use(self):
        value = adapter()
        for raw in (
            "limit=0",
            "sort=score;DROP TABLE users",
            "filter.score=01",
            "offset=10001",
            "limit=1&%6cimit=2",
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"),
            ):
                value.page(object(), raw, VisibilityScope("tenant-a", "user-1"))

    def test_absent_or_forged_scope_fails_before_database_use(self):
        value = adapter()
        for scope in (None, {}, {"tenant_id": "tenant-a", "owner_id": None}):
            with (
                self.subTest(scope=scope),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_SCOPE$"),
            ):
                value.page(object(), "", scope)

    def test_import_and_configuration_do_not_import_the_optional_driver(self):
        script = """
import sys
class NoPsycopg:
    def find_spec(self, name, path=None, target=None):
        if name == 'psycopg' or name.startswith('psycopg.'):
            raise AssertionError('optional driver imported eagerly')
sys.meta_path.insert(0, NoPsycopg())
from feature_standards.listing import ListingSchema
from feature_standards.postgres_listing import PostgresListing, VisibilityScope
PostgresListing(schema=ListingSchema({'id':'string'},{}), table=('public','documents'), columns={'id':'id'}, tenant_column='tenant_id', owner_column='owner_id')
VisibilityScope('tenant-a',None)
"""
        library = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(library)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
