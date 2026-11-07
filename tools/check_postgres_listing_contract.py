#!/usr/bin/env python3
"""Validate the Python-only database profile and its real executable test map."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from openapi_spec_validator import validate_spec

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "libraries/python/tests/test_postgres_listing.py",
    "tests/postgres_listing_conformance.py",
)


def main():
    api = json.loads((ROOT / "features/listing/openapi-postgres.json").read_text())
    cases = json.loads((ROOT / "features/listing/scenarios-postgres.json").read_text())
    if (
        api.get("x-feature-standards-profile") != "postgres-list-v1"
        or cases.get("profile") != "postgres-list-v1"
        or cases.get("feature") != "listing"
        or cases.get("implemented_stacks") != ["python"]
    ):
        raise ValueError("PostgreSQL listing profile bindings mismatch")
    validate_spec(api)
    actual = set()
    for filename in SOURCES:
        tree = ast.parse((ROOT / filename).read_text())
        for test_class in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            actual.update(
                (filename, test_class.name + "." + method.name)
                for method in test_class.body
                if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")
            )
    entries = cases["cases"]
    declared = {(item["path"], item["test"]) for item in entries}
    if (
        declared != actual
        or len(entries) != len(actual)
        or len({item["id"] for item in entries}) != len(entries)
    ):
        raise ValueError("PostgreSQL listing test map is incomplete or duplicated")
    print(
        f"PostgreSQL listing contract: PASS ({len(entries)} mapped tests; Python source profile only, tests not executed)"
    )


if __name__ == "__main__":
    main()
