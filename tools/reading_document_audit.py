"""Post-run whole-document output evidence, separate from original reading metrics."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

MAX_DOCUMENT_BYTES = 2_000_000
AUTH_ROOTS = {
    "python": "python-fastapi",
    "go": "go-net-http",
    "java": "java-spring",
    "rust": "rust-axum",
}
CONSUMER_SOURCES = {
    "python": ["examples/consumer-python-react/app.py", "examples/core-python/app.py"],
    "go": ["examples/consumer-go/main.go", "examples/core-go/main.go"],
    "java": [
        "examples/consumer-java/src/main/java/dev/featurestandards/examples/ConsumerApplication.java",
        *[
            "examples/core-java/src/main/java/dev/featurestandards/examples/core/"
            + name
            + ".java"
            for name in (
                "CoreController",
                "CoreApplication",
                "MembershipProvider",
                "DocumentProvider",
            )
        ],
    ],
    "rust": [
        f"examples/{kind}-rust/src/{name}.rs"
        for kind in ("consumer", "core")
        for name in ("main", "lib")
    ],
}
LIMITS = [
    "Whole-document output inclusion does not prove model consumption, understanding, skill activation, CLI execution or runtime API reuse.",
    "This is a separate post-run audit. It does not replace or correct original automated reading counts, outcomes, timing or token metrics.",
    "Only nonempty strict UTF-8 files smaller than 2000000 bytes in a fixed stack-specific whitelist are candidates; symlinks and partial or normalized matches are excluded.",
    "Identical source and packaged bytes share one content hash; output alone cannot identify which identical path emitted the content.",
    "A failed compound command can emit complete earlier documents. Successful, failed and unknown command outcomes are counted separately.",
]


def _whitelist(stack):
    consumer = "consumer-python-react" if stack == "python" else "consumer-" + stack
    return [
        "README.md",
        f"implementations/{AUTH_ROOTS[stack]}/README.md",
        f"implementations/{AUTH_ROOTS[stack]}/PACKAGE.md",
        f"libraries/{stack}/README.md",
        f"examples/{consumer}/README.md",
        f"examples/core-{stack}/README.md",
        "docs/core-standards.md",
        *[
            f"features/{feature}/specification.md"
            for feature in ("auth", "authorization", "listing")
        ],
        "skills/integrate-auth/SKILL.md",
        "skills/integrate-core/SKILL.md",
        *CONSUMER_SOURCES[stack],
    ]


def _document(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        return None
    try:
        original = path.lstat()
        if (
            not stat.S_ISREG(original.st_mode)
            or not 0 < original.st_size < MAX_DOCUMENT_BYTES
        ):
            return None
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not 0 < metadata.st_size < MAX_DOCUMENT_BYTES
                or (original.st_dev, original.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                return None
            data = source.read(MAX_DOCUMENT_BYTES)
        if not 0 < len(data) < MAX_DOCUMENT_BYTES:
            return None
        return data, data.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def document_output_evidence(trace: Path, snapshot: Path, stack: str) -> dict:
    if stack not in AUTH_ROOTS:
        raise ValueError("unsupported-stack")
    snapshot = snapshot.absolute()
    contents = {}
    for source_path in _whitelist(stack):
        for relative in (source_path, "catalog/package/snapshot/" + source_path):
            document = _document(snapshot / relative)
            if document is not None:
                data, text = document
                digest = hashlib.sha256(data).hexdigest()
                entry = contents.setdefault(digest, {"text": text, "paths": []})
                entry["paths"].append(relative)
    result = {
        "evidence_kind": "whole_document_output_observed",
        "documents": [],
        "events_with_whole_document_output": 0,
        "content_event_matches": 0,
        "candidate_content_count": len(contents),
        "malformed_events": 0,
        "limits": list(LIMITS),
    }
    matched, seen = {}, set()
    with trace.open("rb") as stream:
        for line in stream:
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, ValueError):
                result["malformed_events"] += 1
                continue
            if not isinstance(event, dict):
                result["malformed_events"] += 1
                continue
            item = event.get("item")
            if (
                event.get("type") != "item.completed"
                or not isinstance(item, dict)
                or item.get("type") != "command_execution"
            ):
                continue
            identifier = item.get("id")
            if type(identifier) in {str, int}:
                key = (str(event.get("thread_id")), type(identifier), identifier)
                if key in seen:
                    continue
                seen.add(key)
            output = item.get("aggregated_output")
            if not isinstance(output, str):
                continue
            code, status = item.get("exit_code"), item.get("status", "completed")
            outcome = "unknown"
            if type(code) is int and code == 0 and status == "completed":
                outcome = "successful"
            elif (type(code) is int and code != 0) or status == "failed":
                outcome = "failed"
            any_match = False
            for digest, content in contents.items():
                if content["text"] in output:
                    any_match = True
                    entry = matched.setdefault(
                        digest,
                        {
                            "sha256": digest,
                            "paths": sorted(content["paths"]),
                            "output_event_counts": {
                                "successful": 0,
                                "failed": 0,
                                "unknown": 0,
                            },
                        },
                    )
                    entry["output_event_counts"][outcome] += 1
                    result["content_event_matches"] += 1
            result["events_with_whole_document_output"] += any_match
    result["documents"] = [matched[digest] for digest in sorted(matched)]
    return result
