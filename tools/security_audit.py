"""Produce scoped security evidence; scanner failure or missing coverage blocks."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"dependencies", "static", "secrets"}
LOCK_NAMES = {
    "uv.lock",
    "Cargo.lock",
    "package-lock.json",
    "go.sum",
    "go.mod",
    "pom.xml",
}
SOURCE_ROOTS = (
    "implementations/",
    "libraries/",
    "clients/react/src/",
    "packages/",
    "examples/",
    "tools/",
)
SOURCE_SUFFIXES = {".py", ".go", ".java", ".rs", ".js", ".mjs", ".ts", ".tsx"}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(value: str, root: Path = ROOT) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            raise ValueError("scanner returned a path outside its scope") from None
    if ".." in path.parts or not path.parts:
        raise ValueError("invalid report path")
    return path.as_posix()


def overall_status(checks: dict) -> str:
    if set(checks) != REQUIRED or any(
        c.get("status") not in {"passed", "findings", "error"} for c in checks.values()
    ):
        return "error"
    statuses = {c["status"] for c in checks.values()}
    return (
        "error"
        if "error" in statuses
        else "findings"
        if "findings" in statuses
        else "passed"
    )


def normalize_osv(data: dict, code: int) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise TypeError("invalid dependency scanner report")
    inventory, findings = [], []
    for group in data["results"]:
        source = safe_path(group["source"]["path"])
        for entry in group["packages"]:
            package = entry["package"]
            item = {key: str(package[key]) for key in ("name", "version", "ecosystem")}
            item["source"] = source
            inventory.append(item)
            for vulnerability in entry.get("vulnerabilities", []):
                findings.append(
                    {
                        "id": vulnerability["id"],
                        **item,
                        "severity": vulnerability.get("database_specific", {}).get(
                            "severity", "UNKNOWN"
                        ),
                    }
                )
    valid = code in (0, 1) and inventory and ((code == 1) == bool(findings))
    return {
        "status": ("findings" if findings else "passed") if valid else "error",
        "exitCode": code,
        "packagesScanned": len(inventory),
        "uniqueFindingCount": len(
            {
                (item["id"], item["ecosystem"], item["name"], item["version"])
                for item in findings
            }
        ),
        "sourcesScanned": sorted({item["source"] for item in inventory}),
        "ecosystems": sorted({item["ecosystem"] for item in inventory}),
        "inventory": inventory,
        "findings": findings,
    }


def normalize_semgrep(data: dict, code: int) -> dict:
    scanned = data.get("paths", {}).get("scanned", [])
    errors = data.get("errors", [])
    if not all(isinstance(v, list) for v in (scanned, errors, data.get("results"))):
        raise ValueError("invalid static scanner report")
    findings = [
        {
            "rule": row["check_id"],
            "file": safe_path(row["path"]),
            "line": row["start"]["line"],
        }
        for row in data["results"]
    ]
    valid = (
        code in (0, 1) and scanned and not errors and ((code == 1) == bool(findings))
    )
    return {
        "status": ("findings" if findings else "passed") if valid else "error",
        "exitCode": code,
        "filesScanned": len(scanned),
        "findings": findings,
        "errorTypes": sorted({str(error.get("type", "unknown")) for error in errors}),
        "scannedPaths": sorted(safe_path(path) for path in scanned),
    }


def normalize_gitleaks(data: list, code: int) -> dict:
    if not isinstance(data, list):
        raise TypeError("invalid secret scanner report")
    findings = [
        {
            "rule": row["RuleID"],
            "file": safe_path(row["File"]),
            "line": row["StartLine"],
        }
        for row in data
    ]
    valid = code in (0, 1) and ((code == 1) == bool(findings))
    return {
        "status": ("findings" if findings else "passed") if valid else "error",
        "exitCode": code,
        "findings": findings,
    }


def cyclonedx(inventory: list) -> dict:
    components = {}
    types = {
        "npm": "npm",
        "PyPI": "pypi",
        "Go": "golang",
        "crates.io": "cargo",
        "Maven": "maven",
    }
    for package in inventory:
        ecosystem = package["ecosystem"]
        name, version = package["name"], package["version"]
        kind = types.get(ecosystem, "generic")
        encoded = quote(
            name.lower().replace("_", "-") if kind == "pypi" else name, safe="/"
        )
        if kind == "maven":
            encoded = "/".join(quote(part, safe="") for part in name.split(":"))
        purl = f"pkg:{kind}/{encoded}@{quote(version, safe='')}"
        component = components.setdefault(
            purl,
            {
                "type": "library",
                "name": name,
                "version": version,
                "bom-ref": purl,
                "purl": purl,
                "properties": [],
            },
        )
        prop = {
            "name": "feature-standards:dependency-source",
            "value": package["source"],
        }
        if prop not in component["properties"]:
            component["properties"].append(prop)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"timestamp": timestamp()},
        "components": list(components.values()),
    }


def mapping_check(root: Path = ROOT, *, verify_upstream: bool = False) -> dict:
    mapping = json.loads((root / "security/asvs-map.json").read_text())
    accepted = set(mapping["upstream"]["selectedRequirementIds"])
    if not accepted or any(
        not re.fullmatch(r"v5\.0\.0-\d+\.\d+\.\d+", value) for value in accepted
    ):
        raise ValueError("invalid ASVS requirement identifier")
    if verify_upstream:
        upstream = mapping["upstream"]
        expected_url = "https://github.com/OWASP/ASVS/releases/download/v5.0.0_release/OWASP_Application_Security_Verification_Standard_5.0.0_en.csv"
        if upstream["csv"] != expected_url:
            raise ValueError("untrusted ASVS source URL")
        with urlopen(expected_url, timeout=45) as response:
            content = response.read(1_000_001)
        if (
            len(content) > 1_000_000
            or hashlib.sha256(content).hexdigest() != upstream["sha256"]
        ):
            raise ValueError("ASVS source digest mismatch")
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        official = {row["req_id"].replace("V", "v5.0.0-", 1) for row in rows}
        if not accepted <= official or len(official) != upstream["totalRequirements"]:
            raise ValueError("ASVS source requirement mismatch")
    seen = set()
    for control in mapping["controls"]:
        if control["id"] in seen or control["state"] not in {
            "mapped",
            "partial",
            "gap",
            "deployment-owned",
        }:
            raise ValueError("invalid security control")
        seen.add(control["id"])
        if not control["asvs"] or not set(control["asvs"]) <= accepted:
            raise ValueError("unknown ASVS requirement")
        for reference in control["references"]:
            path = root / safe_path(reference)
            if not path.is_file() or path.is_symlink():
                raise ValueError("missing security reference")
        for test in control.get("tests", []):
            path = root / safe_path(test["path"])
            tree = ast.parse(path.read_text())
            classes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == test["class"]
            ]
            if len(classes) != 1 or test["method"] not in {
                node.name
                for node in classes[0].body
                if isinstance(node, ast.FunctionDef)
            }:
                raise ValueError("missing mapped test declaration")
    return {
        "validation": "references-only",
        "controls": len(seen),
        "selectedRequirements": len(accepted),
        "states": {
            state: sum(c["state"] == state for c in mapping["controls"])
            for state in ("mapped", "partial", "gap", "deployment-owned")
        },
        "asvsLevelClaim": None,
        "runtimeTestsExecuted": False,
        "upstreamVerified": verify_upstream,
    }


def tracked_paths() -> list[str]:
    data = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    )
    return sorted({path.decode() for path in data.split(b"\0") if path})


def source_paths(files: list[str]) -> list[str]:
    return [
        path
        for path in files
        if path.startswith(SOURCE_ROOTS)
        and Path(path).suffix in SOURCE_SUFFIXES
        and not any(part in {"tests", "test", "testdata"} for part in Path(path).parts)
        and not re.search(
            r"(?:_tests?\.(?:go|rs|py)|\.(?:test|spec)\.[cm]?[jt]sx?)$", path
        )
    ]


def scan_environment(inherited: dict | None = None) -> dict:
    inherited = os.environ if inherited is None else inherited
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "SYSTEMROOT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    }
    return {
        **{key: value for key, value in inherited.items() if key in allowed},
        "SEMGREP_SEND_METRICS": "off",
        "SEMGREP_ENABLE_VERSION_CHECK": "0",
    }


def scanner_run(
    argv: list[str],
    private: Path,
    name: str,
    normalizer,
    *,
    report_file: Path | None = None,
) -> dict:
    try:
        with (
            (private / f"{name}.stdout").open("w") as out,
            (private / f"{name}.stderr").open("w") as err,
        ):
            result = subprocess.run(
                argv,
                cwd=ROOT,
                stdout=out,
                stderr=err,
                timeout=600,
                env=scan_environment(),
                check=False,
            )
        data = json.loads((report_file or private / f"{name}.stdout").read_text())
        return normalizer(data, result.returncode)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        return {"status": "error", "errorType": type(error).__name__, "findings": []}


def version(binary: Path, name: str, expected: str) -> None:
    command = "version" if name == "gitleaks" else "--version"
    result = subprocess.run(
        [str(binary), command],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=scan_environment(),
    )
    if result.returncode or not re.search(
        r"(?<![0-9.])" + re.escape(expected) + r"(?![0-9.])",
        result.stdout + result.stderr,
    ):
        raise ValueError("scanner version mismatch")


def audit(out: Path, binaries: Path, semgrep: Path) -> dict:
    if out.is_symlink() or out.exists() or out.resolve().is_relative_to(ROOT):
        raise ValueError("evidence destination must be new")
    out.mkdir(parents=True, mode=0o700)
    config = json.loads((ROOT / "security/tools.json").read_text())["tools"]
    files = tracked_paths()
    aliases = []
    for path in list(files):
        source = ROOT / path
        if source.is_symlink():
            target = source.resolve(strict=True)
            if (
                path
                not in {
                    ".agents/skills/integrate-auth",
                    ".agents/skills/integrate-core",
                }
                or not target.is_dir()
                or not target.is_relative_to(ROOT / "skills")
            ):
                raise ValueError("linked tracked input is unsupported")
            aliases.append(
                {
                    "path": path,
                    "target": target.relative_to(ROOT).as_posix(),
                    "reason": "directory alias; canonical target files are included",
                }
            )
            files.remove(path)
    manifests = [
        path
        for path in files
        if Path(path).name in LOCK_NAMES - {"go.sum"} and "/templates/" not in path
    ]
    sources = source_paths(files)
    report = {
        "schemaVersion": 1,
        "kind": "source-security-baseline",
        "startedAt": timestamp(),
        "sourceCommit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "sourceDirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "tools": {name: tool["version"] for name, tool in config.items()},
        "scope": {
            "dependencyInputs": manifests,
            "staticInputs": sources,
            "directoryAliases": aliases,
            "secrets": ["all-local-git-refs", "current-tracked-and-unignored-files"],
            "templateDependencies": "resolved source manifests; template lockfiles not independently scanned",
            "mavenLimit": "Resolver-inferred dependencies, not the actual built classpath; Maven transitive test dependencies are not covered",
            "goLimit": "Module dependencies only; Go compiler and standard library vulnerabilities are not assessed",
            "staticLimit": "local intrafile rules only; no whole-program authorization proof",
            "externalAudit": False,
            "productionAssessment": False,
        },
        "inputHashes": {
            path: digest(ROOT / path)
            for path in sorted(
                set(
                    manifests
                    + sources
                    + [
                        p
                        for p in files
                        if p.startswith("security/") and (ROOT / p).is_file()
                    ]
                )
            )
        },
        "checks": {},
    }
    with tempfile.TemporaryDirectory(prefix="feature-security-private-") as temporary:
        private = Path(temporary)
        os.chmod(private, 0o700)
        try:
            report["mapping"] = mapping_check()
            for name, binary in (
                ("osv-scanner", binaries / "osv-scanner"),
                ("gitleaks", binaries / "gitleaks"),
                ("semgrep", semgrep),
            ):
                version(binary, name, config[name]["version"])
            osv = [
                str(binaries / "osv-scanner"),
                "scan",
                "source",
                "--format",
                "json",
                "--all-packages",
                "--no-ignore",
            ]
            for path in manifests:
                osv.extend(["--lockfile", path])
            report["checks"]["dependencies"] = scanner_run(
                osv, private, "dependencies", normalize_osv
            )
            dependency = report["checks"]["dependencies"]
            if not {"PyPI", "Go", "Maven", "crates.io", "npm"} <= set(
                dependency.get("ecosystems", [])
            ):
                dependency["status"] = "error"
                dependency["coverageError"] = "missing-required-ecosystem"
            static = [
                str(semgrep),
                "scan",
                "--config",
                "security/semgrep-rules.json",
                "--metrics=off",
                "--disable-version-check",
                "--strict",
                "--error",
                "--json",
                "--no-git-ignore",
                *sources,
            ]
            report["checks"]["static"] = scanner_run(
                static, private, "static", normalize_semgrep
            )
            if set(report["checks"]["static"].get("scannedPaths", [])) != set(sources):
                report["checks"]["static"]["status"] = "error"
                report["checks"]["static"]["coverageError"] = (
                    "source-file-coverage-mismatch"
                )
            history_report = private / "history.json"
            common = [
                "--config=security/gitleaks.toml",
                "--redact=100",
                "--no-banner",
                "--report-format=json",
            ]
            history = scanner_run(
                [
                    str(binaries / "gitleaks"),
                    "git",
                    "--log-opts=--all",
                    *common,
                    f"--report-path={history_report}",
                    ".",
                ],
                private,
                "history",
                normalize_gitleaks,
                report_file=history_report,
            )
            mirror = private / "tracked"
            mirror.mkdir()
            for path in files:
                target = mirror / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, target)
            tree_report = private / "tree.json"

            def normalize_tree(data, code):
                for row in data:
                    row["File"] = safe_path(row["File"], mirror)
                return normalize_gitleaks(data, code)

            tree = scanner_run(
                [
                    str(binaries / "gitleaks"),
                    "dir",
                    *common,
                    f"--report-path={tree_report}",
                    str(mirror),
                ],
                private,
                "tree",
                normalize_tree,
                report_file=tree_report,
            )
            report["checks"]["secrets"] = {
                "status": "error"
                if "error" in {history["status"], tree["status"]}
                else "findings"
                if "findings" in {history["status"], tree["status"]}
                else "passed",
                "history": history,
                "currentTree": tree,
                "filesScanned": len(files),
                "findings": history.get("findings", []) + tree.get("findings", []),
            }
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            report["setupError"] = type(error).__name__
    report["status"] = overall_status(report["checks"])
    report["finishedAt"] = timestamp()
    inventory = report["checks"].get("dependencies", {}).get("inventory", [])
    (out / "dependencies.cdx.json").write_text(
        json.dumps(cyclonedx(inventory), indent=2) + "\n"
    )
    (out / "security-report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Source security baseline",
        "",
        f"Commit: `{report['sourceCommit']}`; dirty: `{report['sourceDirty']}`.",
        f"Finished: {report['finishedAt']}; gate: **{report['status']}**.",
        "",
        "This is scoped automated evidence, not ASVS certification, an external audit or a production assessment.",
        "",
        "| Check | Status | Findings |",
        "| --- | --- | --- |",
    ]
    for name in sorted(REQUIRED):
        check = report["checks"].get(name, {})
        lines.append(
            f"| {name} | {check.get('status', 'not-run')} | {len(check.get('findings', []))} |"
        )
    lines += [
        "",
        "Dependency finding counts are manifest occurrences; the JSON's uniqueFindingCount deduplicates advisory/ecosystem/package/version combinations.",
        "The JSON report records exact inputs, hashes, coverage, tool versions and limitations.",
        "The CycloneDX file is an inventory of scanned dependency declarations, not a complete deployed-system SBOM.",
        "Raw scanner reports, source snippets, secret values and environment variables are not published.",
    ]
    (out / "security-report.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "sourceCommit": report["sourceCommit"],
                "checks": {
                    name: {
                        "status": value["status"],
                        "findings": len(value.get("findings", [])),
                    }
                    for name, value in report["checks"].items()
                },
            }
        )
    )
    return report


def record_setup_failure(out: Path) -> None:
    if (out / "security-report.json").is_file():
        return
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {
        "schemaVersion": 1,
        "kind": "source-security-baseline",
        "status": "error",
        "sourceCommit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "finishedAt": timestamp(),
        "setupError": "prior-step-failed-before-complete-evidence",
        "checks": {
            name: {"status": "error", "executed": False} for name in sorted(REQUIRED)
        },
    }
    (out / "security-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "security-report.md").write_text(
        "# Source security baseline\n\nGate: **error**. Scanner setup or evidence generation did not finish; no clean-security claim is supported.\n"
    )
    (out / "dependencies.cdx.json").write_text(
        json.dumps(cyclonedx([]), indent=2) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument(
        "--semgrep", type=Path, default=ROOT / "security/.venv/bin/semgrep"
    )
    parser.add_argument("--check-mapping", action="store_true")
    parser.add_argument("--record-setup-failure", action="store_true")
    parser.add_argument("--verify-asvs-upstream", action="store_true")
    args = parser.parse_args()
    if args.record_setup_failure and args.out:
        record_setup_failure(args.out)
    elif args.check_mapping:
        print(json.dumps(mapping_check(verify_upstream=args.verify_asvs_upstream)))
    elif args.out and args.bin_dir:
        raise SystemExit(
            0
            if audit(args.out, args.bin_dir, args.semgrep)["status"] == "passed"
            else 1
        )
    else:
        parser.error("provide --check-mapping or both --out and --bin-dir")
