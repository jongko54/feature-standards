"""Validate all OpenAPI profiles and exact mappings to checked-in test declarations."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
PATHS = {"/auth/login", "/auth/me", "/auth/logout", "/healthz"}
ACCOUNT_ENDPOINTS = {
    "/auth/register": ("Register", {"email", "password"}),
    "/auth/email-verification/request": ("AccountEmail", {"email"}),
    "/auth/email-verification/confirm": ("AccountToken", {"token"}),
    "/auth/password-reset/request": ("AccountEmail", {"email"}),
    "/auth/password-reset/confirm": ("ResetPassword", {"token", "password"}),
}
SUITE_BINDINGS = {
    "common-http": ("unittest", "tests/conformance.py", "AuthContract", "each-backend"),
    "shared-postgres": (
        "unittest",
        "tests/postgres_conformance.py",
        "SharedPostgresContract",
        "mixed-backends",
    ),
    "restart": (
        "backend-function",
        "tests/postgres_conformance.py",
        "restart_checks",
        "one-per-listed-backend",
    ),
    "browser": ("playwright", "clients/react/tests/auth.spec.ts", None, "each-backend"),
    "consumer": (
        "playwright",
        "examples/consumer-python-react/tests/consumer.spec.ts",
        None,
        "separate-consumer",
    ),
}
V3_BINDINGS = {
    "common-http": ("unittest", "tests/conformance.py", "AuthContract", "each-backend"),
    "account-http": (
        "unittest",
        "tests/account_conformance.py",
        "AccountContract",
        "each-backend",
    ),
    "shared-accounts": (
        "unittest-prefix",
        "tests/account_conformance.py",
        "SharedAccounts",
        "mixed-backends",
    ),
    "account-browser": (
        "playwright",
        "clients/react/account-tests/accounts.spec.ts",
        None,
        "each-backend",
    ),
    "account-sql": (
        "unittest",
        "tests/test_account_store.py",
        "AccountStoreContract",
        "dedicated-database",
    ),
    "rust-tls": (
        "rust-test",
        "implementations/rust-axum/src/postgres_tls_tests.rs",
        None,
        "isolated-tls-fixture",
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    require(spec is not None and spec.loader is not None, f"Cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_profile(spec: dict, *, version: str, profile: str) -> None:
    validate(spec)
    require(spec["info"]["version"] == version, f"{profile}: release version drift")
    expected_paths = (
        PATHS | set(ACCOUNT_ENDPOINTS) if profile == "browser-session-v3" else PATHS
    )
    require(set(spec["paths"]) == expected_paths, f"{profile}: endpoint drift")
    require(
        spec["components"]["securitySchemes"]["sessionCookie"]["name"] == "fs_session",
        f"{profile}: cookie name drift",
    )
    health = spec["paths"]["/healthz"]["get"]["responses"]["200"]
    require(
        health["content"]["application/json"]["schema"]["properties"]["profile"][
            "const"
        ]
        == profile,
        f"{profile}: health profile drift",
    )
    if profile in ("browser-session-v2", "browser-session-v3"):
        user_id = spec["components"]["schemas"]["User"]["properties"]["id"]
        require(
            "const" not in user_id and user_id["type"] == "string",
            "v2 user id must be dynamic",
        )
        codes = spec["components"]["schemas"]["Error"]["properties"]["error"][
            "properties"
        ]["code"]["enum"]
        require("STORAGE_UNAVAILABLE" in codes, "v2 storage error code missing")
        for path, method in (
            ("/auth/login", "post"),
            ("/auth/me", "get"),
            ("/auth/logout", "post"),
            ("/healthz", "get"),
        ):
            require(
                spec["paths"][path][method]["responses"].get("503")
                == {"$ref": "#/components/responses/StorageUnavailable"},
                f"v2 storage response missing: {method} {path}",
            )
    if profile == "browser-session-v3":
        require(spec.get("x-database-schema-version") == 2, "v3 schema version drift")
        require("INVALID_TOKEN" in codes, "v3 token error code missing")
        for path, (schema_name, fields) in ACCOUNT_ENDPOINTS.items():
            operation = spec["paths"][path]["post"]
            require(set(spec["paths"][path]) == {"post"}, f"v3 method drift: {path}")
            require(
                operation["security"] == [], f"v3 must not require a session: {path}"
            )
            require(
                operation["parameters"] == [{"$ref": "#/components/parameters/Origin"}],
                f"v3 origin drift: {path}",
            )
            require(
                operation["requestBody"]["content"]["application/json"]["schema"]
                == {"$ref": f"#/components/schemas/{schema_name}"},
                f"v3 body schema drift: {path}",
            )
            schema = spec["components"]["schemas"][schema_name]
            require(
                schema["additionalProperties"] is False
                and set(schema["required"]) == fields
                and set(schema["properties"]) == fields,
                f"v3 body fields drift: {path}",
            )
            success = "204" if path.endswith("/confirm") else "202"
            responses = operation["responses"]
            require(
                set(responses)
                == {success, "400", "403", "405", "413", "415", "429", "503"},
                f"v3 response drift: {path}",
            )
            require(
                "Set-Cookie" not in responses[success].get("headers", {}),
                f"v3 must not issue a session: {path}",
            )
            require(
                responses["503"]
                == {"$ref": "#/components/responses/StorageUnavailable"},
                f"v3 storage response missing: {path}",
            )
        password = spec["components"]["schemas"]["Register"]["properties"]["password"]
        require(
            password["minLength"] == 15 and password["maxLength"] == 1024,
            "v3 password limits drift",
        )
        token = spec["components"]["schemas"]["AccountToken"]["properties"]["token"]
        require(token["pattern"] == "^[A-Za-z0-9_-]{43}$", "v3 capability format drift")


def testcase_names(module, name: str) -> set[str]:
    case = getattr(module, name)
    require(
        issubclass(case, unittest.TestCase), f"{name} must remain a unittest TestCase"
    )
    return set(unittest.defaultTestLoader.getTestCaseNames(case))


def case_names(suite: dict, field: str = "test") -> set[str]:
    values = [case[field] for case in suite["cases"]]
    require(
        len(values) == len(set(values)), f"{suite['id']}: duplicate {field} mapping"
    )
    return set(values)


def playwright_names(relative: str) -> set[str]:
    source = (ROOT / relative).read_text()
    # These fixtures use static test('title', ...) declarations. Refuse a new declaration
    # form instead of silently omitting a skipped, focused, dynamic, or grouped case.
    unsupported = re.search(
        r"(?m)^\s*test\.(?!(?:beforeEach|beforeAll|afterEach|afterAll)\s*\()[A-Za-z_]\w*",
        source,
    )
    require(
        unsupported is None,
        f"{relative}: extend the manifest parser for this test form",
    )
    titles = re.findall(r"""(?m)^\s*test\(\s*(['"])(.*?)\1\s*,""", source)
    require(
        len(titles) == len(re.findall(r"(?m)^\s*test\(", source)),
        f"{relative}: non-static Playwright title",
    )
    names = [title for _, title in titles]
    require(len(names) == len(set(names)), f"{relative}: duplicate test title")
    return set(names)


def validate_v2_manifest(manifest: dict, common, postgres) -> tuple[int, int]:
    require(manifest["profile"] == "browser-session-v2", "v2 scenario profile drift")
    require(manifest["version"] == "0.2.0", "v2 scenario version drift")
    require(manifest["schema_version"] == 1, "v2 database schema version drift")
    backends = set(common.BACKENDS)
    require(
        set(manifest["backends"]) == backends
        and len(manifest["backends"]) == len(backends),
        "v2 backend mapping drift",
    )
    suites = manifest["suites"]
    expected_suites = {
        "common-http",
        "shared-postgres",
        "restart",
        "browser",
        "consumer",
    }
    require(
        {suite["id"] for suite in suites} == expected_suites
        and len(suites) == len(expected_suites),
        "v2 scenario suite drift",
    )
    all_ids = [case["id"] for suite in suites for case in suite["cases"]]
    require(len(all_ids) == len(set(all_ids)), "v2 scenario IDs must be unique")
    logical = expanded = 0
    for suite in suites:
        binding = SUITE_BINDINGS[suite["id"]]
        require(
            (
                suite["kind"],
                suite["source"],
                suite.get("class", suite.get("function")),
                suite["scope"],
            )
            == binding,
            f"{suite['id']}: source or runner binding drift",
        )
        require((ROOT / suite["source"]).is_file(), f"{suite['id']}: source missing")
        kind = suite["kind"]
        if kind == "unittest":
            module = common if suite["source"] == "tests/conformance.py" else postgres
            require(
                case_names(suite) == testcase_names(module, suite["class"]),
                f"{suite['id']}: actual unittest method set differs from manifest",
            )
        elif kind == "playwright":
            require(
                case_names(suite) == playwright_names(suite["source"]),
                f"{suite['id']}: actual Playwright test set differs from manifest",
            )
        elif kind == "backend-function":
            require(
                callable(getattr(postgres, suite["function"], None)),
                "restart function missing",
            )
            require(
                case_names(suite, "backend") == backends,
                "restart backend mapping drift",
            )
            tree = ast.parse((ROOT / suite["source"]).read_text())
            function = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == suite["function"]
            )
            require(
                any(
                    isinstance(node, ast.For)
                    and isinstance(node.iter, ast.Name)
                    and node.iter.id == "BACKENDS"
                    for node in ast.walk(function)
                ),
                "restart checks no longer iterate the common backend set",
            )
        else:
            raise AssertionError(f"Unknown scenario kind: {kind}")
        multiplier = len(backends) if suite["scope"] == "each-backend" else 1
        logical += len(suite["cases"])
        expanded += len(suite["cases"]) * multiplier
    require(
        {
            (check["source"], check["function"])
            for check in manifest["supporting_checks"]
        }
        == {
            ("tests/conformance.py", name)
            for name in ("run_contract", "run_secure_cookie_check", "run_browser")
        }
        and len(manifest["supporting_checks"]) == 3,
        "v2 supporting check mapping drift",
    )
    for check in manifest["supporting_checks"]:
        module = common if check["source"] == "tests/conformance.py" else postgres
        require(
            callable(getattr(module, check["function"], None)),
            "supporting check missing",
        )
    return logical, expanded


def validate_v3_manifest(
    manifest: dict, common, accounts, sql_tests
) -> tuple[int, int]:
    require(
        manifest["profile"] == "browser-session-v3" and manifest["version"] == "0.3.0",
        "v3 profile/version drift",
    )
    require(manifest["schema_version"] == 2, "v3 manifest schema version drift")
    backends = set(common.BACKENDS)
    require(
        set(manifest["backends"]) == backends
        and len(manifest["backends"]) == len(backends),
        "v3 backend drift",
    )
    suites = manifest["suites"]
    require(
        {suite["id"] for suite in suites} == set(V3_BINDINGS)
        and len(suites) == len(V3_BINDINGS),
        "v3 suite drift",
    )
    ids = [case["id"] for suite in suites for case in suite["cases"]]
    require(len(ids) == len(set(ids)), "v3 scenario IDs must be unique")
    modules = {
        "tests/conformance.py": common,
        "tests/account_conformance.py": accounts,
        "tests/test_account_store.py": sql_tests,
    }
    logical = expanded = 0
    for suite in suites:
        require(
            (suite["kind"], suite["source"], suite.get("class"), suite["scope"])
            == V3_BINDINGS[suite["id"]],
            f"{suite['id']}: source/runner drift",
        )
        actual = case_names(suite)
        if suite["kind"] == "unittest":
            expected = testcase_names(modules[suite["source"]], suite["class"])
        elif suite["kind"] == "unittest-prefix":
            require(suite["prefix"] == "mixed_", "v3 mixed loader prefix drift")
            loader = unittest.TestLoader()
            loader.testMethodPrefix = suite["prefix"]
            expected = set(loader.getTestCaseNames(accounts.SharedAccounts))
            # The mixed suite deliberately excludes inherited HTTP tests.
            require(
                not expected.intersection(testcase_names(accounts, "AccountContract")),
                "v3 mixed suite repeats inherited HTTP tests",
            )
            tree = ast.parse((ROOT / suite["source"]).read_text())
            require(
                any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "startswith"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "mixed_"
                    for node in ast.walk(tree)
                ),
                "v3 mixed runner no longer selects its mapped prefix",
            )
        elif suite["kind"] == "playwright":
            expected = playwright_names(suite["source"])
        else:
            source = (ROOT / suite["source"]).read_text()
            expected = set(
                re.findall(
                    r"#\[tokio::test\]\s*#\[ignore[^\n]*\]\s*async fn (\w+)\(", source
                )
            )
            require(
                expected == {"postgres_tls_certificate_boundaries"},
                "TLS fixture test declaration drift",
            )
            require(
                suite["runner"] == "implementations/rust-axum/tests/postgres_tls.py",
                "TLS runner drift",
            )
            require((ROOT / suite["runner"]).is_file(), "TLS fixture runner missing")
        require(
            actual == expected,
            f"{suite['id']}: actual declarations differ from manifest",
        )
        logical += len(actual)
        expanded += len(actual) * (
            len(backends) if suite["scope"] == "each-backend" else 1
        )
    return logical, expanded


def main() -> int:
    # postgres_conformance imports conformance/pg_support, and both use tools/auth_db.
    for relative in (".", "tests", "tools"):
        path = str(ROOT / relative)
        if path not in sys.path:
            sys.path.insert(0, path)
    common = load_module("conformance", "tests/conformance.py")
    postgres = load_module("postgres_conformance", "tests/postgres_conformance.py")
    accounts = load_module("account_conformance", "tests/account_conformance.py")
    sql_tests = load_module("test_account_store", "tests/test_account_store.py")
    v1 = json.loads((ROOT / "features/auth/openapi.json").read_text())
    v2 = json.loads((ROOT / "features/auth/openapi-v2.json").read_text())
    v3 = json.loads((ROOT / "features/auth/openapi-v3.json").read_text())
    validate_profile(v1, version="0.1.0", profile="browser-session-v1")
    validate_profile(v2, version="0.2.0", profile="browser-session-v2")
    validate_profile(v3, version="0.3.0", profile="browser-session-v3")
    manifest = json.loads((ROOT / "features/auth/scenarios.json").read_text())
    require(manifest["profile"] == "browser-session-v1", "v1 scenario profile drift")
    mapped = [row["test"] for row in manifest["scenarios"]]
    require(
        len(mapped) == len(set(mapped))
        and set(mapped) == testcase_names(common, "AuthContract"),
        "v1 actual unittest method set differs from manifest",
    )
    generator = importlib.import_module("generate_openapi_v2")
    require(
        v2 == generator.build_spec(v1),
        "v2 OpenAPI generator drift; regenerate openapi-v2.json",
    )
    v2_manifest = json.loads((ROOT / "features/auth/scenarios-v2.json").read_text())
    logical, expanded = validate_v2_manifest(v2_manifest, common, postgres)
    common_suite = next(
        suite for suite in v2_manifest["suites"] if suite["id"] == "common-http"
    )
    require(
        case_names(common_suite) == set(mapped), "v2 must reuse every v1 HTTP scenario"
    )
    v3_generator = importlib.import_module("generate_openapi_v3")
    require(
        v3 == v3_generator.build_spec(v2),
        "v3 OpenAPI generator drift; regenerate openapi-v3.json",
    )
    v3_manifest = json.loads((ROOT / "features/auth/scenarios-v3.json").read_text())
    v3_logical, v3_expanded = validate_v3_manifest(
        v3_manifest, common, accounts, sql_tests
    )
    v3_common = next(
        suite for suite in v3_manifest["suites"] if suite["id"] == "common-http"
    )
    require(
        case_names(v3_common) == set(mapped), "v3 must reuse every v1 HTTP scenario"
    )
    print(f"browser-session-v1: OpenAPI 3.1 valid; {len(mapped)} HTTP methods mapped.")
    print(
        f"browser-session-v2: OpenAPI 3.1 valid; {logical} source scenarios mapped "
        f"({expanded} scheduled checks with backend expansion; not execution results)."
    )
    print(
        f"browser-session-v3: OpenAPI 3.1 valid; {v3_logical} source scenarios mapped "
        f"({v3_expanded} scheduled checks with backend expansion; not execution results)."
    )
    print("v2/v3 OpenAPI generator drift checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
