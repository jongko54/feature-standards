"""Build committed server artifacts and test consumers outside the checkout.

This command only builds/installs local artifacts. It never publishes, uses a
database, sends SMTP mail, or alters the original checkout. Public registry
availability must be verified separately.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = {
    "python": ("implementations/python-fastapi",),
    "java": ("implementations/java-spring", "examples/consumer-java"),
    "rust": ("implementations/rust-axum", "examples/consumer-rust"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_members(
    archive: tarfile.TarFile, prefix: str = ""
) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)):
        raise ValueError("duplicate-archive-path")
    for member in members:
        path = Path(member.name)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or not (member.isfile() or member.isdir())
            or (prefix and path.parts[0] != prefix)
        ):
            raise ValueError("unsafe-archive-member")
    return members


def inspect_wheel(path: Path, expected: tuple[str, str]) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_files = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(names) != len(set(names)) or len(metadata_files) != 1:
            raise ValueError("invalid-wheel-inventory")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if (metadata["Name"], metadata["Version"]) != expected:
            raise ValueError("wheel-identity-mismatch")
        if "feature_auth/__init__.py" not in names or "app.py" in names:
            raise ValueError("wheel-public-package-missing")
    return {
        "name": metadata["Name"],
        "version": metadata["Version"],
        "sha256": digest(path),
    }


def inspect_library_jar(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "dev/featurestandards/auth/AuthService.class" not in names or any(
            name.startswith("BOOT-INF/") for name in names
        ):
            raise ValueError("not-a-reusable-library-jar")
        if (
            "application.properties" in names
            or "dev/featurestandards/auth/AuthApplication.class" in names
        ):
            raise ValueError("reference-application-in-library")
    return {"sha256": digest(path), "plainLibraryJar": True}


def fixture_environment(work: Path) -> dict[str, str]:
    # Preserve the real HOME; isolate Maven configuration and strip runtime and
    # publisher settings rather than allowing inherited DB/SMTP/auth settings.
    env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "HOME",
            "JAVA_HOME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
        )
        if key in os.environ
    }
    env.update(
        MAVEN_USER_HOME=str(work / "maven-user"),
        MAVEN_SKIP_RC="true",
        CARGO_TARGET_DIR=str(work / "rust-target"),
        UV_CACHE_DIR=str(work / "uv-cache"),
        GOWORK="off",
    )
    return env


def execute(
    argv: list[str], cwd: Path, env: dict[str, str], stage: str, timeout: int = 900
) -> bytes:
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        # No raw command output, environment, or exception may contain account
        # credentials or an accidental inherited URI in the public receipt.
        raise ValueError(stage + "-failed")
    return result.stdout


def committed_snapshot(
    source: Path, work: Path, stacks: list[str]
) -> tuple[Path, str, list[str]]:
    paths = sorted({path for stack in stacks for path in PATHS[stack]})
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    changes = subprocess.check_output(
        [
            "git",
            "-C",
            str(source),
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--",
            *paths,
        ]
    )
    if changes:
        raise ValueError("selected-server-source-must-be-committed")
    data = subprocess.check_output(
        ["git", "-C", str(source), "archive", "--format=tar", commit, *paths]
    )
    snapshot = work / "committed-source"
    snapshot.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive_members(archive)
        archive.extractall(snapshot, members=members, filter="data")
    return snapshot, commit, paths


def check_python(snapshot: Path, work: Path, env: dict[str, str]) -> dict:
    source = snapshot / PATHS["python"][0]
    metadata = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    expected = metadata["name"], metadata["version"]
    output = work / "python-dist"
    execute(
        ["uv", "build", "--project", str(source), "--out-dir", str(output)],
        work,
        env,
        "python-build",
    )
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1 or len(list(output.glob("*.tar.gz"))) != 1:
        raise ValueError("python-wheel-and-sdist-required")
    artifact = inspect_wheel(wheels[0], expected)
    # Delete only our private snapshot; the consumer can no longer import it.
    shutil.rmtree(source)
    venv = work / "python-consumer-env"
    execute(
        ["uv", "venv", "--python", sys.executable, str(venv)], work, env, "python-venv"
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    execute(
        ["uv", "pip", "install", "--python", str(python), str(wheels[0])],
        work,
        env,
        "python-wheel-install",
    )
    probe = """
import asyncio, importlib.metadata, pathlib, sys
import feature_auth
from feature_auth import Settings, create_app, current_user
from starlette.requests import Request
assert importlib.metadata.version('feature-standards-python-auth') == sys.argv[1]
assert pathlib.Path(feature_auth.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
assert callable(current_user)
async def verify():
    app = create_app(settings=Settings(demo=True, email='demo@example.com',
        password='correct-horse-battery-staple', secure_cookie=False))
    async with app.router.lifespan_context(app):
        endpoint = next(route.endpoint for route in app.routes if route.path == '/healthz')
        request = Request({'type':'http', 'app':app, 'headers':[], 'method':'GET', 'path':'/healthz'})
        result = endpoint(request)
        assert result['status'] == 'ok' and result['profile'] == 'browser-session-v1'
asyncio.run(verify())
"""
    execute(
        [str(python), "-I", "-c", probe, expected[1]], work, env, "python-public-api"
    )
    return {
        "stack": "python",
        **artifact,
        "wheelInstalledOutsideCheckout": True,
        "privateSourceRemovedBeforeImport": True,
        "publicApiAndMemoryHealth": True,
    }


def check_java(snapshot: Path, work: Path, env: dict[str, str]) -> dict:
    source = snapshot / PATHS["java"][0]
    consumer = work / "java-consumer"
    shutil.copytree(snapshot / PATHS["java"][1], consumer)
    wrapper = source / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    # Keep a wrapper in a separate staging folder before deleting library source.
    wrapper_home = work / "maven-wrapper"
    wrapper_home.mkdir()
    shutil.copy2(wrapper, wrapper_home / wrapper.name)
    shutil.copytree(source / ".mvn", wrapper_home / ".mvn")
    wrapper = wrapper_home / wrapper.name
    settings = work / "blank-settings.xml"
    settings.write_text('<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"/>')
    repository = work / "m2"
    args = [
        str(wrapper),
        "--batch-mode",
        "--no-transfer-progress",
        "-s",
        str(settings),
        "-gs",
        str(settings),
        "-Dmaven.repo.local=" + str(repository),
    ]
    execute(
        [*args, "-f", str(source / "pom.xml"), "-Dmaven.test.skip=true", "install"],
        source,
        env,
        "java-library-build",
    )
    artifact = inspect_library_jar(source / "target/auth-server-library.jar")
    pom = ET.parse(source / "pom.xml").getroot()
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    group, name, version = (
        pom.findtext("m:" + key, namespaces=ns)
        for key in ("groupId", "artifactId", "version")
    )
    installed = (
        repository
        / group.replace(".", "/")
        / name
        / version
        / (name + "-" + version + "-library.jar")
    )
    if digest(installed) != artifact["sha256"]:
        raise ValueError("installed-library-jar-mismatch")
    shutil.rmtree(source)
    execute(
        [*args, "-f", str(consumer / "pom.xml"), "test"],
        consumer,
        env,
        "java-independent-consumer",
    )
    reports = list((consumer / "target/surefire-reports").glob("TEST-*.xml"))
    totals = {
        key: sum(int(ET.parse(report).getroot().get(key, "0")) for report in reports)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if not totals["tests"] or any(
        totals[key] for key in ("failures", "errors", "skipped")
    ):
        raise ValueError("java-consumer-tests-not-complete")
    return {
        "stack": "java",
        "name": group + ":" + name,
        "version": version,
        **artifact,
        "freshPrivateMavenRepository": True,
        "privateSourceRemovedBeforeConsumer": True,
        "installedJarUsedByConsumer": True,
        "consumerTests": totals["tests"],
    }


def check_rust(snapshot: Path, work: Path, env: dict[str, str]) -> dict:
    source = snapshot / PATHS["rust"][0]
    metadata = tomllib.loads((source / "Cargo.toml").read_text())["package"]
    name, version = metadata["name"], metadata["version"]
    execute(
        ["cargo", "package", "--locked", "--manifest-path", str(source / "Cargo.toml")],
        source,
        env,
        "rust-package",
    )
    artifact = work / "rust-target/package" / (name + "-" + version + ".crate")
    unpacked = work / "rust-artifact"
    unpacked.mkdir()
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive_members(archive, name + "-" + version)
        archive.extractall(unpacked, members=members, filter="data")
    package = unpacked / (name + "-" + version)
    actual = tomllib.loads((package / "Cargo.toml").read_text())["package"]
    if (actual["name"], actual["version"]) != (name, version):
        raise ValueError("crate-identity-mismatch")
    consumer = work / "rust-consumer"
    shutil.copytree(snapshot / PATHS["rust"][1], consumer)
    manifest = consumer / "Cargo.toml"
    text = manifest.read_text()
    marker = 'feature-standards-auth = { path = "../../implementations/rust-axum" }'
    if text.count(marker) != 1:
        raise ValueError("unsupported-rust-consumer-layout")
    manifest.write_text(
        text.replace(
            marker,
            "feature-standards-auth = { path = " + json.dumps(str(package)) + " }",
        )
    )
    shutil.rmtree(source)
    execute(
        ["cargo", "test", "--locked", "--manifest-path", str(manifest)],
        consumer,
        env,
        "rust-independent-consumer",
    )
    return {
        "stack": "rust",
        "name": name,
        "version": version,
        "sha256": digest(artifact),
        "crateUnpackedOutsideCheckout": True,
        "privateSourceRemovedBeforeConsumer": True,
        "consumerDependency": "unpacked-local-crate",
        "consumerLifecycleTest": True,
    }


def check_distributions(source: Path, stacks: list[str]) -> dict:
    source = source.resolve()
    if not stacks or any(stack not in PATHS for stack in stacks):
        raise ValueError("unsupported-stack")
    before = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all"]
    )
    with tempfile.TemporaryDirectory(
        prefix="fs-distributions-", dir=Path(tempfile.gettempdir()).resolve()
    ) as temporary:
        work = Path(temporary)
        work.chmod(0o700)
        snapshot, commit, paths = committed_snapshot(source, work, stacks)
        env = fixture_environment(work)
        checks = {"python": check_python, "java": check_java, "rust": check_rust}
        results = [checks[stack](snapshot, work, env) for stack in stacks]
        # Other agents may edit unrelated files during this check. Only the selected
        # committed server and consumer paths are required to remain untouched.
        changed = subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain=v1", "--", *paths]
        )
        if changed:
            raise ValueError("selected-source-was-modified")
        return {
            "sourceCommit": commit,
            "sourceCheckoutDirtyAtStart": bool(before),
            "selectedSourceUnchanged": True,
            "consumers": results,
            "databaseUsed": False,
            "smtpUsed": False,
            "published": False,
            "scope": "Local distribution consumers only; no public-registry installation is claimed.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--stack", choices=["all", *PATHS], default="all")
    args = parser.parse_args()
    stacks = list(PATHS) if args.stack == "all" else [args.stack]
    try:
        print(json.dumps(check_distributions(args.source, stacks), indent=2))
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        tarfile.TarError,
        zipfile.BadZipFile,
        ET.ParseError,
    ) as exc:
        print("Server distribution check: FAIL (" + str(exc) + ")", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
