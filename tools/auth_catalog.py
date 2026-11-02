"""Validate and select auth integration metadata; never execute catalog commands."""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = {"python", "go", "java", "rust"}
PROFILE_SETTINGS = {
    "browser-session-v1": ("memory", "false", []),
    "browser-session-v2": (
        "postgres",
        "false",
        ["features/auth/postgres/001_initial.sql"],
    ),
    "browser-session-v3": (
        "postgres",
        "true",
        [
            "features/auth/postgres/001_initial.sql",
            "features/auth/postgres/002_accounts.sql",
        ],
    ),
}


def checked_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.exists():
        raise ValueError(f"Missing or escaping catalog path: {relative}")
    return path


def validate_catalog(catalog: dict, root: Path = ROOT) -> None:
    schema = json.loads((root / "features/auth/catalog.schema.json").read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(catalog), key=lambda e: str(e.path)
    )
    if errors:
        raise ValueError(f"Catalog schema: {errors[0].json_path}: {errors[0].message}")
    profiles = {profile["id"] for profile in catalog["profiles"]}
    if (
        profiles != {f"browser-session-v{i}" for i in (1, 2, 3)}
        or len(catalog["profiles"]) != 3
    ):
        raise ValueError(
            "Catalog must describe each supported auth profile exactly once"
        )
    for profile in catalog["profiles"]:
        store, accounts, migrations = PROFILE_SETTINGS[profile["id"]]
        if profile["environment"] != {
            "AUTH_STORE": store,
            "AUTH_ACCOUNT_LIFECYCLE": accounts,
        }:
            raise ValueError(f"Catalog profile environment mismatch: {profile['id']}")
        if profile["migrations"] != migrations:
            raise ValueError(f"Catalog profile migration mismatch: {profile['id']}")
        for key in ("specification", "openapi", "scenarios", "guide"):
            checked_path(root, profile[key])
        for migration in profile["migrations"]:
            checked_path(root, migration)
        api = json.loads((root / profile["openapi"]).read_text())
        actual = api["paths"]["/healthz"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["properties"]["profile"]["const"]
        if actual != profile["id"]:
            raise ValueError(f"Catalog/OpenAPI profile mismatch: {profile['id']}")
        scenarios = json.loads((root / profile["scenarios"]).read_text())
        if scenarios["profile"] != profile["id"]:
            raise ValueError(f"Catalog/scenario profile mismatch: {profile['id']}")
        _commands(root, profile["checks"])
    ids = [stack["id"] for stack in catalog["stacks"]]
    if len(ids) != len(set(ids)) or set(ids) != BACKENDS | {"react"}:
        raise ValueError("Catalog stack set is incomplete or duplicated")
    for stack in catalog["stacks"]:
        for key in ("root", "guide", "consumer"):
            checked_path(root, stack[key])
        for entrypoint in stack["entrypoints"]:
            checked_path(root, entrypoint["path"])
            _symbols(root, stack["id"], entrypoint)
        if set(stack["profiles"]) != profiles:
            raise ValueError(f"Unsupported/missing profile: {stack['id']}")
        _commands(root, stack["install"] + stack["checks"])
        _package(root, stack)
    for addon in catalog["addons"]:
        if addon["requires_profile"] not in profiles or (
            addon["id"] == "mail-delivery-v1"
            and addon["requires_profile"] != "browser-session-v3"
        ):
            raise ValueError(f"Catalog addon profile mismatch: {addon['id']}")
        for key in ("specification", "guide", "scenarios", "entrypoint"):
            checked_path(root, addon[key])


def _commands(root: Path, commands: list[dict]) -> None:
    for command in commands:
        cwd = checked_path(root, command["cwd"])
        if not cwd.is_dir():
            raise ValueError(
                f"Catalog command cwd is not a directory: {command['cwd']}"
            )
        argv = command["argv"]
        # Inspect known local file operands, never resolve a command by running it.
        operands = []
        if "/" in argv[0]:
            operands.append(argv[0])
        for index, arg in enumerate(argv[1:], 1):
            if arg in {"-f", "--file", "--manifest-path", "--project"}:
                if index + 1 == len(argv):
                    raise ValueError(f"Catalog command flag has no path: {arg}")
                operands.append(argv[index + 1])
            elif arg.endswith((".py", ".toml", ".xml", ".json")):
                operands.append(arg)
        try:
            for operand in operands:
                path = checked_path(root, str((cwd / operand).relative_to(root)))
                if (
                    operand == argv[0]
                    or Path(operand).suffix in {".py", ".toml", ".xml", ".json"}
                ) and not path.is_file():
                    raise ValueError("File operand resolves to a directory")
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"Catalog command file operand is invalid: {operand}"
            ) from exc
        if argv[0] == "npm":
            package = json.loads((cwd / "package.json").read_text())
            script = (
                argv[2]
                if len(argv) > 2 and argv[1] == "run"
                else ("test" if len(argv) > 1 and argv[1] == "test" else None)
            )
            if script is not None and script not in package.get("scripts", {}):
                raise ValueError(
                    f"Catalog command references missing npm script: {script}"
                )


def _package(root: Path, stack: dict) -> None:
    """Bind install coordinates to package declarations, not a second name list."""
    directory = root / stack["root"]
    if stack["id"] == "python":
        data = tomllib.loads((directory / "pyproject.toml").read_text())
        expected = data["project"]["name"]
    elif stack["id"] == "go":
        declaration = re.search(
            r"(?m)^module\s+(\S+)\s*$", (directory / "go.mod").read_text()
        )
        if declaration is None:
            raise ValueError("Catalog package has no Go module declaration")
        relative = (root / stack["entrypoints"][0]["path"]).parent.relative_to(
            directory
        )
        expected = declaration[1] + (
            "/" + relative.as_posix() if str(relative) != "." else ""
        )
    elif stack["id"] == "rust":
        data = tomllib.loads((directory / "Cargo.toml").read_text())
        expected = data["package"]["name"]
    elif stack["id"] == "java":
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        pom = ET.parse(directory / "pom.xml").getroot()
        classifiers = [
            node.text
            for plugin in pom.findall("m:build/m:plugins/m:plugin", ns)
            if plugin.findtext("m:artifactId", namespaces=ns) == "maven-jar-plugin"
            for node in plugin.findall(".//m:classifier", ns)
        ]
        if len(classifiers) != 1:
            raise ValueError("Catalog package requires one reusable Maven classifier")
        expected = ":".join(
            [
                pom.findtext("m:groupId", default="", namespaces=ns),
                pom.findtext("m:artifactId", default="", namespaces=ns),
                pom.findtext("m:packaging", default="jar", namespaces=ns),
                classifiers[0],
                pom.findtext("m:version", default="", namespaces=ns),
            ]
        )
    else:
        package = json.loads((directory / "package.json").read_text())
        entrypoint = checked_path(root, stack["entrypoints"][0]["path"])
        # A published library exports emitted JS and declarations, not its TS source.
        compiler = json.loads((directory / "tsconfig.lib.json").read_text())[
            "compilerOptions"
        ]
        source_root = (directory / compiler["rootDir"]).resolve()
        emitted = (
            (directory / compiler["outDir"] / entrypoint.relative_to(source_root))
            .with_suffix(".js")
            .resolve()
        )
        if not emitted.is_relative_to(directory.resolve()) or not compiler.get(
            "declaration"
        ):
            raise ValueError(
                "Catalog npm library requires local JS and declaration output"
            )
        exports = [
            name
            for name, target in package.get("exports", {}).items()
            if isinstance(target, dict)
            and isinstance(target.get("import"), str)
            and isinstance(target.get("types"), str)
            and (directory / target["import"]).resolve() == emitted
            and (directory / target["types"]).resolve() == emitted.with_suffix(".d.ts")
        ]
        if "./api" not in exports:
            raise ValueError("Catalog package requires a matching npm API export")
        expected = package["name"] + "/api"
    if stack["package"]["name"] != expected:
        raise ValueError(f"Catalog package coordinate mismatch: {stack['id']}")


def _symbols(root: Path, stack_id: str, entrypoint: dict) -> None:
    """Check declarations/exports, without claiming compiler-level API validation."""
    source = (root / entrypoint["path"]).read_text()
    symbols = [part.strip() for part in entrypoint["symbol"].split(";")]
    if stack_id == "python":
        module = ast.parse(source)
        exports = set()
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exports.update(ast.literal_eval(node.value))
        imported = {
            alias.asname or alias.name
            for node in module.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        declared = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
    for symbol in symbols:
        valid = False
        name = re.escape(symbol.split(".")[-1])
        if stack_id == "python":
            valid = symbol in exports and symbol in imported | declared
        elif stack_id == "go":
            if symbol and symbol[0].isupper():
                if "." in symbol:
                    receiver, _ = symbol.split(".", 1)
                    valid = (
                        bool(
                            re.search(
                                rf"(?m)^func\s+\(\w+\s+\*?{re.escape(receiver)}\)\s+{name}\s*\(",
                                source,
                            )
                        )
                        and symbol.split(".")[-1][0].isupper()
                    )
                else:
                    valid = bool(re.search(rf"(?m)^(?:func|type)\s+{name}\b", source))
        elif stack_id == "java":
            owner, _, member = symbol.partition(".")
            valid = (
                bool(
                    re.search(
                        rf"public\s+(?:(?:final|abstract)\s+)?(?:class|interface|record)\s+{re.escape(owner)}\b",
                        source,
                    )
                )
                and bool(member)
                and bool(
                    re.search(
                        rf"public\s+(?:static\s+)?[\w<>.?\[\]]+\s+{name}\s*\(",
                        source,
                    )
                )
            )
        elif stack_id == "rust":
            valid = bool(
                re.search(
                    rf"(?m)^pub\s+(?:async\s+)?(?:struct|enum|trait|fn|type)\s+{name}\b",
                    source,
                )
            ) or any(
                re.search(rf"\b{name}\b", exported)
                for exported in re.findall(r"(?ms)^pub use\s+([^;]+);", source)
            )
        elif stack_id == "react":
            valid = bool(
                re.search(
                    rf"(?m)^export\s+(?:async\s+)?(?:function|type|interface|const|class)\s+{name}\b",
                    source,
                )
            )
        if not valid:
            raise ValueError(
                f"Catalog public symbol missing: {entrypoint['path']}: {symbol}"
            )


def load_catalog(root: Path = ROOT) -> dict:
    return json.loads((root / "feature-standards.json").read_text())


def select(catalog: dict, stack_id: str, profile_id: str) -> dict:
    stack = next((item for item in catalog["stacks"] if item["id"] == stack_id), None)
    profile = next(
        (item for item in catalog["profiles"] if item["id"] == profile_id), None
    )
    if stack is None or profile is None or profile_id not in stack["profiles"]:
        raise ValueError("Unknown stack or unsupported profile")
    return {
        "feature": catalog["feature"],
        "profile": profile,
        "stack": stack,
        "read": list(
            dict.fromkeys(
                [
                    profile["specification"],
                    profile["openapi"],
                    profile["guide"],
                    stack["guide"],
                ]
            )
        ),
        "note": "Commands are instructions, not executed. Use disposable fixtures for conformance.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--stack", choices=sorted(BACKENDS | {"react"}))
    parser.add_argument("--profile", default="browser-session-v1")
    args = parser.parse_args()
    try:
        catalog = load_catalog()
        validate_catalog(catalog)
        if args.check:
            print(
                "Auth catalog: PASS (5 stacks, 3 profiles, checked paths and OpenAPI bindings)"
            )
        elif args.stack:
            print(
                json.dumps(
                    select(catalog, args.stack, args.profile),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            parser.error("Provide --check or --stack")
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
