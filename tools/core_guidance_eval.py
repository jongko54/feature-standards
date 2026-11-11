"""Run paired optional SDK guidance observations, separately from core-choice-v1."""

from __future__ import annotations

import argparse
import inspect
import json
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import auth_eval
import choice_tasks_v2 as tasks_v2
import core_choice_eval as legacy
import core_eval
from auth_eval import EvalError

ROOT = Path(__file__).resolve().parents[1]
SUITE = "core-guidance-v2"
MODULE_PATHS = {
    "runner": "tools/core_guidance_eval.py",
    "tasks": "tools/choice_tasks_v2.py",
    "legacy_tasks": "tools/choice_tasks.py",
    "auth": "tools/auth_eval.py",
    "core": "tools/core_eval.py",
    "choice": "tools/core_choice_eval.py",
    "discovery": "tools/core_discovery_eval.py",
    "reading": "tools/core_reading_eval.py",
    "trace": "tools/reading_trace.py",
    "source_evidence": "tools/source_evidence.py",
}
GUIDE_PATHS = {stack: f"docs/ai-entry/{stack}.md" for stack in auth_eval.STACKS}
TASK_PATH = "evals/core/tasks.json"
PUBLIC_METADATA = frozenset(
    (
        "protocol_id",
        "requested_model",
        "model_label",
        "stacks",
        "scenarios",
        "conditions",
        "repeats",
        "timeout_seconds",
        "availability_probes_included",
        "module_sha256",
        "fixture_generator_sha256",
        "runner_source_commit",
        "framework_contexts",
        "expected_http_assertions",
        "tasks_sha256",
        "guide_sha256",
        "source_commit",
        "source_dirty",
        "source_sha256",
        "implementation_source_sha256",
        "catalog_snapshot_sha256",
        "upstream_source_sha256",
        "upstream_implementation_source_sha256",
        "instruction_overlay",
        "discovery_agents_sha256",
        "catalog_version",
        "catalog_sha256",
        "catalog_kind",
        "catalog_public_download_verified",
        "candidate_source_commit",
        "manifest_sha256",
    )
)
LIMITS = [
    "One requested model, four backends, two controlled synthetic tasks and two repetitions per condition; this is not external adoption or a population estimate.",
    "Only the optional pointer differs. Both conditions have identical source, neutral instructions, cards, archive, build guidance and paired private ticket data.",
    "Private fixture values enter generated programs after model work. The visible generator and same-user host are not an OS security boundary or a wholly secret grader.",
    "All attempts and failures remain visible. Unsupported, unknown starts, reviewable choices and original HTTP success have separate denominators.",
    "Unreviewed and uncertain source choices are unknown. API-use classifications require source review; names, imports and static hints are not proof of use.",
    "Token pairs require complete comparable usage, independently of HTTP success. Joint-working pairs are a separately labelled diagnostic. Input includes cached input; total=input+output.",
    "Requested model, observed model or unknown, CLI and native contexts are recorded. Server weights, dependency/prompt caches, host load and internal API requests are not controlled.",
    "Do not pool with the earlier core-choice-v1 sessions or infer a general causal saving, market adoption, production security or real customer use.",
]


def fixture_hash(value):
    return legacy.sha256(tasks_v2.ticket_fixture_bytes(value))


def fixture_generator_hash():
    source = "\n".join(
        inspect.getsource(function)
        for function in (tasks_v2.ticket_fixture, tasks_v2.ticket_fixture_bytes)
    )
    return legacy.sha256(source.encode())


def tokens(row):
    # A failed/interrupted CLI can report only earlier completed turns' usage.
    if (row.get("agent") or {}).get("completed") is not True:
        return None
    return legacy.reading.tokens(row)


def blocking_state(state):
    return state.get("infrastructure_error") or (
        "cli-terminal-error"
        if state.get("terminal_error") and not state.get("turn_completed")
        else None
    )


def ticket_fixture_observation(generated, scenario, expected_hash):
    """Read the retained private fixture safely; never publish its basename."""
    empty = {
        "state": "not-applicable" if scenario != "tickets" else "not-created",
        "sha256": None,
        "matches_expected": None,
        "private_file": None,
    }
    if scenario != "tickets":
        return empty
    auth_eval.no_symlink(generated)
    candidates = [
        p for p in generated.iterdir() if p.name.startswith(".core-membership-tickets-")
    ]
    if not candidates:
        return empty
    if len(candidates) != 1 or not re.fullmatch(
        r"\.core-membership-tickets-[0-9a-f]{24}\.json", candidates[0].name
    ):
        raise EvalError("unsafe-ticket-fixture-set")
    path = candidates[0]
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        raise EvalError("unsafe-ticket-fixture-file")
    data = legacy.file_bytes(path, legacy.MAX_SOURCE_BYTES)
    after = path.lstat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_mode,
        before.st_nlink,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_mode,
        after.st_nlink,
    ) or len(data) != after.st_size:
        raise EvalError("ticket-fixture-changed-during-read")
    actual_hash = legacy.sha256(data)
    return {
        "state": "injected",
        "sha256": actual_hash,
        "matches_expected": actual_hash == expected_hash,
        "private_file": path.name,
    }


def public_inventory(value):
    if value is None:
        return None
    return value | {
        "excluded": [
            item | {"path": None}
            if item.get("reason") == "private-fixture-or-environment"
            else item
            for item in value.get("excluded", [])
        ]
    }


def verified_ticket_fixture(row):
    integrity = row.get("ticket_fixture_integrity") or {}
    return row.get("scenario") != "tickets" or (
        integrity.get("state") == "injected"
        and integrity.get("matches_expected") is True
        and integrity.get("sha256") == row.get("fixture_sha256")
    )


def working_http(row):
    return bool(
        row.get("source_unchanged") is True
        and row.get("retained_source_unchanged") is True
        and row.get("original_http_passed") is True
        and len(row.get("checks", [])) == tasks_v2.expected_assertions(row["scenario"])
        and verified_ticket_fixture(row)
    )


def schedule(model, stacks, scenarios, repeats):
    """Rotate task/condition cells by backend; reverse the next repetition."""
    cells = [
        (scenario, condition)
        for scenario in scenarios
        for condition in tasks_v2.CONDITIONS
    ]
    result = []
    for repeat in range(1, repeats + 1):
        for index, stack in enumerate(stacks):
            rotation = index % len(cells)
            order = cells[rotation:] + cells[:rotation]
            if repeat % 2 == 0:
                order = order[::-1]
            for scenario, condition in order:
                result.append(
                    {
                        "trial": f"m01-{stack}-{scenario}-{condition}-trial-{repeat}",
                        "pair_id": f"m01-{stack}-{scenario}-pair-{repeat}",
                        "model_label": "m01",
                        "requested_model": model,
                        "stack": stack,
                        "scenario": scenario,
                        "condition": condition,
                        "repeat": repeat,
                        "sequence": len(result) + 1,
                    }
                )
    return result


def counts(rows, reviews):
    """Task-specific full HTTP checks; never infer a choice for an unknown row."""
    supported = [
        r
        for r in rows
        if (r.get("started_state") or {}).get("supported_started") is True
    ]
    result = {
        "all_attempts": len(rows),
        "supported_started": len(supported),
        "start_unknown": sum(
            (r.get("started_state") or {}).get("supported_started") is None
            for r in rows
        ),
        "prework_infrastructure": sum(
            (r.get("started_state") or {}).get("supported_started") is False
            for r in rows
        ),
        "reviewable": sum(
            bool((r.get("source_inventory") or {}).get("reviewable")) for r in rows
        ),
        "supported_reviewable": sum(
            bool((r.get("source_inventory") or {}).get("reviewable")) for r in supported
        ),
        "reviewed_supported": 0,
        "complete_choice_reviews": 0,
        "choice_unknown": 0,
        "library_connected_full": 0,
        "partial_library_connected": 0,
        "copied_runtime_source_any": 0,
        "direct_independent_full": 0,
        "provided_api_use_full": 0,
        "provided_api_use_any": 0,
        "mixed_sessions": 0,
        "verified_full_reuse": 0,
        "working_provided_api_use_full": 0,
        "http_passed": sum(r.get("original_http_passed") is True for r in rows),
        "working_http_verified": sum(working_http(r) for r in rows),
        "usage_complete": sum(tokens(r) is not None for r in rows),
    }
    feature_classes = {
        f: dict.fromkeys((*legacy.CLASSES, "unreviewed"), 0) for f in legacy.FEATURES
    }
    for row in rows:
        review = legacy._review(row, reviews)
        classes = [
            review["features"][f]["classification"] if review else "unreviewed"
            for f in legacy.FEATURES
        ]
        for feature, classification in zip(legacy.FEATURES, classes, strict=True):
            feature_classes[feature][classification] += 1
        if row not in supported:
            continue
        known = review is not None and "uncertain" not in classes
        result["reviewed_supported"] += review is not None
        result["complete_choice_reviews"] += known
        result["choice_unknown"] += not known
        connected = sum(c in legacy.CONNECTED for c in classes)
        provided = sum(
            c in legacy.CONNECTED or c == "copied_runtime_source" for c in classes
        )
        full = connected == len(legacy.FEATURES)
        result["library_connected_full"] += full
        result["partial_library_connected"] += 0 < connected < len(legacy.FEATURES)
        result["copied_runtime_source_any"] += "copied_runtime_source" in classes
        result["direct_independent_full"] += all(
            c == "direct_independent" for c in classes
        )
        result["mixed_sessions"] += "mixed" in classes
        result["provided_api_use_full"] += provided == len(legacy.FEATURES)
        result["provided_api_use_any"] += provided > 0
        working = working_http(row)
        result["verified_full_reuse"] += bool(full and working)
        result["working_provided_api_use_full"] += bool(
            provided == len(legacy.FEATURES) and working
        )
    denominator = len(supported)
    eligible = bool(denominator and result["complete_choice_reviews"])
    return result | {
        "feature_classes": feature_classes,
        "rates": {
            "interpretation": "confirmed-lower-bounds-over-all-supported-starts-including-unknown-choices",
            "denominator": denominator,
            "confirmed_full_reuse_lower_bound": result["library_connected_full"]
            / denominator
            if eligible
            else None,
            "verified_full_reuse_lower_bound": result["verified_full_reuse"]
            / denominator
            if eligible
            else None,
            "full_reuse_among_complete_reviews": result["library_connected_full"]
            / result["complete_choice_reviews"]
            if result["complete_choice_reviews"]
            else None,
        },
    }


def usage_pairs(rows, assignments):
    by_trial = {r["trial"]: r for r in rows}
    pairs = []
    keys = sorted(
        {
            (a["requested_model"], a["stack"], a["scenario"], a["repeat"], a["pair_id"])
            for a in assignments
        }
    )
    for model, stack, scenario, repeat, pair_id in keys:
        selected = {
            a["condition"]: by_trial.get(a["trial"])
            for a in assignments
            if a["pair_id"] == pair_id
        }
        left, right = (selected.get(c) for c in tasks_v2.CONDITIONS)
        reason = None
        if left is None or right is None:
            reason = "missing-attempt"
        elif any(
            row.get("source_unchanged") is False
            or row.get("retained_source_unchanged") is False
            for row in (left, right)
        ):
            reason = "reference-source-changed"
        elif any(
            row.get("source_unchanged") is not True
            or row.get("retained_source_unchanged") is not True
            for row in (left, right)
        ):
            reason = "reference-source-unverified"
        elif left.get("fixture_sha256") != right.get("fixture_sha256"):
            reason = "fixture-mismatch"
        elif any(
            row["scenario"] == "tickets"
            and (row.get("ticket_fixture_integrity") or {}).get("state")
            != "not-created"
            and not verified_ticket_fixture(row)
            for row in (left, right)
        ):
            reason = "fixture-integrity-unverified"
        elif any(
            left.get(k) != right.get(k)
            for k in ("source_sha256", "tasks_sha256", "module_sha256", "guide_sha256")
        ):
            reason = "provenance-mismatch"
        elif not left.get("cli_version") or not right.get("cli_version"):
            reason = "cli-version-unknown"
        elif left["cli_version"] != right["cli_version"]:
            reason = "cli-version-mismatch"
        elif (
            left.get("model_selection") == "different"
            or right.get("model_selection") == "different"
            or (
                (left.get("agent") or {}).get("models")
                and (right.get("agent") or {}).get("models")
                and left["agent"]["models"] != right["agent"]["models"]
            )
        ):
            reason = "observed-model-mismatch"
        elif tokens(left) is None or tokens(right) is None:
            reason = "incomplete-usage"
        pair = {
            "pair_id": pair_id,
            "requested_model": model,
            "stack": stack,
            "scenario": scenario,
            "repeat": repeat,
            "included": reason is None,
            "excluded_reason": reason,
            "baseline_trial": left["trial"] if left else None,
            "sdk_pointer_trial": right["trial"] if right else None,
            "baseline_http_passed": left.get("original_http_passed") if left else None,
            "sdk_pointer_http_passed": right.get("original_http_passed")
            if right
            else None,
            "joint_working": bool(
                left and right and working_http(left) and working_http(right)
            ),
        }
        if reason is None:
            baseline, treatment = (
                tokens(left),
                tokens(right),
            )
            pair["tokens"] = {
                "baseline": baseline,
                "sdk-pointer": treatment,
                "difference": {k: treatment[k] - baseline[k] for k in baseline},
            }
        else:
            pair["tokens"] = None
        pairs.append(pair)

    def totals(selected):
        if not selected:
            return None
        return {
            condition: {
                key: sum(p["tokens"][condition][key] for p in selected)
                for key in selected[0]["tokens"][condition]
            }
            for condition in ("baseline", "sdk-pointer", "difference")
        }

    included = [p for p in pairs if p["included"]]
    working = [p for p in included if p["joint_working"]]
    return {
        "planned_pairs": len(pairs),
        "included_pairs": len(included),
        "excluded_pairs": len(pairs) - len(included),
        "comparison_basis": "complete-comparable-usage-independent-of-http-outcome",
        "paired_totals": totals(included),
        "joint_working_pairs": len(working),
        "joint_working_basis": "source-and-task-complete-http-with-verified-ticket-fixture",
        "joint_working_totals": totals(working),
        "pairs": pairs,
    }


def summarize(rows, metadata, assignments, reviews=None):
    public = []
    for row in rows:
        item = {
            key: row.get(key)
            for key in (
                "trial",
                "pair_id",
                "model_label",
                "requested_model",
                "stack",
                "scenario",
                "condition",
                "repeat",
                "sequence",
                "original_http_passed",
                "source_unchanged",
                "retained_source_unchanged",
                "original_result_sha256",
                "trace_sha256",
                "agent_log_sha256",
                "analysis_sha256",
                "prompt_sha256",
                "fixture_sha256",
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
            original_error_code=legacy._safe_code(row.get("original_error_code")),
            http_assertions=len(row.get("checks", [])),
            expected_http_assertions=tasks_v2.expected_assertions(row["scenario"]),
            tokens=tokens(row),
            reported_models=(row.get("agent") or {}).get("models", []),
            actual_model_identity=(row.get("agent") or {}).get("models") or "unknown",
            choice_review=legacy._review(row, reviews),
            classification_source="source-review"
            if legacy._review(row, reviews)
            else None,
            runtime_causality_proven=False,
            working_http_verified=working_http(row),
            source_inventory=public_inventory(row.get("source_inventory")),
            ticket_fixture_integrity={
                key: (row.get("ticket_fixture_integrity") or {}).get(key)
                for key in ("state", "sha256", "matches_expected")
            },
        )
        public.append(item)
    groups = []
    for model, stack, scenario, condition in sorted(
        {
            (a["requested_model"], a["stack"], a["scenario"], a["condition"])
            for a in assignments
        }
    ):
        selected = [
            r
            for r in rows
            if (r["requested_model"], r["stack"], r["scenario"], r["condition"])
            == (model, stack, scenario, condition)
        ]
        groups.append(
            {
                "requested_model": model,
                "stack": stack,
                "scenario": scenario,
                "condition": condition,
                **counts(selected, reviews),
            }
        )
    measurements = counts(rows, reviews)
    return {
        "suite": SUITE,
        **{k: v for k, v in metadata.items() if k in PUBLIC_METADATA},
        "limits": LIMITS,
        "planned_model_calls": len(assignments),
        "actual_model_calls": len(rows),
        "passed": measurements["http_passed"],
        **measurements,
        "groups": groups,
        "condition_totals": [
            {
                "condition": condition,
                **counts([r for r in rows if r["condition"] == condition], reviews),
            }
            for condition in tasks_v2.CONDITIONS
        ],
        "usage_pairs": usage_pairs(rows, assignments),
        "runs": public,
    }


def module_hashes(root):
    return {
        name: legacy.sha256(legacy.file_bytes(root / relative))
        for name, relative in MODULE_PATHS.items()
    }


def validate_template(root, metadata):
    if module_hashes(root) != metadata["module_sha256"]:
        raise EvalError("retained-module-hash-mismatch")
    guides = {
        stack: legacy.sha256(legacy.file_bytes(root / relative))
        for stack, relative in GUIDE_PATHS.items()
    }
    if (
        guides != metadata["guide_sha256"]
        or legacy.sha256(legacy.file_bytes(root / TASK_PATH))
        != metadata["tasks_sha256"]
    ):
        raise EvalError("retained-guide-or-task-hash-mismatch")
    if (
        legacy.sha256(legacy.file_bytes(root / "AGENTS.md"))
        != metadata["discovery_agents_sha256"]
    ):
        raise EvalError("retained-instruction-hash-mismatch")
    if (
        auth_eval.digest_hashes(auth_eval.fingerprint(root / "catalog"))
        != metadata["catalog_snapshot_sha256"]
    ):
        raise EvalError("retained-catalog-hash-mismatch")


def analyze(result, retained, source):
    """Keep raw outcome/trace immutable; observations live in analysis.json."""
    result["original_http_passed"] = result["passed"]
    result["original_error_code"] = result["error_code"]
    original = legacy.file_bytes(retained / "result.json")
    result["original_result_sha256"] = legacy.sha256(original)
    trace = retained / "trace.jsonl"
    trace_bytes = legacy.file_bytes(trace, 100_000_000) if trace.exists() else None
    result["trace_sha256"] = (
        legacy.sha256(trace_bytes) if trace_bytes is not None else None
    )
    stderr_bytes = (
        legacy.file_bytes(retained / "agent.log", 100_000_000)
        if (retained / "agent.log").exists()
        else None
    )
    result["agent_log_sha256"] = (
        legacy.sha256(stderr_bytes) if stderr_bytes is not None else None
    )
    stderr = stderr_bytes.decode(errors="replace") if stderr_bytes is not None else ""
    result["started_state"] = legacy.started_state(trace, stderr)
    snapshot = retained / "snapshot"
    result["retained_source_sha256"] = auth_eval.digest_hashes(
        auth_eval.fingerprint(snapshot)
    )
    result["retained_source_unchanged"] = (
        result["retained_source_sha256"] == result["source_sha256"]
    )
    result["postprocessing_errors"] = []
    generated = snapshot / "generated"
    result["ticket_fixture_integrity"] = legacy._observe(
        result,
        "ticket-fixture-integrity",
        lambda: ticket_fixture_observation(
            generated, result["scenario"], result["fixture_sha256"]
        ),
    ) or {
        "state": "unknown",
        "sha256": None,
        "matches_expected": None,
        "private_file": None,
    }
    if (
        result["scenario"] == "tickets"
        and result["original_http_passed"] is True
        and result["ticket_fixture_integrity"]["matches_expected"] is not True
    ):
        result["postprocessing_errors"].append(
            {"stage": "working-ticket-fixture-integrity", "error_type": "EvalError"}
        )
    for key, operation in (
        ("source_inventory", lambda: legacy.source_inventory(generated)),
        (
            "reading_evidence",
            lambda: legacy.reading_trace.reading_evidence(
                trace, result["stack"], snapshot
            ),
        ),
        ("copy_evidence", lambda: legacy.discovery.copy_evidence(generated, source)),
        (
            "static_reuse",
            lambda: legacy.reading.static_reuse(
                generated, source, result["stack"], result["source_commit"]
            ),
        ),
    ):
        result[key] = legacy._observe(result, key.replace("_", "-"), operation)
    if legacy.file_bytes(retained / "result.json") != original or (
        trace_bytes is not None and legacy.file_bytes(trace, 100_000_000) != trace_bytes
    ):
        raise EvalError("original-evidence-modified")
    result["analysis_complete"] = not result["postprocessing_errors"]


def run(args, parser):
    if (
        not re.fullmatch(auth_eval.MODEL_PATTERN, args.model)
        or not re.fullmatch(r"[a-f0-9]{40}", args.source_commit)
        or not re.fullmatch(r"[a-f0-9]{64}", args.artifact_sha256)
        or not 1 <= args.timeout <= 600
        or len(set(args.scenarios)) != len(args.scenarios)
    ):
        parser.error(
            "One explicit model, pinned source/artifact, unique scenarios and timeout 1..600 are required"
        )
    if shutil.which("codex") is None:
        parser.error("Codex CLI is required")
    archive, catalog = legacy.reading.local_artifact(
        args.artifact, args.artifact_sha256, args.source_commit
    )
    stacks = auth_eval.STACKS if args.stack == "all" else (args.stack,)
    assignments = schedule(args.model, stacks, args.scenarios, args.repeats)
    metadata = catalog | {
        "protocol_id": SUITE,
        "requested_model": args.model,
        "model_label": "m01",
        "stacks": list(stacks),
        "scenarios": args.scenarios,
        "conditions": list(tasks_v2.CONDITIONS),
        "repeats": args.repeats,
        "timeout_seconds": args.timeout,
        "availability_probes_included": False,
        "module_sha256": module_hashes(ROOT),
        "fixture_generator_sha256": fixture_generator_hash(),
        "runner_source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "framework_contexts": {
            s: legacy.choice_tasks.NATIVE_CONTEXTS[s] for s in stacks
        },
        "expected_http_assertions": {
            s: tasks_v2.expected_assertions(s) for s in args.scenarios
        },
    }
    with tempfile.TemporaryDirectory(prefix="feature-guidance-source-") as temporary:
        template = Path(temporary).resolve() / "source"
        metadata.update(
            legacy.discovery.neutralize(
                template,
                core_eval.freeze_sources(
                    ROOT, template, archive, commit=args.source_commit
                ),
            )
        )
        task_file = template / TASK_PATH
        if not task_file.exists():
            task_file.parent.mkdir(parents=True, exist_ok=True)
            task_file.write_bytes(
                subprocess.check_output(
                    ["git", "show", f"{args.source_commit}:{TASK_PATH}"], cwd=ROOT
                )
            )
            task_file.chmod(0o444)
        task_bytes = legacy.file_bytes(task_file)
        tasks = json.loads(task_bytes)
        metadata["tasks_sha256"] = legacy.sha256(task_bytes)
        metadata["guide_sha256"] = {
            s: legacy.sha256(legacy.file_bytes(template / p))
            for s, p in GUIDE_PATHS.items()
        }
        metadata["source_sha256"] = auth_eval.digest_hashes(
            auth_eval.fingerprint(template)
        )
        metadata["implementation_source_sha256"] = auth_eval.digest_hashes(
            {
                k: v
                for k, v in auth_eval.fingerprint(template).items()
                if not k.startswith("catalog/")
            }
        )
        validate_template(template, metadata)
        source = auth_eval.fingerprint(template)
        fixtures = {}
        prompts = {}
        for assignment in assignments:
            pair_id = assignment["pair_id"]
            if assignment["scenario"] == "tickets" and pair_id not in fixtures:
                seed = secrets.token_hex(32)
                fixtures[pair_id] = {
                    "seed": seed,
                    "sha256": fixture_hash(tasks_v2.ticket_fixture(seed)),
                }
            assignment["fixture_sha256"] = (
                fixtures[pair_id]["sha256"] if pair_id in fixtures else None
            )
            prompts[assignment["trial"]] = tasks_v2.prompt(
                assignment["stack"],
                args.source_commit,
                tasks,
                assignment["condition"],
                scenario=assignment["scenario"],
            )
            assignment["prompt_sha256"] = legacy.sha256(
                prompts[assignment["trial"]].encode()
            )
        output = auth_eval.prepare_output(args.output)
        (output / "prompts").mkdir(mode=0o700)
        for trial, prompt in prompts.items():
            with auth_eval.private_file(
                output / "prompts" / (trial + ".txt")
            ) as stream:
                stream.write(prompt.encode())
        manifest = {
            "suite": SUITE,
            "metadata": metadata.copy(),
            "trials": assignments,
            "fixtures": fixtures,
        }
        auth_eval.write_json(output / "manifest.json", manifest)
        metadata["manifest_sha256"] = legacy.sha256(
            legacy.file_bytes(output / "manifest.json")
        )
        rows, blocked = [], None

        def current():
            return summarize(rows, metadata, assignments) | {
                "blocked": blocked,
                "complete": len(rows) == len(assignments) and blocked is None,
            }

        legacy.reading.checkpoint(output / "progress.json", current())
        for assignment in assignments:
            retained = output / assignment["trial"]
            fixture = fixtures.get(assignment["pair_id"])
            ticket_data = tasks_v2.ticket_fixture(fixture["seed"]) if fixture else None
            contract = tasks_v2.contract_factory(
                assignment["scenario"], assignment["condition"], ticket_data=ticket_data
            )
            result = auth_eval.run_trial(
                ROOT,
                retained,
                assignment["stack"],
                assignment["condition"],
                args.timeout,
                model=args.model,
                template=template,
                source_metadata=metadata | assignment,
                tasks=tasks,
                repeat=assignment["repeat"],
                sequence=assignment["sequence"],
                contract=contract,
            )
            rows.append(result)
            try:
                analyze(result, retained, source)
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
                result.setdefault(
                    "ticket_fixture_integrity",
                    {
                        "state": "unknown",
                        "sha256": None,
                        "matches_expected": None,
                        "private_file": None,
                    },
                )
            state = result["started_state"]
            blocked = blocking_state(state)
            auth_eval.write_json(retained / "analysis.json", result)
            result["analysis_sha256"] = legacy.sha256(
                legacy.file_bytes(retained / "analysis.json")
            )
            legacy.reading.checkpoint(output / "progress.json", current())
            print(
                f"{len(rows)}/{len(assignments)} m01/{assignment['stack']}/{assignment['scenario']}/{assignment['condition']}/r{assignment['repeat']}: {'HTTP-PASS' if result['original_http_passed'] else legacy._safe_code(result['original_error_code'])}",
                flush=True,
            )
            if blocked:
                break
        report = current()
        auth_eval.write_json(output / "summary.json", report)
    return 0 if report["complete"] else 1


def retained_rows(root):
    """Validate retained provenance and evidence without replaying applications."""
    auth_eval.no_symlink(root)
    manifest_data = legacy.file_bytes(root / "manifest.json")
    manifest = json.loads(manifest_data)
    summary = legacy.read_json(
        root / ("summary.json" if (root / "summary.json").exists() else "progress.json")
    )
    if (
        manifest.get("suite") != SUITE
        or summary.get("suite") != SUITE
        or summary.get("manifest_sha256") != legacy.sha256(manifest_data)
    ):
        raise EvalError("retained-manifest-mismatch")
    metadata = manifest["metadata"] | {"manifest_sha256": legacy.sha256(manifest_data)}
    if (
        module_hashes(ROOT) != metadata["module_sha256"]
        or metadata["fixture_generator_sha256"] != fixture_generator_hash()
    ):
        raise EvalError("report-runtime-module-mismatch")
    canonical = schedule(
        metadata["requested_model"],
        metadata["stacks"],
        metadata["scenarios"],
        metadata["repeats"],
    )
    expected = {a["trial"]: a for a in manifest["trials"]}
    if len(expected) != len(canonical) or len(expected) != len(manifest["trials"]):
        raise EvalError("duplicate-or-missing-retained-assignment")
    fixture_pairs = {a["pair_id"] for a in canonical if a["scenario"] == "tickets"}
    if set(manifest["fixtures"]) != fixture_pairs:
        raise EvalError("retained-fixture-set-mismatch")
    for fixture in manifest["fixtures"].values():
        if (
            set(fixture) != {"seed", "sha256"}
            or fixture_hash(tasks_v2.ticket_fixture(fixture["seed"]))
            != fixture["sha256"]
        ):
            raise EvalError("retained-fixture-hash-mismatch")
    for assignment in canonical:
        recorded = expected.get(assignment["trial"], {})
        if any(recorded.get(k) != v for k, v in assignment.items()):
            raise EvalError("retained-assignment-mismatch")
        fixture = manifest["fixtures"].get(assignment["pair_id"])
        if recorded.get("fixture_sha256") != (fixture["sha256"] if fixture else None):
            raise EvalError("retained-assignment-fixture-mismatch")
        prompt = legacy.file_bytes(root / "prompts" / (assignment["trial"] + ".txt"))
        if legacy.sha256(prompt) != recorded.get("prompt_sha256"):
            raise EvalError("retained-prompt-hash-mismatch")
    public = {r["trial"]: r for r in summary["runs"]}
    actual = {
        p.name for p in root.iterdir() if p.is_dir() and (p / "result.json").exists()
    }
    if (
        len(public) != len(summary["runs"])
        or actual != set(public)
        or not actual.issubset(expected)
    ):
        raise EvalError("retained-attempt-set-mismatch")
    if actual != {a["trial"] for a in canonical[: len(actual)]}:
        raise EvalError("retained-order-mismatch")
    rows = []
    for trial in sorted(actual, key=lambda name: expected[name]["sequence"]):
        legacy.safe_relative(trial)
        retained = root / trial
        analysis_data = legacy.file_bytes(retained / "analysis.json")
        if legacy.sha256(analysis_data) != public[trial].get("analysis_sha256"):
            raise EvalError("retained-analysis-mismatch")
        row = json.loads(analysis_data)
        original_data = legacy.file_bytes(retained / "result.json")
        if legacy.sha256(original_data) != row.get("original_result_sha256"):
            raise EvalError("retained-original-result-mismatch")
        original = json.loads(original_data)
        if any(
            row.get(k) != v or original.get(k) != v
            for k, v in (metadata | expected[trial]).items()
        ):
            raise EvalError("retained-provenance-or-assignment-mismatch")
        if (
            row.get("original_http_passed") != original.get("passed")
            or row.get("original_error_code") != original.get("error_code")
            or any(row.get(k) != v for k, v in original.items())
        ):
            raise EvalError("retained-original-outcome-mismatch")
        trace = retained / "trace.jsonl"
        trace_hash = (
            legacy.sha256(legacy.file_bytes(trace, 100_000_000))
            if trace.exists()
            else None
        )
        if trace_hash != row.get("trace_sha256"):
            raise EvalError("retained-trace-mismatch")
        stderr_file = retained / "agent.log"
        stderr_data = (
            legacy.file_bytes(stderr_file, 100_000_000)
            if stderr_file.exists()
            else None
        )
        if (legacy.sha256(stderr_data) if stderr_data is not None else None) != row.get(
            "agent_log_sha256"
        ):
            raise EvalError("retained-agent-log-mismatch")
        state = legacy.started_state(
            trace,
            stderr_data.decode(errors="replace") if stderr_data is not None else "",
        )
        if state != row.get("started_state"):
            raise EvalError("retained-started-state-mismatch")
        if trace.exists() and auth_eval.parse_trace(trace) != original.get("agent"):
            raise EvalError("retained-agent-trace-mismatch")
        snapshot = retained / "snapshot"
        observed_fixture = ticket_fixture_observation(
            snapshot / "generated", row["scenario"], row["fixture_sha256"]
        )
        if observed_fixture != row.get("ticket_fixture_integrity"):
            raise EvalError("retained-ticket-fixture-integrity-mismatch")
        if (
            row["scenario"] == "tickets"
            and row["original_http_passed"] is True
            and observed_fixture["matches_expected"] is not True
        ):
            raise EvalError("working-ticket-fixture-integrity-mismatch")
        validate_template(snapshot, metadata)
        task_data = json.loads(legacy.file_bytes(snapshot / TASK_PATH))
        regenerated = tasks_v2.prompt(
            row["stack"],
            metadata["source_commit"],
            task_data,
            row["condition"],
            scenario=row["scenario"],
        )
        if legacy.sha256(regenerated.encode()) != row["prompt_sha256"]:
            raise EvalError("retained-task-prompt-mismatch")
        if (
            row.get("source_inventory") is not None
            and legacy.source_inventory(snapshot / "generated")
            != row["source_inventory"]
        ):
            raise EvalError("retained-generated-source-mismatch")
        if row.get("retained_source_sha256") != auth_eval.digest_hashes(
            auth_eval.fingerprint(snapshot)
        ):
            raise EvalError("retained-reference-source-mismatch")
        row["analysis_sha256"] = legacy.sha256(analysis_data)
        rows.append(row)
    blocked = blocking_state(rows[-1]["started_state"]) if rows else None
    if blocked != summary.get("blocked"):
        raise EvalError("retained-blocked-state-mismatch")
    return rows, metadata, manifest["trials"], blocked


def report(args):
    root = args.input.expanduser().absolute()
    rows, metadata, assignments, blocked = retained_rows(root)
    reviews = (
        legacy.validate_reviews(legacy.read_json(args.reviews), rows, root)
        if args.reviews
        else {}
    )
    result = summarize(rows, metadata, assignments, reviews) | {
        "blocked": blocked,
        "complete": len(rows) == len(assignments) and blocked is None,
        "report_kind": "retained-source-review",
        "reviews_sha256": legacy.sha256(legacy.file_bytes(args.reviews))
        if args.reviews
        else None,
    }
    output = auth_eval.prepare_output(args.output)
    auth_eval.write_json(output / "summary.json", result)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--artifact", type=Path, required=True)
    runner.add_argument("--artifact-sha256", required=True)
    runner.add_argument("--source-commit", required=True)
    runner.add_argument("--model", required=True)
    runner.add_argument("--stack", choices=(*auth_eval.STACKS, "all"), default="all")
    runner.add_argument(
        "--scenarios",
        nargs="+",
        choices=tasks_v2.SCENARIOS,
        default=list(tasks_v2.SCENARIOS),
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
        SyntaxError,
        subprocess.SubprocessError,
    ):
        print(
            "Guidance evaluation could not complete; inspect private retained evidence.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
