#!/usr/bin/env python3
"""Create a production-signed core Maven bundle after full source CI. Never uploads."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from release_metadata import metadata

ROOT = Path(__file__).resolve().parents[1]


def run(argv, *, env=None, capture=False):
    return subprocess.run(
        list(map(str, argv)),
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key",
        required=True,
        help="Existing production GPG fingerprint; never a password",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist/core/central")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Fa-f0-9]{40}", args.key):
        parser.error("Expected a complete production GPG fingerprint")
    if run(["git", "status", "--porcelain"], capture=True).stdout.strip():
        parser.error("Commit source changes before preparing the signed release")
    sha = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    runs = json.loads(
        run(
            [
                "gh",
                "run",
                "list",
                "--repo",
                "jongko54/feature-standards",
                "--workflow",
                "ci.yml",
                "--commit",
                sha,
                "--limit",
                "30",
                "--json",
                "headSha,headBranch,event,conclusion,url",
            ],
            capture=True,
        ).stdout
    )
    successful = [
        entry
        for entry in runs
        if entry["headSha"] == sha
        and entry["headBranch"] == "main"
        and entry["event"] == "push"
        and entry["conclusion"] == "success"
    ]
    if not successful:
        parser.error("Full main source CI must succeed before production signing")
    if not sys.stdin.isatty():
        parser.error(
            "Run this command in your terminal so GPG can request the key passphrase privately"
        )
    details = metadata("java-core")
    group, artifact = details["name"].split(":")
    stem = artifact + "-" + details["version"]
    output = args.out_dir.resolve()
    directory = (
        output / "repository" / group.replace(".", "/") / artifact / details["version"]
    )
    directory.mkdir(parents=True, exist_ok=True)
    run(
        [
            ROOT / "implementations/java-spring/mvnw",
            "-q",
            "-f",
            "libraries/java/pom.xml",
            "-DskipTests",
            "package",
        ]
    )
    for suffix in (".jar", "-sources.jar", "-javadoc.jar"):
        shutil.copyfile(
            ROOT / "libraries/java/target" / (stem + suffix),
            directory / (stem + suffix),
        )
    shutil.copyfile(ROOT / "libraries/java/pom.xml", directory / (stem + ".pom"))
    signing_env = os.environ.copy()
    signing_env["GPG_TTY"] = os.ttyname(sys.stdin.fileno())
    artifacts = [
        directory / (stem + suffix)
        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar")
    ]
    for file in artifacts:
        signature = file.with_name(file.name + ".asc")
        run(
            [
                "gpg",
                "--yes",
                "--armor",
                "--detach-sign",
                "--local-user",
                args.key,
                "--output",
                signature,
                file,
            ],
            env=signing_env,
        )
        result = run(
            ["gpg", "--batch", "--status-fd", "1", "--verify", signature, file],
            capture=True,
        )
        if f"[GNUPG:] VALIDSIG {args.key.upper()} " not in result.stdout:
            raise ValueError("Signature did not match the selected production key")
        for algorithm in ("md5", "sha1", "sha256", "sha512"):
            file.with_name(file.name + "." + algorithm).write_text(
                hashlib.new(algorithm, file.read_bytes()).hexdigest()
            )
    bundle = output / (stem + "-bundle.zip")
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(directory.iterdir()):
            archive.write(file, file.relative_to(output / "repository"))
    record = {
        "schemaVersion": 1,
        "published": False,
        "sourceCommit": sha,
        "sourceCi": successful[0]["url"],
        "coordinates": details["name"] + ":" + details["version"],
        "signer": args.key.upper(),
        "bundle": str(bundle),
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "signaturesVerified": 4,
        "artifactChecksums": 16,
    }
    (output / "SIGNING.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
