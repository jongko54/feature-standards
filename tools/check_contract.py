"""Validate the OpenAPI document and its connection to conformance tests."""

import importlib.util
import json
import unittest
from pathlib import Path

from openapi_spec_validator import validate

root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "features/auth/openapi.json").read_text())
validate(spec)
assert spec["info"]["version"] == "0.1.0"
assert set(spec["paths"]) == {"/auth/login", "/auth/me", "/auth/logout", "/healthz"}
assert spec["components"]["securitySchemes"]["sessionCookie"]["name"] == "fs_session"
module_spec = importlib.util.spec_from_file_location(
    "conformance", root / "tests/conformance.py"
)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
tests = unittest.defaultTestLoader.getTestCaseNames(module.AuthContract)
manifest = json.loads((root / "features/auth/scenarios.json").read_text())
assert manifest["profile"] == "browser-session-v1"
assert set(tests) == {row["test"] for row in manifest["scenarios"]}, (
    "Scenario manifest drift"
)
print(f"OpenAPI 3.1 valid; {len(tests)} conformance scenarios mapped.")
