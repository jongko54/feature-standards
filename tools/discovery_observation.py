"""Validate reviewed observations; never infer reading or SDK use from a mention."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "evals/discovery/prompts.json"
STAGES = ["unbranded", "named", "supplied_url", "integration"]
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
FIELDS = {
    "id",
    "provider",
    "interface",
    "requestedModel",
    "observedModel",
    "caseId",
    "stage",
    "sessionId",
    "freshSession",
    "startedAt",
    "outcome",
    "promptSha256",
    "transcriptSha256",
    "review",
}
REVIEW_FIELDS = {
    "status",
    "mentioned",
    "recommended",
    "sourceUrls",
    "readEvidence",
    "integrationEvidence",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 2_000_000, "input exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def load_protocol(path):
    protocol = read_json(path)
    require(
        isinstance(protocol, dict)
        and protocol.get("schemaVersion") == 1
        and protocol.get("protocol") == "web-discovery-v1",
        "unsupported protocol",
    )
    require(protocol.get("stages") == STAGES, "invalid stages")
    cases = protocol.get("cases")
    require(isinstance(cases, list) and 1 <= len(cases) <= 20, "invalid cases")
    ids = set()
    for case in cases:
        require(
            isinstance(case, dict) and set(case) == {"id", "language", "prompts"},
            "invalid case",
        )
        require(
            isinstance(case["id"], str)
            and re.fullmatch(r"[a-z0-9-]+", case["id"])
            and case["id"] not in ids,
            "duplicate or invalid case id",
        )
        ids.add(case["id"])
        require(case["language"] in {"ko", "en"}, "unsupported case language")
        prompts = case["prompts"]
        require(
            isinstance(prompts, dict) and set(prompts) == set(STAGES),
            "missing stage prompts",
        )
        for text in prompts.values():
            require(
                isinstance(text, str) and 1 <= len(text) <= 10_000, "invalid prompt"
            )
        require(
            not re.search(
                r"feature[-_ ]standards|jongko54|ugauga|https?://",
                prompts["unbranded"],
                re.IGNORECASE,
            ),
            "unbranded prompt leaks a target hint",
        )
    return protocol


def official_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
        ):
            return False
        host = parsed.hostname
        parts = unquote(parsed.path).strip("/").split("/")
        if any(
            part in {".", ".."} or "\\" in part or any(ord(char) < 32 for char in part)
            for part in parts
        ):
            return False
        if host in {"github.com", "raw.githubusercontent.com"}:
            return parts[:2] == ["jongko54", "feature-standards"]
        if host in {"www.npmjs.com", "npmjs.com"}:
            return parts == ["package", "feature-standards"] or parts in [
                ["package", "@ugauga", name]
                for name in (
                    "feature-standards-core",
                    "feature-standards-react-auth",
                    "create-feature-auth",
                )
            ]
        if host == "pypi.org":
            return (
                len(parts) >= 2
                and parts[0] == "project"
                and parts[1]
                in {"feature-standards-core", "feature-standards-python-auth"}
            )
        if host == "crates.io":
            return (
                len(parts) >= 2
                and parts[0] == "crates"
                and parts[1] in {"feature-standards-core", "feature-standards-auth"}
            )
        if host == "central.sonatype.com":
            return (
                len(parts) >= 3
                and parts[:2] == ["artifact", "io.github.jongko54"]
                and parts[2] in {"java-spring-auth", "feature-standards-core"}
            )
        if host == "pkg.go.dev":
            return parts[:3] == ["github.com", "jongko54", "feature-standards"]
    except ValueError:
        return False
    return False


def validate_record(row, cases):
    require(
        isinstance(row, dict) and set(row) == FIELDS, "unknown or missing record fields"
    )
    for key in ("id", "provider", "interface", "requestedModel", "caseId", "sessionId"):
        require(
            isinstance(row[key], str) and 1 <= len(row[key]) <= 200,
            "invalid record identity",
        )
    require(
        row["observedModel"] is None or isinstance(row["observedModel"], str),
        "invalid observed model",
    )
    require(type(row["freshSession"]) is bool, "freshSession must be boolean")
    require(row["caseId"] in cases and row["stage"] in STAGES, "unknown case or stage")
    require(
        row["outcome"] in {"completed", "blocked", "timeout", "error"},
        "unknown outcome",
    )
    try:
        started = datetime.fromisoformat(row["startedAt"])
        require(started.tzinfo is not None, "timestamp needs a timezone")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid observation timestamp") from None
    prompt = cases[row["caseId"]]["prompts"][row["stage"]]
    require(
        row["promptSha256"] == hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt hash mismatch",
    )
    require(
        row["transcriptSha256"] is None or digest(row["transcriptSha256"]),
        "invalid transcript hash",
    )
    review = row["review"]
    if row["outcome"] != "completed":
        require(review is None, "noncompleted record cannot have a result review")
        return
    require(
        digest(row["transcriptSha256"]), "completed observation needs a transcript hash"
    )
    require(
        isinstance(review, dict) and review.get("status") in {"pending", "reviewed"},
        "invalid review",
    )
    if review["status"] == "pending":
        require(set(review) == {"status"}, "pending review cannot assert results")
        return
    require(set(review) == REVIEW_FIELDS, "invalid reviewed result fields")
    require(
        type(review["mentioned"]) is bool and type(review["recommended"]) is bool,
        "invalid review flags",
    )
    require(
        isinstance(review["sourceUrls"], list)
        and len(review["sourceUrls"]) <= 40
        and all(
            isinstance(url, str) and len(url) <= 2000 for url in review["sourceUrls"]
        ),
        "invalid source URLs",
    )
    require(
        not review["recommended"] or review["mentioned"],
        "recommendation requires a target mention",
    )
    evidence = review["readEvidence"]
    if evidence is not None:
        require(
            isinstance(evidence, dict)
            and set(evidence) == {"kind", "sourceUrl", "sha256"}
            and evidence["kind"] == "tool-output"
            and official_url(evidence["sourceUrl"])
            and digest(evidence["sha256"]),
            "reading requires reviewed official tool-output evidence",
        )
    integration = review["integrationEvidence"]
    if integration is not None:
        require(
            row["stage"] == "integration", "SDK execution belongs to integration stage"
        )
        require(
            isinstance(integration, dict)
            and set(integration)
            == {
                "httpPassed",
                "httpReceiptSha256",
                "originEvidenceSha256",
                "appSourceSha256",
            }
            and integration["httpPassed"] is True
            and all(
                digest(integration[key])
                for key in (
                    "httpReceiptSha256",
                    "originEvidenceSha256",
                    "appSourceSha256",
                )
            ),
            "SDK connection requires HTTP, dependency origin and app source evidence",
        )


def summarize(records, protocol):
    require(
        isinstance(records, list) and len(records) <= 2000, "invalid observation list"
    )
    cases = {case["id"]: case for case in protocol["cases"]}
    seen_ids, seen_sessions, groups = set(), set(), {}
    for row in records:
        validate_record(row, cases)
        session = (row["provider"], row["interface"], row["sessionId"])
        require(row["id"] not in seen_ids, "duplicate record id")
        require(
            session not in seen_sessions,
            "duplicate session; followups are not independent trials",
        )
        seen_ids.add(row["id"])
        seen_sessions.add(session)
        key = tuple(
            row[k]
            for k in ("provider", "interface", "requestedModel", "caseId", "stage")
        )
        if key not in groups:
            groups[key] = {
                **dict(
                    zip(
                        ("provider", "interface", "requestedModel", "caseId", "stage"),
                        key,
                    )
                ),
                **dict.fromkeys(
                    (
                        "attempts",
                        "completed",
                        "blocked",
                        "timeout",
                        "error",
                        "nonIndependent",
                        "pendingReview",
                        "reviewedIndependentCompleted",
                        "mentions",
                        "officialRecommendations",
                        "documentOutputs",
                        "sdkConnections",
                    ),
                    0,
                ),
            }
        group = groups[key]
        group["attempts"] += 1
        group[row["outcome"]] += 1
        group["nonIndependent"] += not row["freshSession"]
        review = row["review"]
        if row["outcome"] != "completed":
            continue
        if review["status"] == "pending":
            group["pendingReview"] += 1
            continue
        if not row["freshSession"]:
            continue
        group["reviewedIndependentCompleted"] += 1
        group["mentions"] += review["mentioned"]
        group["officialRecommendations"] += review["recommended"] and any(
            map(official_url, review["sourceUrls"])
        )
        group["documentOutputs"] += review["readEvidence"] is not None
        group["sdkConnections"] += review["integrationEvidence"] is not None
    result = [groups[key] for key in sorted(groups)]
    for group in result:
        denominator = group["reviewedIndependentCompleted"]
        group["officialRecommendationRate"] = (
            group["officialRecommendations"] / denominator if denominator else None
        )
    return {
        "schemaVersion": 1,
        "protocol": protocol["protocol"],
        "records": len(records),
        "groups": result,
        "unobservedStages": [
            stage for stage in STAGES if not any(r["stage"] == stage for r in records)
        ],
        "limits": [
            "These are reviewed observations, not a market adoption rate or a model population estimate.",
            "Evidence hashes identify reviewer-retained artifacts; this aggregator does not fetch or attest their contents.",
            "A tool output does not establish model understanding. A recommendation does not establish execution.",
            "Provider, interface, requested model, prompt case and stage remain separate; null is not zero.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    commands = parser.add_subparsers(dest="command", required=True)
    prompt = commands.add_parser("prompt")
    prompt.add_argument("--case", required=True)
    prompt.add_argument("--stage", choices=STAGES, required=True)
    report = commands.add_parser("summarize")
    report.add_argument("--records", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        protocol = load_protocol(args.protocol)
        if args.command == "prompt":
            cases = {case["id"]: case for case in protocol["cases"]}
            require(args.case in cases, "unknown case")
            print(cases[args.case]["prompts"][args.stage])
        else:
            print(
                json.dumps(
                    summarize(read_json(args.records), protocol),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    except (ValueError, OSError) as error:
        print(f"discovery-observation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
