#!/usr/bin/env python3
"""Bind release tags to package metadata before any registry upload."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "npm-core": ("libraries/typescript", "npm-core-v", "npm"),
    "python-core": ("libraries/python", "python-core-v", "python"),
    "java-core": ("libraries/java", "java-core-v", "java"),
    "rust-core": ("libraries/rust", "rust-core-v", "rust"),
    "npm-standards": ("packages/feature-standards", "feature-standards-v", "npm"),
    "npm-react-auth": ("clients/react", "npm-react-auth-v", "npm"),
    "npm-cli": ("packages/create-feature-auth", "npm-create-feature-auth-v", "npm"),
    "python": ("implementations/python-fastapi", "python-auth-v", "python"),
    "java": ("implementations/java-spring", "java-auth-v", "java"),
    "rust": ("implementations/rust-axum", "rust-auth-v", "rust"),
}


def metadata(target: str, tag: str | None = None, root: Path = ROOT) -> dict[str, str]:
    directory, prefix, kind = TARGETS[target]
    location = root / directory
    if kind == "npm":
        value = json.loads((location / "package.json").read_text())
        name, version = value["name"], value["version"]
    elif kind in {"python", "rust"}:
        file = "pyproject.toml" if kind == "python" else "Cargo.toml"
        section = "project" if kind == "python" else "package"
        value = tomllib.loads((location / file).read_text())[section]
        name, version = value["name"], value["version"]
    else:
        value = ET.parse(location / "pom.xml").getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        name = (
            value.findtext("m:groupId", namespaces=ns)
            + ":"
            + value.findtext("m:artifactId", namespaces=ns)
        )
        version = value.findtext("m:version", namespaces=ns)
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("release version must be an explicit stable X.Y.Z")
    if not isinstance(name, str) or not re.fullmatch(r"[@a-zA-Z0-9_./:-]+", name):
        raise ValueError("unsafe package name")
    expected = prefix + version
    if tag is not None and tag != expected:
        raise ValueError(f"release tag must match package version: {expected}")
    return {
        "target": target,
        "directory": directory,
        "name": name,
        "version": version,
        "tag": expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--tag", help="Require this exact release tag")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    try:
        result = metadata(args.target, args.tag)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if args.github_output:
        for key, value in result.items():
            print(f"{key}={value}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
