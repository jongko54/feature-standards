"""Build and inspect a signed Central bundle using an ephemeral test-only key.

This command cannot publish: its temporary POM forces skipUpload and replaces
the Central URL with a loopback trap. Test keys and bundle are deleted afterward.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "http://maven.apache.org/POM/4.0.0"
ET.register_namespace("", NS)
TEST_IDENTITY = "Feature Standards release fixture <fixture@example.invalid>"


def q(name: str) -> str:
    return "{" + NS + "}" + name


def child(parent: ET.Element, name: str, value: str) -> None:
    element = parent.find(q(name))
    if element is None:
        element = ET.SubElement(parent, q(name))
    element.text = value


def coordinates(pom: ET.Element) -> tuple[str, str, str]:
    values = tuple(
        pom.findtext(q(name)) or "" for name in ("groupId", "artifactId", "version")
    )
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in values):
        raise ValueError("explicit-safe-coordinates-required")
    if values[2].endswith("-SNAPSHOT"):
        raise ValueError("release-version-required")
    required = (
        "name",
        "description",
        "url",
        "licenses/license/name",
        "licenses/license/url",
        "developers/developer/id",
        "developers/developer/name",
        "developers/developer/url",
        "scm/connection",
        "scm/developerConnection",
        "scm/url",
    )
    for path in required:
        element = pom.find("/".join(q(part) for part in path.split("/")))
        if element is None or not (element.text or "").strip():
            raise ValueError("missing-central-pom-metadata")
    return values


def overlay(source: Path, work: Path, endpoint: str, gpg: str) -> bytes:
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+/forbidden", endpoint):
        raise ValueError("loopback-trap-required")
    pom = ET.parse(source / "pom.xml").getroot()
    coordinates(pom)
    profiles = pom.findall(q("profiles") + "/" + q("profile"))
    if len(profiles) != 1 or profiles[0].findtext(q("id")) != "central-release":
        raise ValueError("unexpected-release-profiles")
    plugins = profiles[0].findall(q("build") + "/" + q("plugins") + "/" + q("plugin"))
    by_id = {plugin.findtext(q("artifactId")): plugin for plugin in plugins}
    if set(by_id) != {"maven-gpg-plugin", "central-publishing-maven-plugin"}:
        raise ValueError("unexpected-release-plugins")
    central = by_id["central-publishing-maven-plugin"]
    if (
        central.findtext(q("groupId")) != "org.sonatype.central"
        or central.findtext(q("version")) != "0.12.0"
    ):
        raise ValueError("verified-central-plugin-version-required")
    config = central.find(q("configuration"))
    if config is not None:
        central.remove(config)
    config = ET.SubElement(central, q("configuration"))
    for key, value in {
        "skipUpload": "true",
        "skipPublishing": "false",
        "ignorePublishedComponents": "false",
        "centralBaseUrl": endpoint,
        "autoPublish": "false",
        "waitUntil": "uploaded",
    }.items():
        child(config, key, value)
    signer = by_id["maven-gpg-plugin"]
    config = signer.find(q("configuration"))
    if config is not None:
        signer.remove(config)
    config = ET.SubElement(signer, q("configuration"))
    for key, value in {
        "homedir": str(work / "gpg"),
        "executable": gpg,
        "keyname": TEST_IDENTITY,
        "bestPractices": "true",
        "interactive": "false",
    }.items():
        child(config, key, value)
    arguments = ET.SubElement(config, q("gpgArguments"))
    for value in ("--batch", "--no-tty", "--pinentry-mode", "loopback"):
        ET.SubElement(arguments, q("arg")).text = value
    build = pom.find(q("build"))
    if build is None:
        raise ValueError("source-build-required")
    child(build, "sourceDirectory", str(source / "src/main/java"))
    resources = ET.SubElement(build, q("resources"))
    resource = ET.SubElement(resources, q("resource"))
    child(resource, "directory", str(source / "src/main/resources"))
    return ET.tostring(pom, encoding="utf-8", xml_declaration=True)


def source_hashes(source: Path) -> dict[str, str]:
    files = [source / "pom.xml", *(source / "src").rglob("*")]
    return {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
        if path.is_file()
    }


def execute(
    argv: list[str], *, cwd: Path, env: dict[str, str], stage: str, timeout: int = 900
) -> bytes:
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, check=False, timeout=timeout
    )
    if result.returncode:
        raise ValueError(stage + "-failed")
    return result.stdout


def inspect_bundle(
    bundle: Path,
    expected: tuple[str, str, str],
    home: Path,
    gpg: str,
    env: dict[str, str],
) -> dict:
    group, artifact, version = expected
    prefix = group.replace(".", "/") + "/" + artifact + "/" + version + "/"
    base = artifact + "-" + version
    artifact_names = [
        base + suffix
        for suffix in (".pom", ".jar", "-library.jar", "-sources.jar", "-javadoc.jar")
    ]
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            not name.startswith(prefix) or ".." in Path(name).parts for name in names
        ):
            raise ValueError("unexpected-bundle-path")
        contents = {
            name[len(prefix) :]: archive.read(name)
            for name in names
            if not name.endswith("/")
        }
    allowed = {
        name + suffix
        for name in artifact_names
        for suffix in ("", ".asc", ".md5", ".sha1", ".sha256", ".sha512")
    }
    if set(contents) - allowed:
        raise ValueError("unexpected-bundle-artifact")
    for name in artifact_names:
        if name not in contents or name + ".asc" not in contents:
            raise ValueError("missing-artifact-or-signature")
        for algorithm in ("md5", "sha1", "sha256", "sha512"):
            checksum = contents.get(name + "." + algorithm, b"").decode("ascii").strip()
            if checksum != hashlib.new(algorithm, contents[name]).hexdigest():
                raise ValueError("invalid-bundle-checksum")
        target = home.parent / name
        target.write_bytes(contents[name])
        signature = target.with_name(name + ".asc")
        signature.write_bytes(contents[name + ".asc"])
        execute(
            [
                gpg,
                "--homedir",
                str(home),
                "--batch",
                "--verify",
                str(signature),
                str(target),
            ],
            cwd=home.parent,
            env=env,
            stage="signature-verification",
            timeout=30,
        )
    if coordinates(ET.fromstring(contents[base + ".pom"])) != expected:
        raise ValueError("bundle-coordinate-mismatch")
    for suffix in (".jar", "-library.jar", "-sources.jar", "-javadoc.jar"):
        with zipfile.ZipFile(io.BytesIO(contents[base + suffix])) as jar:
            entries = set(jar.namelist())
            if not any(name.endswith("/LICENSE") for name in entries):
                raise ValueError("jar-license-missing")
            if suffix == "-library.jar":
                if "dev/featurestandards/auth/AuthService.class" not in entries or any(
                    name.startswith("BOOT-INF/") for name in entries
                ):
                    raise ValueError("library-not-reusable-jar")
                if (
                    "application.properties" in entries
                    or "dev/featurestandards/auth/AuthApplication.class" in entries
                ):
                    raise ValueError("reference-application-leaked-into-library")
            elif (
                suffix == "-sources.jar"
                and "dev/featurestandards/auth/AuthService.java" not in entries
            ):
                raise ValueError("sources-missing")
            elif suffix == "-javadoc.jar" and "index.html" not in entries:
                raise ValueError("javadoc-missing")
    return {
        "coordinates": ":".join(expected),
        "bundle_files": len(contents),
        "artifacts": len(artifact_names),
        "verified_signatures": len(artifact_names),
        "verified_checksums": len(artifact_names) * 4,
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    }


class UploadTrap(http.server.BaseHTTPRequestHandler):
    requests = 0

    def parse_request(self):
        type(self).requests += 1
        return super().parse_request()

    def do_GET(self):
        self.send_error(403)

    do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = do_GET

    def log_message(self, *_args):
        pass


def fixture_environment(
    work: Path, inherited: Mapping[str, str] | None = None
) -> dict[str, str]:
    inherited = os.environ if inherited is None else inherited
    env = {
        key: inherited[key]
        for key in (
            "PATH",
            "JAVA_HOME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
            "HOME",
        )
        if key in inherited
    }
    env.update(
        GNUPGHOME=str(work / "gpg"),
        MAVEN_USER_HOME=str(work / "maven-user"),
        MAVEN_SKIP_RC="true",
    )
    return env


def check_release(source: Path) -> dict:
    source = source.resolve()
    gpg = shutil.which("gpg")
    gpgconf = shutil.which("gpgconf")
    if not gpg or not gpgconf:
        raise ValueError("gpg-and-gpgconf-required")
    before = source_hashes(source)
    expected = coordinates(ET.parse(source / "pom.xml").getroot())
    # A short private path also keeps GPG's Unix-domain socket below platform limits.
    with tempfile.TemporaryDirectory(
        prefix="fs-mvn-", dir=Path(tempfile.gettempdir()).resolve()
    ) as temporary:
        work = Path(temporary)
        home = work / "gpg"
        home.mkdir(mode=0o700)
        env = fixture_environment(work)
        try:
            execute(
                [
                    gpg,
                    "--homedir",
                    str(home),
                    "--batch",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase",
                    "",
                    "--quick-generate-key",
                    TEST_IDENTITY,
                    "ed25519",
                    "sign",
                    "1d",
                ],
                cwd=work,
                env=env,
                stage="test-key-generation",
                timeout=60,
            )
            UploadTrap.requests = 0
            with http.server.ThreadingHTTPServer(("127.0.0.1", 0), UploadTrap) as trap:
                thread = threading.Thread(target=trap.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = f"http://127.0.0.1:{trap.server_port}/forbidden"
                    (work / "pom.xml").write_bytes(overlay(source, work, endpoint, gpg))
                    (work / "settings.xml").write_text(
                        '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"/>'
                    )
                    execute(
                        [
                            str(source / "mvnw"),
                            "--batch-mode",
                            "--no-transfer-progress",
                            "-s",
                            str(work / "settings.xml"),
                            "-gs",
                            str(work / "settings.xml"),
                            "-f",
                            str(work / "pom.xml"),
                            "-Dmaven.repo.local=" + str(work / "m2"),
                            "-Dmaven.test.skip=true",
                            "-DskipUpload=true",
                            "-DignorePublishedComponents=false",
                            "-Pcentral-release",
                            "deploy",
                        ],
                        cwd=work,
                        env=env,
                        stage="maven-bundle",
                    )
                finally:
                    trap.shutdown()
                    thread.join(timeout=5)
                if UploadTrap.requests:
                    raise ValueError("unexpected-central-request")
            result = inspect_bundle(
                work / "target/central-publishing/central-bundle.zip",
                expected,
                home,
                gpg,
                env,
            )
            if source_hashes(source) != before:
                raise ValueError("source-was-modified")
            return {
                **result,
                "source_unchanged": True,
                "test_key_only": True,
                "central_requests": 0,
                "published": False,
            }
        finally:
            subprocess.run(
                [gpgconf, "--homedir", str(home), "--kill", "gpg-agent"],
                env=env,
                capture_output=True,
                check=False,
                timeout=10,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "implementations/java-spring"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(check_release(args.source), indent=2))
    except (
        ValueError,
        OSError,
        subprocess.TimeoutExpired,
        zipfile.BadZipFile,
        ET.ParseError,
    ) as exc:
        print("Maven release fixture: FAIL (" + str(exc) + ")")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
