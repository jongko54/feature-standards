"""Exercise real scanner rules with disposable synthetic positive/negative inputs."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from security_audit import scan_environment

ROOT = Path(__file__).resolve().parents[1]
POSITIVE = {
    "fixture.py": "import pickle, subprocess, ssl, requests\neval(payload)\nexec(payload)\npickle.loads(payload)\nsubprocess.run(payload, shell=True)\nrequests.get(url, verify=False)\n",
    "fixture.go": 'package fixture\nimport("crypto/tls";"os/exec")\nfunc bad(){ _ = tls.Config{InsecureSkipVerify: true};exec.Command("sh", "-c", input) }\n',
    "Fixture.java": 'import java.security.MessageDigest; class Fixture { void bad() throws Exception { new ProcessBuilder("sh", "-c", input); MessageDigest.getInstance("MD5"); } }\n',
    "fixture.rs": 'use std::process::Command; fn bad(){ client.danger_accept_invalid_certs(true); Command::new("sh").arg("-c").arg(input); }\n',
    "fixture.js": "eval(payload); new Function(payload); const options = {rejectUnauthorized: false};\n",
}
NEGATIVE = {
    "fixture.py": "import subprocess\nsubprocess.run(['echo', 'synthetic'], shell=False)\n",
    "fixture.go": 'package fixture\nimport "crypto/tls"\nfunc good(){ _ = tls.Config{InsecureSkipVerify: false} }\n',
    "Fixture.java": 'import java.security.MessageDigest; class Fixture { void good() throws Exception { MessageDigest.getInstance("SHA-256"); } }\n',
    "fixture.rs": "fn good(){ client.danger_accept_invalid_certs(false); }\n",
    "fixture.js": "const options = {rejectUnauthorized: true};\n",
}


def selftest(binaries: Path, semgrep: Path) -> None:
    expected = {
        rule["id"]
        for rule in json.loads((ROOT / "security/semgrep-rules.json").read_text())[
            "rules"
        ]
    }
    with tempfile.TemporaryDirectory(prefix="feature-security-selftest-") as temporary:
        work = Path(temporary)
        for label, samples in (("positive", POSITIVE), ("negative", NEGATIVE)):
            directory = work / label
            directory.mkdir()
            for name, content in samples.items():
                (directory / name).write_text(content)
            result = subprocess.run(
                [
                    str(semgrep),
                    "scan",
                    "--config",
                    str(ROOT / "security/semgrep-rules.json"),
                    "--metrics=off",
                    "--disable-version-check",
                    "--no-git-ignore",
                    "--strict",
                    "--json",
                    str(directory),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=ROOT,
                env=scan_environment(),
                check=False,
            )
            data = json.loads(result.stdout)
            found = {row["check_id"].split(".")[-1] for row in data["results"]}
            if (
                result.returncode
                or data["errors"]
                or len(data["paths"]["scanned"]) != len(samples)
            ):
                raise ValueError("static rule fixture failed to scan")
            if found != (expected if label == "positive" else set()):
                raise ValueError(
                    f"static fixture mismatch: {label}; missing={sorted(expected - found) if label == 'positive' else sorted(found)}"
                )
        secrets = work / "secrets"
        secrets.mkdir()
        known = json.loads((ROOT / "security/secret-exceptions.json").read_text())[
            "digests"
        ][0]
        candidate = hashlib.sha256(
            b"disposable-noncredential-scanner-fixture"
        ).hexdigest()
        (secrets / "fixture.txt").write_text(
            f'api_key = "{candidate}"\nauth = "{known}"\n'
        )
        report = work / "secrets.json"
        result = subprocess.run(
            [
                str(binaries / "gitleaks"),
                "dir",
                "--config=" + str(ROOT / "security/gitleaks.toml"),
                "--redact=100",
                "--no-banner",
                "--report-format=json",
                "--report-path=" + str(report),
                str(secrets),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=scan_environment(),
            check=False,
        )
        findings = json.loads(report.read_text())
        if (
            result.returncode != 1
            or len(findings) != 1
            or findings[0]["StartLine"] != 1
        ):
            raise ValueError(
                "secret detector fixture or narrow digest exception failed"
            )
    print(
        json.dumps(
            {
                "staticRulesExercised": len(expected),
                "staticLanguages": 5,
                "negativeFixturesPassed": len(NEGATIVE),
                "secretPositiveAndDigestException": "passed",
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument(
        "--semgrep", default=ROOT / "security/.venv/bin/semgrep", type=Path
    )
    args = parser.parse_args()
    selftest(args.bin_dir, args.semgrep)
