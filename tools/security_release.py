"""Bind release artifact digests to verified source workflow references."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def release_report(
    receipt: dict, artifacts: Path, source_commit: str, *, now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    if (
        receipt.get("kind") != "verified-source-workflow-references"
        or receipt.get("status") != "passed"
        or receipt.get("sourceCommit") != source_commit
    ):
        raise ValueError("source security receipt mismatch")
    if receipt.get("repository") != "jongko54/feature-standards" or not re.fullmatch(
        r"[a-f0-9]{40}", source_commit
    ):
        raise ValueError("untrusted release source")
    age = (now - datetime.fromisoformat(receipt["verifiedAt"])).total_seconds()
    if not -300 <= age <= 3600:
        raise ValueError("source verification receipt expired")
    for label, workflow in (("functional", "ci.yml"), ("security", "security.yml")):
        check = receipt["checks"][label]
        run_id = check["runId"]
        if (
            type(run_id) is not int
            or run_id < 1
            or check["workflow"] != workflow
            or check["conclusion"] != "success"
        ):
            raise ValueError("invalid source workflow reference")
        if (
            check["url"]
            != f"https://github.com/jongko54/feature-standards/actions/runs/{run_id}"
        ):
            raise ValueError("untrusted source workflow URL")
    security_age = (
        now - datetime.fromisoformat(receipt["checks"]["security"]["createdAt"])
    ).total_seconds()
    if not -300 <= security_age <= 72 * 3600:
        raise ValueError("security workflow evidence expired")
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ValueError("artifact directory must be physical")
    inventory = []
    allowed = (
        ".tgz",
        ".whl",
        ".tar.gz",
        ".crate",
        ".jar",
        ".pom",
        ".module",
        ".asc",
        ".sha256",
        ".sha512",
        ".zip",
    )
    for path in sorted(artifacts.rglob("*")):
        if path.is_symlink():
            raise ValueError("linked release artifact")
        if path.is_dir():
            continue
        if not path.name.endswith(allowed) and not re.fullmatch(
            r"checks-(?:npm|python|rust|java)\.json", path.name
        ):
            raise ValueError("unexpected release artifact type")
        inventory.append(
            {
                "path": path.relative_to(artifacts).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not inventory:
        raise ValueError("no release artifacts")
    return {
        "schemaVersion": 1,
        "kind": "release-artifact-digest-binding",
        "createdAt": now.isoformat(),
        "sourceCommit": source_commit,
        "sourceVerification": receipt,
        "artifacts": inventory,
        "scope": "Artifact byte hashes bound to verified source workflow references; artifacts are not independently vulnerability-scanned here.",
        "registryPublished": False,
        "signedAttestation": False,
        "externalSecurityAudit": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=False).returncode:
        raise ValueError("release source has tracked modifications")
    report = release_report(
        json.loads(args.receipt.read_text()), args.artifacts, commit
    )
    with args.out.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(
        json.dumps({"sourceCommit": commit, "artifactCount": len(report["artifacts"])})
    )
