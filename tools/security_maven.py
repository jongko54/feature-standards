"""Resolve source Maven projects in an isolated repository for security scanning.

The generated CycloneDX files contain actual resolved project dependencies from
all Maven scopes. They do not inventory build plugins or the JDK. No publication,
tests, application startup, account settings or shared Maven cache is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlencode

MAVEN_POMS = (
    "implementations/java-spring/pom.xml",
    "libraries/java/pom.xml",
    "examples/consumer-java/pom.xml",
    "examples/core-java/pom.xml",
)
PLUGIN_COORDINATE = "org.apache.maven.plugins:maven-dependency-plugin"
SCOPES = {"compile", "runtime", "test", "provided", "system", "import"}


class MavenInventoryError(ValueError):
    """A sanitized error: raw Maven output is kept only in private work files."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plugin_goal(config: dict) -> str:
    version = config.get("version", "")
    if config.get("coordinate") != PLUGIN_COORDINATE or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", version
    ):
        raise MavenInventoryError("invalid-maven-plugin-pin")
    return f"{PLUGIN_COORDINATE}:{version}:tree"


def maven_environment(work: Path, inherited: dict | None = None) -> dict:
    inherited = os.environ if inherited is None else inherited
    allowed = {
        "PATH",
        "HOME",
        "JAVA_HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {
        **{key: value for key, value in inherited.items() if key in allowed},
        "MAVEN_USER_HOME": str(work / "maven-user"),
        "MAVEN_SKIP_RC": "true",
    }


def pom_identity(path: Path) -> tuple[str, str, str]:
    element = ET.parse(path).getroot()
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    fields = []
    for name in ("groupId", "artifactId", "version"):
        value = element.findtext(f"m:{name}", namespaces=namespace)
        if value is None and name != "artifactId":
            value = element.findtext(f"m:parent/m:{name}", namespaces=namespace)
        if not value:
            raise MavenInventoryError("missing-maven-project-identity")
        fields.append(value.strip())
    return tuple(fields)


def dependency_bom(tree: dict, expected: tuple[str, str, str]) -> dict:
    """Convert the pinned plugin's JSON tree without resolving guessed versions."""
    components: dict[str, dict] = {}
    graph: dict[str, set] = {}
    visits = 0

    def visit(node: dict, depth: int = 0) -> str:
        nonlocal visits
        visits += 1
        if visits > 10_000 or depth > 100 or not isinstance(node, dict):
            raise MavenInventoryError("invalid-maven-tree")
        try:
            group, artifact, version, kind = (
                node[key] for key in ("groupId", "artifactId", "version", "type")
            )
            classifier = node.get("classifier", "")
            scope = node["scope"]
            children = node.get("children", [])
        except (KeyError, TypeError):
            raise MavenInventoryError("invalid-maven-tree") from None
        if (
            not all(
                isinstance(value, str)
                for value in (group, artifact, version, kind, classifier, scope)
            )
            or not all(
                re.fullmatch(r"[A-Za-z0-9_.-]+", value)
                for value in (group, artifact, kind)
            )
            or (classifier and not re.fullmatch(r"[A-Za-z0-9_.-]+", classifier))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", version)
            or version in {"LATEST", "RELEASE"}
            or version.endswith("-SNAPSHOT")
            or not isinstance(children, list)
            or (depth and scope not in SCOPES)
            or (not depth and ((group, artifact, version) != expected or scope != ""))
        ):
            raise MavenInventoryError("unresolved-or-invalid-maven-coordinate")
        qualifiers = {"type": kind}
        if classifier:
            qualifiers["classifier"] = classifier
        purl = (
            f"pkg:maven/{quote(group, safe='')}/{quote(artifact, safe='')}"
            f"@{quote(version, safe='')}?{urlencode(sorted(qualifiers.items()))}"
        )
        component = components.setdefault(
            purl,
            {
                "type": "library" if depth else "application",
                "bom-ref": purl,
                "group": group,
                "name": artifact,
                "version": version,
                "purl": purl,
                "properties": [],
            },
        )
        if scope:
            property_value = {"name": "feature-standards:maven-scope", "value": scope}
            if property_value not in component["properties"]:
                component["properties"].append(property_value)
        graph.setdefault(purl, set()).update(
            visit(child, depth + 1) for child in children
        )
        return purl

    root = visit(tree)
    project = components.pop(root)
    if not components:
        raise MavenInventoryError("empty-maven-dependency-inventory")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": project},
        "components": [components[key] for key in sorted(components)],
        "dependencies": [
            {"ref": key, "dependsOn": sorted(value)}
            for key, value in sorted(graph.items())
        ],
    }


def maven_coverage(inventory: list[dict], projects: list[dict]) -> dict:
    """Require every resolved Maven package to reach the scanner, per source POM."""
    if {project["sourcePom"] for project in projects} != set(MAVEN_POMS):
        raise MavenInventoryError("maven-project-coverage-mismatch")
    coverage = []
    for project in projects:
        expected = {
            (row["name"], row["version"]) for row in project["resolvedPackages"]
        }
        rows = [row for row in inventory if row["source"] == project["sourcePom"]]
        actual = {
            (row["name"], row["version"]) for row in rows if row["ecosystem"] == "Maven"
        }
        passed = (
            bool(expected)
            and expected == actual
            and all(row["ecosystem"] == "Maven" for row in rows)
        )
        coverage.append(
            {
                "sourcePom": project["sourcePom"],
                "status": "passed" if passed else "error",
                "expectedPackages": len(expected),
                "scannedPackages": len(actual),
            }
        )
    return {
        "status": "passed"
        if all(row["status"] == "passed" for row in coverage)
        else "error",
        "projects": coverage,
    }


def execute(argv: list[str], cwd: Path, env: dict, log: Path) -> None:
    try:
        with log.open("xb") as output:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=1200,
                check=False,
            )
        if result.returncode:
            raise MavenInventoryError("maven-resolution-failed")
    except (OSError, subprocess.SubprocessError):
        raise MavenInventoryError("maven-resolution-failed") from None


def create_inventory(
    root: Path,
    manifests: list[str],
    files: list[str],
    work: Path,
    plugin: dict,
) -> tuple[list[Path], dict[str, str], dict]:
    goal = plugin_goal(plugin)
    if {path for path in manifests if Path(path).name == "pom.xml"} != set(MAVEN_POMS):
        raise MavenInventoryError("maven-project-coverage-mismatch")
    if (
        work.exists()
        or work.is_symlink()
        or work.resolve().is_relative_to(root.resolve())
    ):
        raise MavenInventoryError("maven-workspace-must-be-new-and-private")
    # On macOS /var is an alias for /private/var. Use one identical absolute
    # path both in OSV's argv and in the narrowly permitted source aliases.
    work = work.resolve()
    work.mkdir(parents=True, mode=0o700)
    snapshot = work / "source"
    source_hashes = {}
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise MavenInventoryError("unsafe-maven-source-path")
        if not any(path.is_relative_to(Path(pom).parent) for pom in MAVEN_POMS):
            continue
        source = root / path
        if not source.is_file() or source.is_symlink():
            raise MavenInventoryError("unsupported-maven-source-file")
        target = snapshot / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hashes[name] = sha256(target)
    if not set(MAVEN_POMS) <= set(source_hashes):
        raise MavenInventoryError("missing-maven-source-pom")
    settings = work / "blank-settings.xml"
    settings.write_text('<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"/>')
    wrapper = snapshot / "implementations/java-spring/mvnw"
    env = maven_environment(work)
    args = [
        str(wrapper),
        "--batch-mode",
        "--no-transfer-progress",
        "--strict-checksums",
        "-s",
        str(settings),
        "-gs",
        str(settings),
        "-Dmaven.repo.local=" + str(work / "m2"),
    ]
    for index, pom in enumerate(MAVEN_POMS[:2]):
        execute(
            [*args, "-f", str(snapshot / pom), "-DskipTests", "install"],
            snapshot,
            env,
            work / f"install-{index}.private.log",
        )
    local_artifacts = []
    for index, pom in enumerate(MAVEN_POMS[:2]):
        group, artifact, version = pom_identity(snapshot / pom)
        suffix = "-library" if index == 0 else ""
        filename = f"{artifact}-{version}{suffix}.jar"
        installed = (
            work / "m2" / Path(*group.split(".")) / artifact / version / filename
        )
        built = (
            snapshot
            / Path(pom).parent
            / "target"
            / ("auth-server-library.jar" if index == 0 else filename)
        )
        if (
            not installed.is_file()
            or not built.is_file()
            or not built.stat().st_size
            or sha256(installed) != sha256(built)
        ):
            raise MavenInventoryError("local-source-artifact-install-mismatch")
        local_artifacts.append(
            {"sourcePom": pom, "artifact": filename, "sha256": sha256(built)}
        )
    sboms, aliases, projects = [], {}, []
    for index, pom in enumerate(MAVEN_POMS):
        tree_file = work / f"tree-{index}.json"
        execute(
            [
                *args,
                "-f",
                str(snapshot / pom),
                goal,
                "-DoutputType=json",
                "-Dverbose=false",
                "-DoutputFile=" + str(tree_file),
            ],
            snapshot,
            env,
            work / f"tree-{index}.private.log",
        )
        try:
            tree = json.loads(tree_file.read_text())
            bom = dependency_bom(tree, pom_identity(snapshot / pom))
        except (OSError, TypeError, ValueError, ET.ParseError):
            raise MavenInventoryError("invalid-maven-resolution-output") from None
        sbom = work / f"project-{index}.cdx.json"
        sbom.write_text(json.dumps(bom, sort_keys=True, indent=2) + "\n")
        sboms.append(sbom)
        aliases[str(sbom.resolve())] = pom
        projects.append(
            {
                "sourcePom": pom,
                "pomSha256": source_hashes[pom],
                "treeSha256": sha256(tree_file),
                "sbomSha256": sha256(sbom),
                "components": len(bom["components"]),
                "resolvedPackages": [
                    {
                        "name": f"{component['group']}:{component['name']}",
                        "version": component["version"],
                    }
                    for component in bom["components"]
                ],
                "scopes": sorted(
                    {
                        prop["value"]
                        for component in bom["components"]
                        for prop in component["properties"]
                    }
                ),
            }
        )
    if any(sha256(root / name) != digest for name, digest in source_hashes.items()):
        raise MavenInventoryError("maven-source-changed-during-resolution")
    return (
        sboms,
        aliases,
        {
            "kind": "actual-resolved-maven-project-dependencies",
            "plugin": goal,
            "sourceInputHashes": source_hashes,
            "projects": projects,
            "localSourceInstall": [
                {"sourcePom": pom, "arguments": ["-DskipTests", "install"]}
                for pom in MAVEN_POMS[:2]
            ],
            "localSourceArtifacts": local_artifacts,
            "treeArguments": [
                goal,
                "-DoutputType=json",
                "-Dverbose=false",
                "-DoutputFile=<private>",
            ],
            "scopeFilter": None,
            "privateRepository": True,
            "blankUserAndGlobalSettings": True,
            "buildPluginsAndJdkInventoried": False,
        },
    )
