"""Bounded multi-model observations of choices in a supplied source checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import auth_eval
import choice_tasks
import core_discovery_eval as discovery
import core_eval
import core_reading_eval as reading
import reading_trace
import source_evidence
from auth_eval import EvalError

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ("auth", "authorization", "listing")
CLASSES = (
    "library_connected",
    "transitive_library_connected",
    "direct_independent",
    "copied_runtime_source",
    "mixed",
    "uncertain",
)
CONNECTED = frozenset(CLASSES[:2])
SOURCE_SUFFIXES = frozenset(
    (".py", ".go", ".java", ".rs", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx")
)
MANIFEST_SUFFIXES = frozenset(
    (".json", ".toml", ".xml", ".yaml", ".yml", ".gradle", ".kts", ".properties")
)
MANIFEST_NAMES = frozenset(
    ("go.mod", "go.sum", "Cargo.lock", "Makefile", "requirements.txt", "uv.lock")
)
MAX_SOURCE_BYTES = 2_000_000
LIMITS = [
    "These are choices in an already supplied repository and local packed candidate, not internet discovery or external adoption.",
    "The default 32 sessions have only two repeats per requested-model/backend/task cell. Documents and notes are fixed similar variants, not independent task families or a population sample.",
    "All attempts remain visible. Prework infrastructure rejection, supported starts, unknown starts, reviewable sources and working reviewed reuse have separate denominators.",
    "Unreviewed or uncertain choices remain unknown. Rates are null without eligible reviews; confirmed lower bounds include unknown choices in the supported-start denominator.",
    "Overall reuse rates require at least one complete three-feature review of a supported attempt; partial feature classifications remain separate while the complete choice is unknown.",
    "Source-reviewed route connections, static hints, exact file copies and independent HTTP results are different evidence. Source review does not prove runtime causality, internal reasoning or originality.",
    "This measures package/API reuse, not document influence or adoption of the standards' ideas. An independent implementation may still follow the supplied contracts or documents.",
    "Whole-file copy observations omit caches, tests and files of 200 bytes or less; they do not rule out partial copying.",
    "Requested and observed model identities, usage and order are retained. Server weights, shared dependency/prompt caches and host load are not controlled.",
    "Do not pool this protocol with the old four discovery observations, instructed reading trials, availability probes or other sources/tasks/runners.",
]


def schedule(models, stacks, scenarios, repeats):
    pairs = [(model, scenario) for scenario in scenarios for model in models]
    result = []
    for repeat in range(repeats):
        for index, stack in enumerate(stacks):
            rotation = index % len(pairs)
            order = pairs[rotation:] + pairs[:rotation]
            if repeat % 2:
                order = order[::-1]
            result.extend(
                (model, stack, scenario, repeat + 1) for model, scenario in order
            )
    return result


def started_state(trace, stderr=""):
    """Classify observable work, never model acceptance from successful grading."""
    started = completed = activity = terminal = False
    messages = []
    if trace.exists():
        for line in trace.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type", "")
            started |= kind == "turn.started"
            completed |= kind == "turn.completed"
            activity |= (
                isinstance(kind, str)
                and kind.startswith("item.")
                and isinstance(event.get("item"), dict)
            )
            if isinstance(kind, str) and kind in {"error", "turn.failed"}:
                terminal = True
                messages.append(
                    json.dumps(
                        {
                            key: event.get(key)
                            for key in ("message", "error", "code", "status")
                        }
                    )
                )
    stderr_messages = [
        line
        for line in stderr.splitlines()
        if not completed
        and re.search(
            r"\b(?:error|failed|exceeded|reached|unauthorized)\b", line, re.IGNORECASE
        )
    ]
    patterns = (
        (
            r"not logged in|\b401\b|\bunauthorized\b|not authorized|invalid_api_key|authentication[_ -](?:failed|required)",
            "cli-authentication-failed",
        ),
        (r"(?:rate|usage)[_ -]limit|\b429\b", "cli-rate-limited"),
        (
            r"model[^\n]*(?:not[_ -]found|not[_ -]supported|does[_ -]not[_ -]exist|unavailable|not[_ -]available)|unsupported[_ -]model",
            "cli-model-unavailable",
        ),
    )
    infrastructure = infrastructure_source = None
    for origin, candidates in (("trace", messages), ("stderr", stderr_messages)):
        for pattern, code in patterns:
            if any(
                re.search(pattern, message, re.IGNORECASE) for message in candidates
            ):
                infrastructure, infrastructure_source = code, origin
                break
        if infrastructure is not None:
            break
    supported = (
        True
        if completed or activity
        else False
        if infrastructure is not None
        else True
        if started
        else None
    )
    return {
        "supported_started": supported,
        "infrastructure_error": infrastructure,
        "turn_started": started,
        "turn_completed": completed,
        "item_activity": activity,
        "terminal_error": terminal,
        "terminal_reason_source": infrastructure_source
        or ("trace" if terminal else None),
    }


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise EvalError("unsafe-relative-path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise EvalError("unsafe-relative-path")
    if str(path) != value or value == ".":
        raise EvalError("unsafe-relative-path")
    return value


def file_bytes(path, maximum=5_000_000):
    auth_eval.no_symlink(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise EvalError("unsafe-or-oversized-evidence-file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        status = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_size > maximum
            or (before.st_dev, before.st_ino) != (status.st_dev, status.st_ino)
        ):
            raise EvalError("unsafe-or-oversized-evidence-file")
        data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise EvalError("unsafe-or-oversized-evidence-file")
        return data


def source_inventory(generated):
    """Publish only safe source/manifest metadata; never source text or binaries."""
    files, excluded = [], []
    try:
        auth_eval.no_symlink(generated)
        if not generated.is_dir():
            raise EvalError("missing-generated-directory")
    except (EvalError, OSError):
        return {
            "files": [],
            "excluded": [{"path": None, "reason": "unsafe-root"}],
            "reviewable": False,
        }

    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = str(path.relative_to(generated))
            try:
                safe_relative(relative)
            except EvalError:
                excluded.append({"path": None, "reason": "unsafe-path"})
                continue
            try:
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    reason = "symlink"
                elif any(
                    part in core_eval.CORE_IGNORED_PARTS
                    for part in path.relative_to(generated).parts
                ):
                    reason = "cache-or-build-output"
                elif path.name.startswith((".env", ".core-membership-")):
                    reason = "private-fixture-or-environment"
                elif stat.S_ISDIR(mode):
                    visit(path)
                    continue
                elif not stat.S_ISREG(mode):
                    reason = "nonregular"
                elif (
                    path.suffix not in SOURCE_SUFFIXES | MANIFEST_SUFFIXES
                    and path.name not in MANIFEST_NAMES
                ):
                    reason = "not-source-or-manifest"
                elif path.stat().st_size > MAX_SOURCE_BYTES:
                    reason = "oversized"
                else:
                    data = file_bytes(path, MAX_SOURCE_BYTES)
                    try:
                        text = data.decode("utf-8", errors="strict")
                    except UnicodeError:
                        reason = "non-utf8"
                    else:
                        files.append(
                            {
                                "path": relative,
                                "sha256": sha256(data),
                                "bytes": len(data),
                                "lines": len(text.splitlines()),
                            }
                        )
                        continue
            except (OSError, EvalError):
                reason = "unreadable-or-unsafe"
            excluded.append({"path": relative, "reason": reason})

    visit(generated)
    return {
        "files": files,
        "excluded": excluded,
        "reviewable": any(
            Path(item["path"]).suffix in SOURCE_SUFFIXES for item in files
        ),
    }


def _safe_code(value):
    if value is None:
        return None
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,100}", value)
        else "unclassified-error"
    )


def _review(row, reviews):
    review = (reviews or {}).get(row.get("trial"))
    if review is None:
        return None
    if review.get("original_result_sha256") != row.get("original_result_sha256"):
        raise EvalError("review-original-result-mismatch")
    return review


def _counts(rows, reviews):
    supported = [
        row
        for row in rows
        if (row.get("started_state") or {}).get("supported_started") is True
    ]
    counts = {
        "all_attempts": len(rows),
        "supported_started": len(supported),
        "start_unknown": sum(
            (row.get("started_state") or {}).get("supported_started") is None
            for row in rows
        ),
        "prework_infrastructure": sum(
            (row.get("started_state") or {}).get("supported_started") is False
            for row in rows
        ),
        "reviewable": sum(
            bool((row.get("source_inventory") or {}).get("reviewable")) for row in rows
        ),
        "supported_reviewable": sum(
            bool((row.get("source_inventory") or {}).get("reviewable"))
            for row in supported
        ),
        "reviewed_supported": 0,
        "complete_choice_reviews": 0,
        "choice_unknown": 0,
        "library_connected_full": 0,
        "partial_library_connected": 0,
        "mixed_sessions": 0,
        "verified_full_reuse": 0,
        "http_passed": sum(
            bool(row.get("original_http_passed", row.get("passed"))) for row in rows
        ),
    }
    feature_classes = {
        feature: dict.fromkeys((*CLASSES, "unreviewed"), 0) for feature in FEATURES
    }
    for row in rows:
        review = _review(row, reviews)
        classes = {
            feature: review["features"][feature]["classification"]
            if review
            else "unreviewed"
            for feature in FEATURES
        }
        for feature, classification in classes.items():
            feature_classes[feature][classification] += 1
        if (row.get("started_state") or {}).get("supported_started") is not True:
            continue
        known = review is not None and "uncertain" not in classes.values()
        counts["reviewed_supported"] += review is not None
        counts["complete_choice_reviews"] += known
        counts["choice_unknown"] += not known
        connected = sum(value in CONNECTED for value in classes.values())
        full = connected == len(FEATURES)
        counts["library_connected_full"] += full
        counts["partial_library_connected"] += 0 < connected < len(FEATURES)
        counts["mixed_sessions"] += "mixed" in classes.values()
        counts["verified_full_reuse"] += bool(
            full
            and row.get("source_unchanged") is True
            and row.get("retained_source_unchanged") is True
            and row.get("original_http_passed", row.get("passed")) is True
            and len(row.get("checks", [])) == 143
        )
    denominator = counts["supported_started"]
    eligible = bool(denominator and counts["complete_choice_reviews"])
    rates = {
        "interpretation": "confirmed-lower-bounds-over-all-supported-starts-including-unknown-choices",
        "denominator": denominator,
        "confirmed_full_reuse_lower_bound": counts["library_connected_full"]
        / denominator
        if eligible
        else None,
        "verified_full_reuse_lower_bound": counts["verified_full_reuse"] / denominator
        if eligible
        else None,
        "full_reuse_among_complete_reviews": counts["library_connected_full"]
        / counts["complete_choice_reviews"]
        if counts["complete_choice_reviews"]
        else None,
    }
    return counts | {"feature_classes": feature_classes, "rates": rates}


def summarize(rows, metadata, planned, reviews=None):
    """Summarize validated source reviews without inferring adoption from hints."""
    public = []
    for row in rows:
        review = _review(row, reviews)
        item = {
            key: row.get(key)
            for key in (
                "trial",
                "model_label",
                "requested_model",
                "stack",
                "condition",
                "repeat",
                "sequence",
                "original_http_passed",
                "source_unchanged",
                "retained_source_unchanged",
                "original_result_sha256",
                "trace_sha256",
                "analysis_sha256",
                "prompt_sha256",
                "retained_source_sha256",
                "cli_version",
                "model_selection",
                "agent_seconds",
                "elapsed_seconds",
                "started_state",
                "source_inventory",
                "analysis_complete",
                "postprocessing_errors",
            )
        }
        item.update(
            original_error_code=_safe_code(row.get("original_error_code")),
            http_assertions=len(row.get("checks", [])),
            tokens=reading.tokens(row),
            reported_models=(row.get("agent") or {}).get("models", []),
            static_reuse_hint=bool((row.get("static_reuse") or {}).get("passed")),
            feature_hints={
                "auth": bool(
                    ((row.get("feature_evidence") or {}).get("auth") or {}).get(
                        "passed"
                    )
                ),
                **{
                    feature: (row.get("feature_evidence") or {}).get(feature)
                    for feature in FEATURES[1:]
                },
            },
            exact_copy_counts={
                feature: len((row.get("copy_evidence") or {}).get(feature, []))
                for feature in ("auth", "core")
            },
            reading_counts={
                key: (row.get("reading_evidence") or {}).get(key)
                for key in (
                    "list",
                    "full_context",
                    "compact_context",
                    "doc_read_commands",
                    "doc_search_commands",
                    "unclassified_commands",
                )
            },
            choice_review=review,
            classification_source="source-review" if review else None,
            runtime_causality_proven=False,
        )
        public.append(item)
    measurements = _counts(rows, reviews)
    groups = []
    for model, stack, scenario in sorted(
        {(row["requested_model"], row["stack"], row["condition"]) for row in rows}
    ):
        selected = [
            row
            for row in rows
            if (row["requested_model"], row["stack"], row["condition"])
            == (model, stack, scenario)
        ]
        groups.append(
            {
                "requested_model": model,
                "stack": stack,
                "scenario": scenario,
                **_counts(selected, reviews),
            }
        )
    return {
        "suite": "core-choice-v1",
        **metadata,
        "limits": LIMITS,
        "planned_model_calls": planned,
        "actual_model_calls": len(rows),
        "passed": measurements["http_passed"],
        **measurements,
        "groups": groups,
        "runs": public,
    }


def _observe(row, stage, operation):
    try:
        return operation()
    except (EvalError, OSError, ValueError, TypeError, KeyError, SyntaxError) as exc:
        row["postprocessing_errors"].append(
            {"stage": stage, "error_type": type(exc).__name__}
        )
        return None


def analyze(row, retained, source, tasks, commit):
    """Add observations to a completed row without changing its HTTP outcome."""
    row["original_http_passed"] = row["passed"]
    row["original_error_code"] = row["error_code"]
    row["postprocessing_errors"] = []
    original = file_bytes(retained / "result.json")
    row["original_result_sha256"] = sha256(original)
    trace = retained / "trace.jsonl"
    trace_data = file_bytes(trace, 100_000_000) if trace.exists() else None
    row["trace_sha256"] = sha256(trace_data) if trace_data is not None else None
    stderr = ""
    if (
        row["original_error_code"]
        and not (row.get("agent") or {}).get("completed")
        and (retained / "agent.log").exists()
    ):
        stderr = file_bytes(retained / "agent.log", 100_000_000).decode(
            errors="replace"
        )
    row["started_state"] = started_state(trace, stderr)
    row["prompt_sha256"] = sha256(
        choice_tasks.prompt(row["stack"], commit, tasks, row["condition"]).encode()
    )
    snapshot = retained / "snapshot"
    generated = snapshot / "generated"
    row["retained_source_sha256"] = auth_eval.digest_hashes(
        auth_eval.fingerprint(snapshot)
    )
    row["retained_source_unchanged"] = (
        row["retained_source_sha256"] == row["source_sha256"]
    )
    row["source_inventory"] = _observe(
        row, "source-inventory", lambda: source_inventory(generated)
    )
    row["reading_evidence"] = _observe(
        row,
        "reading-evidence",
        lambda: reading_trace.reading_evidence(trace, row["stack"], snapshot),
    )
    row["copy_evidence"] = _observe(
        row, "copy-evidence", lambda: discovery.copy_evidence(generated, source)
    )
    row["static_reuse"] = _observe(
        row,
        "static-reuse",
        lambda: reading.static_reuse(generated, source, row["stack"], commit),
    )
    row["feature_evidence"] = _observe(
        row,
        "feature-evidence",
        lambda: discovery.feature_evidence(generated, source, row["stack"], commit),
    )
    if file_bytes(retained / "result.json") != original or (
        trace_data is not None and file_bytes(trace, 100_000_000) != trace_data
    ):
        raise EvalError("original-evidence-modified")
    row["analysis_complete"] = not row["postprocessing_errors"]


def trial_name(model_label, stack, scenario, repeat):
    return f"{model_label}-{stack}-{scenario}-trial-{repeat}"


def run(args, parser):
    if (
        len(args.models) != 2
        or len(set(args.models)) != len(args.models)
        or any(
            not re.fullmatch(auth_eval.MODEL_PATTERN, model) for model in args.models
        )
        or not re.fullmatch(r"[a-f0-9]{40}", args.source_commit)
        or not re.fullmatch(r"[a-f0-9]{64}", args.artifact_sha256)
        or not 1 <= args.timeout <= 600
        or len(set(args.scenarios)) != len(args.scenarios)
    ):
        parser.error(
            "Two distinct explicit models, pinned source/artifact, unique scenarios and timeout1..600 are required"
        )
    if shutil.which("codex") is None:
        parser.error("Codex CLI is required")
    archive, catalog = reading.local_artifact(
        args.artifact, args.artifact_sha256, args.source_commit
    )
    task_bytes = (ROOT / "evals/core/tasks.json").read_bytes()
    tasks = json.loads(task_bytes)
    stacks = auth_eval.STACKS if args.stack == "all" else (args.stack,)
    trials = schedule(tuple(args.models), stacks, tuple(args.scenarios), args.repeats)
    labels = {model: f"m{index:02d}" for index, model in enumerate(args.models, 1)}
    output = auth_eval.prepare_output(args.output)
    metadata = catalog | {
        "protocol_id": "core-choice-v1",
        "requested_models": args.models,
        "model_labels": labels,
        "timeout_seconds": args.timeout,
        "repeats": args.repeats,
        "scenarios": args.scenarios,
        "stacks": list(stacks),
        "tasks_sha256": sha256(task_bytes),
        "availability_probes_included": False,
    }
    contexts = getattr(choice_tasks, "NATIVE_CONTEXTS", None)
    if isinstance(contexts, dict):
        metadata["framework_contexts"] = {stack: contexts[stack] for stack in stacks}
    for key, path in (
        ("runner_sha256", __file__),
        ("auth_runner_sha256", auth_eval.__file__),
        ("core_runner_sha256", core_eval.__file__),
        ("discovery_runner_sha256", discovery.__file__),
        ("choice_tasks_sha256", choice_tasks.__file__),
        ("reading_runner_sha256", reading.__file__),
        ("trace_runner_sha256", reading_trace.__file__),
        ("source_evidence_sha256", source_evidence.__file__),
    ):
        metadata[key] = sha256(file_bytes(Path(path)))
    metadata["runner_source_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    rows, blocked = [], None
    with tempfile.TemporaryDirectory(prefix="feature-choice-source-") as temporary:
        template = Path(temporary).resolve() / "source"
        metadata.update(
            discovery.neutralize(
                template,
                core_eval.freeze_sources(
                    ROOT, template, archive, commit=args.source_commit
                ),
            )
        )
        source = auth_eval.fingerprint(template)
        manifest = {
            "metadata": metadata,
            "trials": [
                {
                    "trial": trial_name(labels[model], stack, scenario, repeat),
                    "requested_model": model,
                    "model_label": labels[model],
                    "stack": stack,
                    "condition": scenario,
                    "repeat": repeat,
                    "sequence": index,
                }
                for index, (model, stack, scenario, repeat) in enumerate(trials, 1)
            ],
        }
        auth_eval.write_json(output / "manifest.json", manifest)
        metadata["manifest_sha256"] = sha256(file_bytes(output / "manifest.json"))

        def current():
            return summarize(rows, metadata, len(trials)) | {
                "blocked": blocked,
                "complete": len(rows) == len(trials) and blocked is None,
            }

        reading.checkpoint(output / "progress.json", current())
        for assignment in manifest["trials"]:
            retained = output / assignment["trial"]
            result = auth_eval.run_trial(
                ROOT,
                retained,
                assignment["stack"],
                assignment["condition"],
                args.timeout,
                model=assignment["requested_model"],
                template=template,
                source_metadata=metadata,
                tasks=tasks,
                repeat=assignment["repeat"],
                sequence=assignment["sequence"],
                contract=choice_tasks.contract_factory(assignment["condition"]),
            )
            result.update(
                trial=assignment["trial"], model_label=assignment["model_label"]
            )
            rows.append(result)
            try:
                analyze(result, retained, source, tasks, args.source_commit)
            except (
                EvalError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                SyntaxError,
            ) as exc:
                result.setdefault("original_http_passed", result["passed"])
                result.setdefault("original_error_code", result["error_code"])
                result.setdefault("postprocessing_errors", []).append(
                    {"stage": "analysis", "error_type": type(exc).__name__}
                )
                result["analysis_complete"] = False
                result.setdefault(
                    "started_state",
                    {"supported_started": None, "infrastructure_error": None},
                )
            state = result["started_state"]
            blocked = state.get("infrastructure_error") or (
                "cli-terminal-error" if state.get("terminal_error") else None
            )
            auth_eval.write_json(retained / "analysis.json", result)
            result["analysis_sha256"] = sha256(file_bytes(retained / "analysis.json"))
            reading.checkpoint(output / "progress.json", current())
            print(
                f"{len(rows)}/{len(trials)} {assignment['model_label']}/{assignment['stack']}/{assignment['condition']}/r{assignment['repeat']}: {'HTTP-PASS' if result['original_http_passed'] else _safe_code(result['original_error_code'])}",
                flush=True,
            )
            if blocked:
                break
        report = current()
        auth_eval.write_json(output / "summary.json", report)
    return 0 if report["complete"] else 1


def read_json(path):
    return json.loads(file_bytes(path).decode("utf-8"))


def retained_rows(root):
    """Verify saved analysis and raw evidence; never replay or rewrite programs."""
    auth_eval.no_symlink(root)
    manifest_data = file_bytes(root / "manifest.json")
    manifest = json.loads(manifest_data)
    summary = read_json(
        root / ("summary.json" if (root / "summary.json").exists() else "progress.json")
    )
    if summary.get("suite") != "core-choice-v1" or summary.get(
        "manifest_sha256"
    ) != sha256(manifest_data):
        raise EvalError("retained-manifest-mismatch")
    expected = {item["trial"]: item for item in manifest["trials"]}
    public = {item["trial"]: item for item in summary["runs"]}
    if len(expected) != len(manifest["trials"]) or len(public) != len(summary["runs"]):
        raise EvalError("duplicate-retained-trial")
    actual = {
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "result.json").exists()
    }
    if actual != set(public) or not actual.issubset(expected):
        raise EvalError("retained-attempt-set-mismatch")
    rows = []
    for trial in sorted(actual, key=lambda name: expected[name]["sequence"]):
        if not re.fullmatch(
            r"m\d{2}-(?:python|go|java|rust)-(?:documents|notes)-trial-[1-4]", trial
        ):
            raise EvalError("unsafe-retained-trial")
        retained = root / trial
        analysis_data = file_bytes(retained / "analysis.json")
        if sha256(analysis_data) != public[trial].get("analysis_sha256"):
            raise EvalError("retained-analysis-mismatch")
        row = json.loads(analysis_data)
        original_data = file_bytes(retained / "result.json")
        if sha256(original_data) != row.get("original_result_sha256"):
            raise EvalError("retained-original-result-mismatch")
        original = json.loads(original_data)
        if any(
            original.get(key) != value or row.get(key) != value
            for key, value in manifest["metadata"].items()
        ):
            raise EvalError("retained-provenance-mismatch")
        if any(
            row.get(key) != expected[trial][key]
            or original.get(key) != expected[trial][key]
            for key in ("requested_model", "stack", "condition", "repeat", "sequence")
        ):
            raise EvalError("retained-assignment-mismatch")
        if (
            row.get("original_http_passed") != original.get("passed")
            or row.get("original_error_code") != original.get("error_code")
            or row.get("checks") != original.get("checks")
            or row.get("source_unchanged") != original.get("source_unchanged")
        ):
            raise EvalError("retained-original-outcome-mismatch")
        trace = retained / "trace.jsonl"
        actual_trace = (
            sha256(file_bytes(trace, 100_000_000)) if trace.exists() else None
        )
        if actual_trace != row.get("trace_sha256"):
            raise EvalError("retained-trace-mismatch")
        if (
            row.get("source_inventory") is not None
            and source_inventory(retained / "snapshot/generated")
            != row["source_inventory"]
        ):
            raise EvalError("retained-generated-source-mismatch")
        if row.get("retained_source_sha256") != auth_eval.digest_hashes(
            auth_eval.fingerprint(retained / "snapshot")
        ):
            raise EvalError("retained-reference-source-mismatch")
        row["analysis_sha256"] = sha256(analysis_data)
        rows.append(row)
    return (
        rows,
        manifest["metadata"] | {"manifest_sha256": sha256(manifest_data)},
        len(expected),
        summary.get("blocked"),
    )


def validate_reviews(document, rows, root):
    if (
        not isinstance(document, dict)
        or set(document) != {"reviews"}
        or not isinstance(document["reviews"], list)
    ):
        raise EvalError("invalid-source-review")
    by_trial = {row["trial"]: row for row in rows}
    reviews = {}
    for review in document["reviews"]:
        if not isinstance(review, dict) or set(review) != {
            "trial",
            "original_result_sha256",
            "features",
        }:
            raise EvalError("invalid-source-review")
        trial = review["trial"]
        if not isinstance(trial, str) or trial not in by_trial or trial in reviews:
            raise EvalError("invalid-source-review-trial")
        row = by_trial[trial]
        if review["original_result_sha256"] != row.get("original_result_sha256"):
            raise EvalError("review-original-result-mismatch")
        features = review["features"]
        if not isinstance(features, dict) or set(features) != set(FEATURES):
            raise EvalError("invalid-source-review-features")
        inventory = {
            item["path"]: item
            for item in (row.get("source_inventory") or {}).get("files", [])
        }
        for feature in FEATURES:
            item = features[feature]
            if (
                not isinstance(item, dict)
                or set(item) != {"classification", "evidence"}
                or item["classification"] not in CLASSES
                or not isinstance(item["evidence"], list)
                or (not item["evidence"] and item["classification"] != "uncertain")
            ):
                raise EvalError("invalid-source-review-classification")
            for evidence in item["evidence"]:
                if not isinstance(evidence, dict) or set(evidence) != {
                    "path",
                    "line",
                    "sha256",
                }:
                    raise EvalError("invalid-source-review-evidence")
                relative = safe_relative(evidence["path"])
                record = inventory.get(relative)
                if (
                    record is None
                    or type(evidence["line"]) is not int
                    or evidence["line"] < 1
                ):
                    raise EvalError("invalid-source-review-evidence")
                data = file_bytes(
                    root / trial / "snapshot/generated" / relative, MAX_SOURCE_BYTES
                )
                if (
                    sha256(data) != record["sha256"]
                    or evidence["sha256"] != record["sha256"]
                    or evidence["line"]
                    > len(data.decode("utf-8", errors="strict").splitlines())
                ):
                    raise EvalError("source-review-evidence-mismatch")
        reviews[trial] = review
    return reviews


def report(args):
    root = args.input.expanduser().absolute()
    rows, metadata, planned, blocked = retained_rows(root)
    reviews = (
        validate_reviews(read_json(args.reviews), rows, root) if args.reviews else {}
    )
    result = summarize(rows, metadata, planned, reviews) | {
        "blocked": blocked,
        "complete": len(rows) == planned and blocked is None,
        "report_kind": "retained-source-review",
        "reviews_sha256": sha256(file_bytes(args.reviews)) if args.reviews else None,
    }
    output = auth_eval.prepare_output(args.output)
    auth_eval.write_json(output / "summary.json", result)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in {"run", "report"}:
        argv.insert(0, "run")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--artifact", type=Path, required=True)
    runner.add_argument("--artifact-sha256", required=True)
    runner.add_argument("--source-commit", required=True)
    runner.add_argument("--models", nargs="+", required=True)
    runner.add_argument("--stack", choices=(*auth_eval.STACKS, "all"), default="all")
    runner.add_argument(
        "--scenarios",
        nargs="+",
        choices=choice_tasks.SCENARIOS,
        default=list(choice_tasks.SCENARIOS),
    )
    runner.add_argument("--repeats", type=int, choices=range(1, 5), default=2)
    runner.add_argument("--timeout", type=int, default=600)
    runner.add_argument("--output", type=Path, required=True)
    reporter = commands.add_parser("report")
    reporter.add_argument("--input", type=Path, required=True)
    reporter.add_argument("--reviews", type=Path)
    reporter.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return run(args, runner) if args.command == "run" else report(args)
    except (
        EvalError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ):
        print(
            "Choice evaluation could not complete; inspect private retained evidence.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
