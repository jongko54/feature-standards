"""Check mail scenario/source linkage and SMTP/SQL error-code drift without importing tests."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = {
    "smtp-settings": ("tests/test_smtp_transport.py", "SMTPConfiguration"),
    "smtp-wire": ("tests/test_smtp_transport.py", "SMTPWire"),
    "worker-settings": ("tests/test_mail_worker.py", "WorkerSettingsTests"),
    "worker-postgres": ("tests/test_mail_worker.py", "MailWorkerPostgresTests"),
    "capture-postgres": (
        "tests/test_mail_capture_delivery.py",
        "CaptureDeliveryContract",
    ),
    "mail-integration": ("tests/mail_conformance.py", "MailDeliveryContract"),
}
TERMINAL_CODES = {"INTERNAL", "EXPIRED", "SUPERSEDED", "DISABLED", "ATTEMPTS_EXHAUSTED"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def tree(relative: str) -> ast.Module:
    return ast.parse((ROOT / relative).read_text())


def literal_assignment(module: ast.Module, name: str):
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
                and len(value.args) == 1
            ):
                value = value.args[0]
            return ast.literal_eval(value)
    raise AssertionError(f"Missing literal declaration: {name}")


def test_names(relative: str, class_name: str) -> set[str]:
    matches = [
        node
        for node in tree(relative).body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    require(len(matches) == 1, f"Missing or duplicate test class: {class_name}")
    declarations = [
        node.name
        for node in matches[0].body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    require(
        len(declarations) == len(set(declarations)),
        f"Duplicate test declaration: {class_name}",
    )
    require(bool(declarations), f"Empty test class: {class_name}")
    return set(declarations)


def validate_manifest(manifest: dict) -> int:
    require(manifest["profile"] == "mail-delivery-v1", "Mail profile drift")
    require(
        manifest["base_schema_version"] == 2
        and manifest["delivery_schema_version"] == 1,
        "Mail schema version drift",
    )
    require(
        manifest["contract"] == "features/auth/mail-delivery-v1.md",
        "Mail contract binding drift",
    )
    require(
        manifest["migration"] == "features/auth/postgres/003_mail_delivery.sql",
        "Mail migration binding drift",
    )
    backends = literal_assignment(tree("tests/conformance.py"), "BACKENDS")
    require(
        set(manifest["backends"]) == set(backends)
        and len(manifest["backends"]) == len(backends),
        "Mail backend mapping drift",
    )
    suites = manifest["suites"]
    require(
        {suite["id"] for suite in suites} == set(BINDINGS)
        and len(suites) == len(BINDINGS),
        "Mail suite mapping drift",
    )
    identifiers = []
    count = 0
    for suite in suites:
        require(
            (suite["source"], suite["class"]) == BINDINGS[suite["id"]],
            f"{suite['id']}: source binding drift",
        )
        actual = test_names(suite["source"], suite["class"])
        declared = [case["test"] for case in suite["cases"]]
        require(
            set(declared) == actual and len(declared) == len(actual),
            f"{suite['id']}: test method mapping drift",
        )
        identifiers.extend(case["id"] for case in suite["cases"])
        count += len(actual)
    require(len(identifiers) == len(set(identifiers)), "Duplicate mail scenario ID")
    integration = tree("tests/mail_conformance.py")
    main = next(
        node
        for node in integration.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    require(
        any(
            isinstance(node, ast.comprehension)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "BACKENDS"
            for node in ast.walk(main)
        ),
        "Integration no longer launches the shared backend set",
    )
    return count


def validate_errors(manifest: dict) -> None:
    transport_codes = literal_assignment(tree("tools/smtp_transport.py"), "ERROR_CODES")
    require(
        isinstance(transport_codes, set)
        and all(isinstance(code, str) for code in transport_codes),
        "SMTP error declaration must remain a literal string set",
    )
    ddl = (ROOT / manifest["migration"]).read_text()
    match = re.search(
        r"last_error_code\s+text\s+CHECK\s*\(\s*last_error_code\s+IN\s*\((.*?)\)\s*\)",
        ddl,
        re.DOTALL | re.IGNORECASE,
    )
    require(match is not None, "SQL allowed error-code constraint missing")
    codes = re.findall(r"'([A-Z0-9_]+)'", match[1])
    require(len(codes) == len(set(codes)), "Duplicate SQL delivery error code")
    require(
        set(manifest["terminal_error_codes"]) == TERMINAL_CODES
        and len(manifest["terminal_error_codes"]) == len(TERMINAL_CODES),
        "Terminal error-code policy drift",
    )
    require(
        set(codes) == transport_codes | TERMINAL_CODES,
        "SMTP and SQL delivery error codes differ",
    )


def main() -> int:
    manifest = json.loads((ROOT / "features/auth/mail-scenarios.json").read_text())
    count = validate_manifest(manifest)
    validate_errors(manifest)
    print(
        f"mail-delivery-v1: {count} declared test scenarios mapped; SMTP/SQL error codes match (not execution results)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
