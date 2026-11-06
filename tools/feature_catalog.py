"""Validate and select source feature catalogs without executing their commands."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import auth_catalog
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
FEATURES = {
    "auth": ("browser-session-v1", "browser-session-v2", "browser-session-v3"),
    "authorization": ("rbac-v1",),
    "listing": ("offset-list-v1",),
}
STACKS = {"python", "go", "java", "rust", "react"}


def checked_path(root: Path, relative: str) -> Path:
    """Resolve only checkout-owned paths, including when an ancestor is a link."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Invalid catalog path")
    if ".." in Path(relative).parts:
        raise ValueError(f"Escaping catalog path: {relative}")
    current = root.resolve()
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Linked catalog path: {relative}")
    if not current.exists() or not current.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Missing or escaping catalog path: {relative}")
    return current


def load_index(root: Path = ROOT) -> dict:
    return json.loads(checked_path(root, "features/catalog.json").read_text())


def _index_shape(index: dict) -> None:
    if (
        not isinstance(index, dict)
        or set(index) != {"schema_version", "features"}
        or type(index["schema_version"]) is not int
        or index["schema_version"] != 1
    ):
        raise ValueError("Unsupported feature index")
    entries = index["features"]
    if not isinstance(entries, list) or len(entries) != len(FEATURES):
        raise ValueError("Incomplete feature index")
    ids = []
    keys = {
        "id",
        "catalog",
        "description",
        "default_profile",
        "integration_skill",
        "integration_guide",
    }
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != keys:
            raise ValueError("Invalid feature descriptor")
        if any(
            not isinstance(value, str) or not value.strip() for value in entry.values()
        ):
            raise ValueError("Invalid feature descriptor value")
        if (
            entry["id"] not in FEATURES
            or entry["default_profile"] != FEATURES[entry["id"]][0]
        ):
            raise ValueError("Invalid feature default profile")
        ids.append(entry["id"])
    if len(set(ids)) != len(ids) or set(ids) != set(FEATURES):
        raise ValueError("Unknown or duplicate feature")


def load_catalog(feature: str = "auth", root: Path = ROOT) -> dict:
    index = load_index(root)
    _index_shape(index)
    entry = next((item for item in index["features"] if item["id"] == feature), None)
    if entry is None:
        raise ValueError("Unknown feature")
    return json.loads(checked_path(root, entry["catalog"]).read_text())


def validate_index(index: dict, root: Path = ROOT) -> None:
    _index_shape(index)
    for descriptor in index["features"]:
        for field in ("catalog", "integration_skill", "integration_guide"):
            if not checked_path(root, descriptor[field]).is_file():
                raise ValueError("Feature descriptor must reference a document")
        catalog = json.loads(checked_path(root, descriptor["catalog"]).read_text())
        if catalog.get("feature") != descriptor["id"]:
            raise ValueError("Feature index/catalog mismatch")
        validate_catalog(catalog, root)


def _shape(catalog: dict, root: Path) -> None:
    schema = copy.deepcopy(
        json.loads((root / "features/auth/catalog.schema.json").read_text())
    )
    schema["properties"]["feature"] = {"enum": list(FEATURES)[1:]}
    # Source coordinates may name their initial version, but are never release receipts.
    package = schema["properties"]["stacks"]["items"]["properties"]["package"]
    package["properties"]["version"] = {"type": "string", "const": "0.1.0"}
    schema["properties"]["stacks"]["items"]["properties"]["install"]["minItems"] = 0
    schema["properties"]["addons"]["minItems"] = 0
    errors = sorted(
        Draft202012Validator(schema).iter_errors(catalog),
        key=lambda error: str(error.path),
    )
    if errors:
        raise ValueError(
            f"Feature catalog schema: {errors[0].json_path}: {errors[0].message}"
        )


def _symbols(root: Path, stack: dict, entrypoint: dict) -> None:
    source = checked_path(root, entrypoint["path"]).read_text()
    symbols = [symbol.strip() for symbol in entrypoint["symbol"].split(";")]
    declared = set()
    if stack["id"] == "python":
        module = ast.parse(source)
        declared = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
        }
        declared.update(
            alias.asname or alias.name
            for node in module.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if not (alias.asname or alias.name).startswith("_")
        )
    for symbol in symbols:
        valid = False
        name = re.escape(symbol.split(".")[-1])
        if stack["id"] == "python":
            valid = symbol in declared
        elif stack["id"] == "go" and symbol and symbol[0].isupper():
            if "." in symbol:
                owner, member = symbol.split(".", 1)
                valid = member[0].isupper() and bool(
                    re.search(
                        rf"(?m)^func\s+\(\w+\s+\*?{re.escape(owner)}\)\s+{name}\s*\(",
                        source,
                    )
                )
            else:
                valid = bool(re.search(rf"(?m)^(?:func|type)\s+{name}\b", source))
        elif stack["id"] == "java":
            owner, _, member = symbol.partition(".")
            valid = bool(
                re.search(
                    rf"public\s+(?:(?:final|abstract|static)\s+)*(?:class|interface|record|enum)\s+{re.escape(owner)}\b",
                    source,
                )
            )
            if member:
                public_type = re.search(
                    rf"public\s+(?:(?:static|final|abstract)\s+)*(?:class|record|interface|enum)\s+{name}\b",
                    source,
                )
                public_method = re.search(
                    rf"public\s+(?:(?:static|final)\s+)*[\w<>.?\[\], ]+\s+{name}\s*\(",
                    source,
                )
                valid = valid and bool(public_type or public_method)
        elif stack["id"] == "rust":
            valid = bool(
                re.search(
                    rf"(?m)^pub\s+(?:async\s+)?(?:struct|enum|trait|fn|type)\s+{name}\b",
                    source,
                )
            )
        elif stack["id"] == "react":
            valid = bool(
                re.search(
                    rf"(?m)^export\s+(?:async\s+)?(?:function|class|const)\s+{name}\b",
                    source,
                )
            )
        if not valid:
            raise ValueError(
                f"Feature catalog public symbol missing: {entrypoint['path']}: {symbol}"
            )


def _package(root: Path, stack: dict) -> None:
    directory = checked_path(root, stack["root"])
    identifier = stack["id"]
    version = None
    if identifier == "python":
        data = tomllib.loads((directory / "pyproject.toml").read_text())["project"]
        expected, version = data["name"], data["version"]
    elif identifier == "go":
        module = re.search(
            r"(?m)^module\s+(\S+)\s*$", (directory / "go.mod").read_text()
        )
        if module is None:
            raise ValueError("Feature catalog package has no Go module declaration")
        expected = module[1]
    elif identifier == "java":
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        pom = ET.parse(directory / "pom.xml").getroot()
        expected = ":".join(
            pom.findtext("m:" + field, default="", namespaces=ns)
            for field in ("groupId", "artifactId", "version")
        )
        version = pom.findtext("m:version", namespaces=ns)
    elif identifier == "rust":
        data = tomllib.loads((directory / "Cargo.toml").read_text())["package"]
        expected, version = data["name"], data["version"]
        if data.get("publish") is not False:
            raise ValueError("Unpublished core Rust package must disable publication")
    else:
        data = json.loads((directory / "package.json").read_text())
        expected, version = data["name"], data["version"]
        if data.get("private") is not True:
            raise ValueError("Unpublished core npm package must be private")
        export = data.get("exports", {}).get(".", {})
        for kind, suffix in (("import", ".mjs"), ("types", ".d.mts")):
            target = export.get(kind)
            if (
                not isinstance(target, str)
                or not target.endswith(suffix)
                or not checked_path(directory, target).is_file()
            ):
                raise ValueError(
                    "Core npm package requires real JavaScript and declaration exports"
                )
    if stack["package"]["name"] != expected or (
        "version" in stack["package"]
        and version is not None
        and stack["package"]["version"] != version
    ):
        raise ValueError(f"Feature catalog package coordinate mismatch: {identifier}")


def validate_catalog(catalog: dict, root: Path = ROOT) -> None:
    if not isinstance(catalog, dict):
        raise TypeError("Feature catalog must be an object")
    if catalog.get("feature") == "auth":
        auth_catalog.validate_catalog(catalog, root)
        return
    _shape(catalog, root)
    feature = catalog["feature"]
    expected_profiles = FEATURES[feature]
    profiles = [profile["id"] for profile in catalog["profiles"]]
    if tuple(profiles) != expected_profiles:
        raise ValueError("Feature catalog profile mismatch")
    ids = [stack["id"] for stack in catalog["stacks"]]
    if len(ids) != len(set(ids)) or set(ids) != STACKS:
        raise ValueError("Feature catalog stack set is incomplete or duplicated")
    if catalog["addons"]:
        raise ValueError("Core feature addons are not supported")
    for profile in catalog["profiles"]:
        if profile["environment"] or profile["migrations"]:
            raise ValueError(
                "Core libraries cannot imply authentication environment or migrations"
            )
        for key in ("specification", "openapi", "scenarios", "guide"):
            if not checked_path(root, profile[key]).is_file():
                raise ValueError("Feature catalog document must be a file")
        api = json.loads(checked_path(root, profile["openapi"]).read_text())
        scenarios = json.loads(checked_path(root, profile["scenarios"]).read_text())
        if (
            api.get("x-feature-standards-profile") != profile["id"]
            or scenarios.get("profile") != profile["id"]
            or scenarios.get("feature") != feature
        ):
            raise ValueError("Feature catalog/OpenAPI/scenario profile mismatch")
        auth_catalog._commands(root, profile["checks"])
    for stack in catalog["stacks"]:
        if stack["profiles"] != list(expected_profiles):
            raise ValueError("Feature catalog stack profile mismatch")
        if stack["role"] != ("client" if stack["id"] == "react" else "backend"):
            raise ValueError("Feature catalog stack role mismatch")
        if stack["package"]["published"] is not False:
            raise ValueError("New core feature package is unpublished")
        if (
            not checked_path(root, stack["root"]).is_dir()
            or not checked_path(root, stack["consumer"]).is_dir()
        ):
            raise ValueError("Feature catalog root/consumer must be directories")
        checked_path(root, stack["guide"])
        checked_path(root, stack["consumer"] + "/README.md")
        for entrypoint in stack["entrypoints"]:
            _symbols(root, stack, entrypoint)
        auth_catalog._commands(root, stack["install"] + stack["checks"])
        _package(root, stack)


def select(catalog: dict, stack_id: str, profile_id: str | None = None) -> dict:
    if profile_id is None:
        profiles = FEATURES.get(catalog.get("feature"))
        if profiles is None:
            raise ValueError("Unknown feature")
        profile_id = profiles[0]
    return auth_catalog.select(catalog, stack_id, profile_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--feature", choices=list(FEATURES), default="auth")
    parser.add_argument("--stack", choices=sorted(STACKS))
    parser.add_argument("--profile")
    args = parser.parse_args()
    try:
        index = load_index()
        validate_index(index)
        if args.check:
            print(
                "Feature catalogs: PASS (3 features, 25 source contexts; no commands executed)"
            )
        elif args.stack:
            print(
                json.dumps(
                    select(load_catalog(args.feature), args.stack, args.profile),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            parser.error("Provide --check or --stack")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
