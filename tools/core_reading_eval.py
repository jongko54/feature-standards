"""Compare three reading routes against one frozen new-source CLI artifact."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import tarfile
import tempfile
from pathlib import Path

import auth_eval
import core_eval
from auth_eval import EvalError

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("manual", "catalog_full", "catalog_compact")
METRICS = (
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "total_tokens",
)
IDENTITY = (
    "source_sha256",
    "requested_model",
    "cli_version",
    "runner_sha256",
    "auth_runner_sha256",
    "core_runner_sha256",
    "trace_runner_sha256",
    "tasks_sha256",
    "profile",
    "timeout_seconds",
)
LIMITS = [
    "Two observations per stack/condition are exploratory, not a population estimate or proof of causation.",
    "Assigned entrypoint differs; all conditions have the identical candidate archive, source, task and tool environment.",
    "Serial execution and rotated/reversed condition order reduce some confounds; shared warm dependency caches and server prompt caches remain.",
    "Input includes cached input. Total=input+output; uncached=input-cached. These are token counts, not price or unique prompt size.",
    "All complete paired attempts and joint-success pairs are separate. Failed or missing-usage trials are never silently dropped or replaced by zero.",
    "Observed commands, static public-API call evidence and independent HTTP success are distinct evidence. None measures external adoption or model internal reasoning.",
    "Task is auth+RBAC+materialized listing. New PostgreSQL-listing APIs, React UI and other models are not measured.",
]


def tokens(result):
    agent = result.get("agent") or {}
    value = agent.get("usage")
    if not agent.get("usage_complete") or not isinstance(value, dict):
        return None
    keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    if any(type(value.get(k)) is not int or value[k] < 0 for k in keys):
        return None
    if value["cached_input_tokens"] > value["input_tokens"]:
        return None
    return {k: value[k] for k in keys} | {
        "uncached_input_tokens": value["input_tokens"] - value["cached_input_tokens"],
        "total_tokens": value["input_tokens"] + value["output_tokens"],
    }


def schedule(stacks, repeats):
    result = []
    for repeat in range(repeats):
        for index, stack in enumerate(stacks):
            rotation = index % len(CONDITIONS)
            order = CONDITIONS[rotation:] + CONDITIONS[:rotation]
            if repeat % 2:
                order = order[::-1]
            result.extend((stack, repeat + 1, condition) for condition in order)
    return result


def prompt(stack, commit, tasks, condition):
    if condition not in CONDITIONS:
        raise EvalError("invalid-reading-condition")
    if condition == "manual":
        entry = (
            "Start at ../README.md and the selected implementation/library public API guides "
            "and consumer examples. Locate the relevant contracts manually. "
            "The same catalog is available under ../catalog/package if you choose to use it."
        )
    else:
        flag = " --compact" if condition == "catalog_compact" else ""
        entry = (
            "First run node ../catalog/package/src/cli.mjs list. Then run these selected commands:\n"
            + "\n".join(
                f"node ../catalog/package/src/cli.mjs context --feature {feature} "
                f"--stack {stack} --profile {profile}{flag}"
                for feature, profile in (
                    ("auth", "browser-session-v1"),
                    ("authorization", "rbac-v1"),
                    ("listing", "offset-list-v1"),
                )
            )
            + "\nUse the returned document paths to read the relevant public APIs and consumer guide."
        )
    original = core_eval.prompt(stack, commit, tasks, "baseline")
    _, separator, body = original.partition("\n\nCurrent directory")
    if not separator:
        raise EvalError("upstream-task-shape-changed")
    body = body.replace(
        "Both conditions receive the same source and verified feature-standards@0.3.2 catalog bytes.",
        "All conditions receive the same source and feature-standards@0.4.0 local candidate archive bytes; this is not a registry-publication experiment.",
    ).replace(
        "using the published rbac-v1 and offset-list-v1 APIs",
        "using the source packages' rbac-v1 and offset-list-v1 public APIs",
    )
    return (
        f"{tasks['stacks'][stack]}\n{entry}\n\nCurrent directory{body}\n"
        "Keep dependency/build outputs in conventional .venv, .cache, target or bin directories. "
        "Use normal dependency caches; do not require offline resolution for unavailable packages. "
        "Read only the selected API/consumer/contract material needed for this integration. "
        "Prefer a small adapter over reimplementing existing behavior. "
        "Do not run the full repository tests. run.json must build/start this app independently.\n"
    )


def local_artifact(path, expected_sha256, source_commit):
    auth_eval.no_symlink(path)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or path.stat().st_size > 5_000_000
    ):
        raise EvalError("candidate-artifact-hash-or-size")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise EvalError("candidate-artifact-hash-mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        names = set()
        for member in archive.getmembers():
            name = str(core_eval._safe_member(member, package=True))
            if name.casefold() in names:
                raise EvalError("duplicate-candidate-member")
            names.add(name.casefold())
        package = json.load(archive.extractfile("package/package.json"))
        provenance = json.load(archive.extractfile("package/snapshot/provenance.json"))
        if (
            package.get("name") != "feature-standards"
            or package.get("version") != "0.4.0"
            or provenance.get("sourceCommit") != source_commit
            or provenance.get("sourceDirty") is not False
            or provenance.get("snapshotDirty") is not False
        ):
            raise EvalError("candidate-provenance-mismatch")
        for name, record in provenance["files"].items():
            member = "package/snapshot/" + name
            if (
                record.get("sourceModified") is not False
                or hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                != record["sha256"]
            ):
                raise EvalError("candidate-document-hash-mismatch")
    return data, {
        "catalog_version": "0.4.0",
        "catalog_sha256": expected_sha256,
        "catalog_kind": "local-source-candidate",
        "catalog_public_download_verified": False,
        "candidate_source_commit": source_commit,
    }


def comparison(rows, reference, variant):
    selected = {}
    for row in rows:
        if row["condition"] not in (reference, variant):
            continue
        key = (row["stack"], row["repeat"], row["condition"])
        if key in selected:
            raise EvalError("duplicate-comparison-trial")
        selected[key] = row
    keys = {(s, r) for s, r, _ in selected}
    pairs, good, missing, mismatch, unmatched = [], [], 0, 0, 0
    for stack, repeat in sorted(keys):
        left = selected.get((stack, repeat, reference))
        right = selected.get((stack, repeat, variant))
        if left is None or right is None:
            unmatched += 1
            continue
        models = set((left.get("agent") or {}).get("models", []))
        models.update((right.get("agent") or {}).get("models", []))
        if any(
            left.get(k) != right.get(k) or not left.get(k) for k in IDENTITY
        ) or not models.issubset({left.get("requested_model")}):
            mismatch += 1
            continue
        baseline, alternative = tokens(left), tokens(right)
        if baseline is None or alternative is None:
            missing += 1
            continue
        pair = (baseline, alternative)
        pairs.append(pair)
        if left["passed"] and right["passed"]:
            good.append(pair)

    def totals(items):
        metrics = {}
        for metric in METRICS:
            baseline = sum(a[metric] for a, _ in items)
            alternative = sum(b[metric] for _, b in items)
            percentages = [
                (a[metric] - b[metric]) / a[metric] * 100 for a, b in items if a[metric]
            ]
            metrics[metric] = {
                "reference_sum": baseline if items else None,
                "variant_sum": alternative if items else None,
                "reduction_percent": round((baseline - alternative) / baseline * 100, 3)
                if items and baseline
                else None,
                "paired_median_reduction_percent": round(
                    statistics.median(percentages), 3
                )
                if percentages
                else None,
            }
        return {"pairs": len(items), "metrics": metrics}

    return {
        "reference": reference,
        "variant": variant,
        "reference_attempts": sum(r["condition"] == reference for r in rows),
        "variant_attempts": sum(r["condition"] == variant for r in rows),
        "reference_failures": sum(
            r["condition"] == reference and not r["passed"] for r in rows
        ),
        "variant_failures": sum(
            r["condition"] == variant and not r["passed"] for r in rows
        ),
        "unmatched_pairs": unmatched,
        "missing_usage_pairs": missing,
        "configuration_mismatch_pairs": mismatch,
        "all_complete_pairs": totals(pairs),
        "joint_success_pairs": totals(good),
    }


def summarize(rows, metadata, *, planned_total):
    public = []
    for row in rows:
        public.append(
            {
                k: row.get(k)
                for k in (
                    "stack",
                    "condition",
                    "repeat",
                    "sequence",
                    "passed",
                    "original_http_passed",
                    "original_error_code",
                    "error_code",
                    "postprocessing_error",
                    "source_unchanged",
                    "elapsed_seconds",
                    "agent_seconds",
                    "cli_version",
                    "model_selection",
                    "reading_evidence",
                    "static_reuse",
                    "original_result_sha256",
                    "trace_sha256",
                    "prompt_sha256",
                )
            }
            | {
                "http_assertions": len(row.get("checks", [])),
                "tokens": tokens(row),
                "reported_models": (row.get("agent") or {}).get("models", []),
                "command_count": (row.get("agent") or {}).get("command_count"),
            }
        )
    groups = {}
    for condition in CONDITIONS:
        values = [row for row in rows if row["condition"] == condition]
        groups[condition] = {
            "attempts": len(values),
            "passed": sum(bool(r["passed"]) for r in values),
            "complete_usage": sum(tokens(r) is not None for r in values),
            "static_reuse_pass": sum(
                bool((r.get("static_reuse") or {}).get("passed")) for r in values
            ),
            "static_reuse_and_http_pass": sum(
                bool((r.get("static_reuse") or {}).get("passed")) and r["passed"]
                for r in values
            ),
        }
    return {
        "suite": "core-reading-candidate-v1",
        **metadata,
        "limits": LIMITS,
        "planned_model_calls": planned_total,
        "actual_model_calls": len(rows),
        "passed": sum(bool(r["passed"]) for r in rows),
        "groups": groups,
        "comparisons": [
            comparison(rows, a, b)
            for a, b in (
                ("manual", "catalog_full"),
                ("manual", "catalog_compact"),
                ("catalog_full", "catalog_compact"),
            )
        ],
        "runs": public,
    }


def static_reuse(generated, source, stack, commit):
    try:
        core_eval.core_reuse_check(generated, stack, source, commit)
        return {
            "passed": True,
            "kind": "static-public-auth-and-core-call-evidence",
            "runtime_causality_proven": False,
        }
    except (EvalError, OSError, ValueError, SyntaxError) as exc:
        code = str(exc) if isinstance(exc, EvalError) else "static-check-unavailable"
        return {
            "passed": False,
            "error_code": code,
            "kind": "static-public-auth-and-core-call-evidence",
            "runtime_causality_proven": False,
        }


def checkpoint(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".progress-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def terminal_block_reason(trace, stderr):
    """Only CLI terminal errors, never normal tool command/output content."""
    messages = []
    if trace.exists():
        for line in trace.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") in {
                "error",
                "turn.failed",
            }:
                messages.append(
                    json.dumps(
                        {
                            key: event.get(key)
                            for key in ("message", "error", "code", "status")
                        },
                        ensure_ascii=False,
                    )
                )
    messages.extend(
        line
        for line in stderr.splitlines()
        if re.search(
            r"\b(?:error|failed|exceeded|reached|unauthorized)\b", line, re.IGNORECASE
        )
    )
    for pattern, code in (
        (
            r"not logged in|\b401\b|invalid_api_key|authentication[_ -](?:failed|required)",
            "cli-authentication-failed",
        ),
        (r"(?:rate|usage)[_ -]limit|\b429\b", "cli-rate-limited"),
        (
            r"model[^\n]*(?:not[_ -]found|not[_ -]supported|does[_ -]not[_ -]exist)",
            "cli-model-unavailable",
        ),
    ):
        if any(re.search(pattern, message, re.IGNORECASE) for message in messages):
            return code
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--stack", choices=(*auth_eval.STACKS, "all"), default="all")
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not re.fullmatch(auth_eval.MODEL_PATTERN, args.model)
        or not re.fullmatch(r"[a-f0-9]{40}", args.source_commit)
        or not 1 <= args.timeout <= 600
        or shutil.which("codex") is None
    ):
        parser.error(
            "Fixed valid model/source, timeout1..600 and existing Codex CLI required"
        )
    from reading_trace import reading_evidence

    artifact, catalog_metadata = local_artifact(
        args.artifact, args.artifact_sha256, args.source_commit
    )
    output = auth_eval.prepare_output(args.output)
    tasks_bytes = (ROOT / "evals/core/tasks.json").read_bytes()
    tasks = json.loads(tasks_bytes)
    stacks = auth_eval.STACKS if args.stack == "all" else (args.stack,)
    trials = schedule(stacks, args.repeats)
    rows = []
    metadata = {
        **catalog_metadata,
        "requested_model": args.model,
        "timeout_seconds": args.timeout,
        "repeats": args.repeats,
    }
    blocked = None
    with tempfile.TemporaryDirectory(prefix="feature-reading-source-") as temporary:
        template = Path(temporary).resolve() / "source"
        metadata.update(
            core_eval.freeze_sources(
                ROOT, template, artifact, commit=args.source_commit
            )
        )
        for key, name in (
            ("runner_sha256", __file__),
            ("auth_runner_sha256", auth_eval.__file__),
            ("core_runner_sha256", core_eval.__file__),
            ("trace_runner_sha256", ROOT / "tools/reading_trace.py"),
            ("tasks_sha256", ROOT / "evals/core/tasks.json"),
        ):
            metadata[key] = hashlib.sha256(Path(name).read_bytes()).hexdigest()
        metadata["runner_source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        contract = core_eval.trial_contract()
        contract.prompt_builder = prompt
        checkpoint(
            output / "progress.json",
            summarize(rows, metadata, planned_total=len(trials)),
        )
        for stack, repeat, condition in trials:
            name = f"{stack}-{condition}-trial-{repeat}"
            result = auth_eval.run_trial(
                ROOT,
                output / name,
                stack,
                condition,
                args.timeout,
                model=args.model,
                template=template,
                source_metadata=metadata,
                tasks=tasks,
                repeat=repeat,
                sequence=len(rows) + 1,
                contract=contract,
            )
            retained = output / name
            trace = retained / "trace.jsonl"
            result["original_http_passed"] = result["passed"]
            result["original_error_code"] = result["error_code"]
            rows.append(result)
            try:
                original_result = (retained / "result.json").read_bytes()
                result["original_result_sha256"] = hashlib.sha256(
                    original_result
                ).hexdigest()
                result["prompt_sha256"] = hashlib.sha256(
                    prompt(stack, args.source_commit, tasks, condition).encode()
                ).hexdigest()
                result["reading_evidence"] = reading_evidence(
                    trace, stack, retained / "snapshot"
                )
                result["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
                result["static_reuse"] = static_reuse(
                    retained / "snapshot/generated",
                    auth_eval.fingerprint(template),
                    stack,
                    args.source_commit,
                )
            except (EvalError, OSError, ValueError, TypeError, KeyError) as exc:
                result["passed"] = False
                result["error_code"] = "postprocessing-failed"
                result["postprocessing_error"] = type(exc).__name__
            if result["original_error_code"] == "agent-failed":
                errors = (retained / "agent.log").read_text(errors="replace")
                blocked = terminal_block_reason(trace, errors)
            auth_eval.write_json(retained / "analysis.json", result)
            report = summarize(rows, metadata, planned_total=len(trials))
            report["blocked"] = blocked
            checkpoint(output / "progress.json", report)
            print(
                f"{len(rows)}/{len(trials)} {stack}/{condition}/r{repeat}: "
                f"{'PASS' if result['passed'] else result['error_code']}",
                flush=True,
            )
            if blocked:
                break
        report = summarize(rows, metadata, planned_total=len(trials))
        report["blocked"] = blocked
        report["complete"] = len(rows) == len(trials) and blocked is None
        auth_eval.write_json(output / "summary.json", report)
    print(
        f"Completed {len(rows)}/{len(trials)} model calls; {report['passed']} passed.",
        flush=True,
    )
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
