"""Post-run document/context output evidence, separate from original reading metrics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

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
        f"docs/ai-briefs/{stack}.md",
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


CONTEXT_PROFILES = {
    "auth": "browser-session-v1",
    "authorization": "rbac-v1",
    "listing": "offset-list-v1",
}
CATALOG_LIMITS = [
    "Complete selected context data was observed in tool output. This does not prove CLI execution, model consumption, understanding, skill activation or runtime API reuse; echoing the data can also produce this evidence.",
    "This separate post-run audit supplements strict CLI argv evidence and never overwrites original metrics. Failed compound commands can contain valid earlier context output.",
    "Only complete JSON objects matching the captured 0.4.0 package, stack, feature/profile, source commit and packaged document-reference hashes are counted. Quoted JSON strings and partial/malformed objects are excluded.",
    "Counts are output events, deduplicated within each mode/feature and by terminal event ID. Unique selections ignore full/compact rendering mode. Reference matching checks captured metadata, not command origin.",
]


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def _invalid_json_constant(_value):
    raise ValueError("non-json-constant")


def _json_objects(output):
    decoder = json.JSONDecoder(
        object_pairs_hook=_unique_json_object, parse_constant=_invalid_json_constant
    )
    cursor = 0
    while cursor < len(output):
        if output[cursor] not in '{["':
            cursor += 1
            continue
        try:
            value, end = decoder.raw_decode(output, cursor)
        except (ValueError, RecursionError):
            cursor += 1
            continue
        cursor = end
        # Consume strings/arrays as units, so an escaped JSON example is not
        # reinterpreted by scanning its inner braces as another object.
        if isinstance(value, dict):
            yield value


def _catalog_provenance(snapshot):
    document = _document(snapshot / "catalog/package/snapshot/provenance.json")
    if document is None:
        return None
    try:
        value = json.loads(document[1], object_pairs_hook=_unique_json_object)
    except ValueError:
        return None
    if (
        not isinstance(value, dict)
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
        or not re.fullmatch(r"[a-f0-9]{40,64}", str(value.get("sourceCommit", "")))
        or value.get("sourceDirty") is not False
        or value.get("snapshotDirty") is not False
        or not isinstance(value.get("files"), dict)
        or not value["files"]
    ):
        return None
    return value


def _context_reference(value, files):
    if not isinstance(value, dict) or not isinstance(value.get("readPath"), str):
        return False
    path = value["readPath"]
    if not path.startswith("/") or "/snapshot/" not in path:
        return False
    relative = path.rsplit("/snapshot/", 1)[1]
    canonical = PurePosixPath(relative)
    if (
        not relative
        or canonical.is_absolute()
        or ".." in canonical.parts
        or str(canonical) != relative
        or "\\" in relative
    ):
        return False
    record = files.get(relative)
    if (
        not isinstance(record, dict)
        or record.get("sourceModified") is not False
        or value.get("sourceModified") is not False
        or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256", "")))
        or value["sha256"] != record.get("sha256")
    ):
        return False
    return (
        value.get("sourcePath", relative) == relative
        and value.get("packagePath", "snapshot/" + relative) == "snapshot/" + relative
    )


def _context_selection(value, provenance, stack):
    feature = value.get("feature")
    if (
        type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
        or value.get("package") != {"name": "feature-standards", "version": "0.4.0"}
        or not isinstance(feature, str)
        or feature not in CONTEXT_PROFILES
        or value.get("profile") != CONTEXT_PROFILES[feature]
        or not isinstance(value.get("stack"), dict)
        or value["stack"].get("id") != stack
        or not isinstance(value.get("optionalAddons"), list)
        or not isinstance(value.get("limits"), list)
    ):
        return None
    files = provenance["files"]
    if value.get("mode") == "compact":
        source, references, contract = (
            value.get("source"),
            value.get("readFirst"),
            value.get("contract"),
        )
        required = {"specification", "openapi", "scenarios", "profileGuide", "manifest"}
        if feature != "auth":
            required.add("releaseReceipt")
        if (
            value.get("readOnly") is not True
            or not isinstance(source, dict)
            or source.get("required") is not True
            or source.get("commit") != provenance["sourceCommit"]
            or source.get("sourceDirty") is not False
            or source.get("snapshotDirty") is not False
            or not isinstance(source.get("entrypoints"), list)
            or not isinstance(value.get("packageMetadata"), dict)
            or not isinstance(value.get("fullContext"), dict)
            or value["fullContext"].get("executed") is not False
            or not isinstance(references, list)
            or len(references) != 3
            or not isinstance(contract, dict)
            or not required.issubset(contract)
        ):
            return None
        refs = references + list(contract.values())
        for group in ("relatedSpecifications", "migrations"):
            if not isinstance(value.get(group), list):
                return None
            refs += value[group]
        return (
            ("compact_context", feature)
            if all(_context_reference(ref, files) for ref in refs)
            else None
        )
    captured, checkout, documents = (
        value.get("provenance"),
        value.get("sourceCheckout"),
        value.get("packagedDocuments"),
    )
    required = {
        "manifest",
        "specification",
        "openapi",
        "scenarios",
        "profileGuide",
        "apiGuide",
        "consumerGuide",
        "integrationSkill",
        "integrationGuide",
        "relatedSpecifications",
        "migrations",
        "profileReferences",
        "generatorGuide" if feature == "auth" else "releaseReceipt",
    }
    if (
        "mode" in value
        or not isinstance(captured, dict)
        or captured.get("sourceCommit") != provenance["sourceCommit"]
        or captured.get("sourceDirty") is not False
        or captured.get("snapshotDirty") is not False
        or not isinstance(checkout, dict)
        or checkout.get("required") is not True
        or any(
            not isinstance(checkout.get(key), list)
            for key in ("entrypoints", "install", "checks")
        )
        or not isinstance(checkout.get("environment"), dict)
        or not isinstance(documents, dict)
        or not required.issubset(documents)
    ):
        return None
    refs = []
    for reference in documents.values():
        refs.extend(reference if isinstance(reference, list) else [reference])
    return (
        ("full_context", feature)
        if all(_context_reference(ref, files) for ref in refs)
        else None
    )


def catalog_output_evidence(trace: Path, snapshot: Path, stack: str) -> dict:
    """Observe matching context data in output, without attributing execution."""
    if stack not in AUTH_ROOTS:
        raise ValueError("unsupported-stack")
    provenance = _catalog_provenance(snapshot.absolute())
    result = {
        "evidence_kind": "complete_selected_context_output_observed",
        "full_context": {"successful": 0, "failed": 0, "unknown": 0},
        "compact_context": {"successful": 0, "failed": 0, "unknown": 0},
        "by_feature": {
            feature: {
                mode: {"successful": 0, "failed": 0, "unknown": 0}
                for mode in ("full_context", "compact_context")
            }
            for feature in CONTEXT_PROFILES
        },
        "unique_selected_contexts": 0,
        "snapshot_provenance_available": provenance is not None,
        "limits": list(CATALOG_LIMITS),
    }
    if provenance is None:
        return result
    seen, selections = set(), set()
    with trace.open("rb") as stream:
        for line in stream:
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, ValueError):
                continue
            if not isinstance(event, dict):
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
            outcome = (
                "successful"
                if type(code) is int and code == 0 and status == "completed"
                else "failed"
                if (type(code) is int and code != 0) or status == "failed"
                else "unknown"
            )
            contexts = {
                selected
                for value in _json_objects(output)
                if (selected := _context_selection(value, provenance, stack))
                is not None
            }
            for mode in {mode for mode, _ in contexts}:
                result[mode][outcome] += 1
            for mode, feature in contexts:
                result["by_feature"][feature][mode][outcome] += 1
                selections.add(feature)
    result["unique_selected_contexts"] = len(selections)
    return result
