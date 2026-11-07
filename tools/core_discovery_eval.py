"""Observe implementation choices in four provided-repository HTTP tasks."""

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import auth_eval
import core_eval
import core_reading_eval as reading
from auth_eval import EvalError
from reading_trace import reading_evidence

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = """# Discovery workspace safety
Reference source bytes and catalog are read-only. Write application source only in generated/.
Use foreground servers and conventional local tool caches. Do not create background daemons.
Do not read account credentials, commit/push Git, publish, send mail, migrate databases or deploy.
"""
LIMITS = [
    "One observation per language in a provided repository is not external adoption or a population estimate.",
    "Implementation choice is unconstrained; HTTP success, static calls and exact file copies are separate evidence.",
    "Static calls and matching file bytes do not prove reachable runtime API use or model understanding.",
    "Conventional tool caches and files of 200 bytes or less are excluded from exact source-copy evidence.",
    "Do not pool these calls or tokens with the instructed reading experiment or infer a causal effect between them.",
    "Shared dependency/prompt caches, server model weights and host load are not controlled; missing usage/model identities remain unknown.",
]


def prompt(stack, commit, tasks, condition):
    language = dict(zip(auth_eval.STACKS, ("Python", "Go", "Java", "Rust")))[stack]
    return f"""Build a {language} HTTP application in generated/. Choose your implementation approach.
Reference material is available in the parent directory; its source revision is {commit}.
Listen on AUTH_HOST/AUTH_PORT and honor AUTH_ALLOWED_ORIGIN; grading uses loopback, AUTH_DEMO=true,
AUTH_COOKIE_SECURE=false, AUTH_STORE=memory and AUTH_ACCOUNT_LIFECYCLE=false. No database is needed.

HTTP session contract:
POST /auth/login accepts JSON email/password: demo@example.com / correct-horse-battery-staple.
Wrong credentials or unknown email =>401. Success =>200 with {{"user":{{"id":"demo-user","email":"demo@example.com"}},"csrfToken":"..."}}.
Set an HttpOnly fs_session cookie whose value is 43 URL-safe base64 characters; csrfToken is also 43 characters.
Each login creates independent random session/csrf values. GET /api/profile and GET /auth/me return {{"user":...}}.
Anonymous, forged and revoked cookies =>401 UNAUTHENTICATED. POST /auth/logout requires the matching
session's X-CSRF-Token; wrong or another session's token =>403 and preserves the session.
Valid logout =>204, revokes that cookie on all protected routes and leaves other sessions valid.

Product contract:
Serve GET /api/documents and GET /api/documents/{{id}} with this immutable server data:
{json.dumps(tasks["documents"], ensure_ascii=False)}
Return only id/name/score/active. Authenticate every product request before loading CURRENT membership
from the private JSON file named by CORE_MEMBERSHIP_FILE. Grading creates it after you finish and
rewrites it between requests; do not create or cache it. Its valid object is
{{"subjectId":"demo-user","tenantId":"tenant-a","roles":["viewer"]}}; roles may be [].
Viewer may list its tenant collection but may read only its own documents. Restrict visibility before
filters, totals, sort and slicing. Subject mismatch or insufficient permission =>403 FORBIDDEN.
Missing and inaccessible document IDs both =>403. Never trust HTTP role/tenant/subject headers or input.
Missing/unreadable/malformed membership JSON or {{"unavailable":true}} =>503 AUTHORIZATION_UNAVAILABLE.
Valid restored membership must work on the next request. No public provider-control endpoints.

Listing query contract (original raw query before coercion): max 2048 UTF-8 bytes and 16 pairs;
form-decode once, then reject duplicate/unknown keys, empty pairs, malformed escapes or invalid UTF-8/control characters.
limit defaults20/range1..100; offset defaults0/range0..10000; canonical unsigned decimal only.
sort allows id/name/score/active, optionally '-' descending, default id ascending; non-ID ties use ID ascending.
filter.name is exact nonempty Unicode (<=256 scalars/1024 bytes); filter.score is canonical signed
safe integer (+/-9007199254740991, no plus/leading zero/-0); filter.active is exactly true/false.
Return {{items,total,limit,offset,nextOffset}}; total counts only visible filtered rows; nextOffset is null at the end.
Out-of-range offsets return empty items with unchanged total. Invalid query =>400 INVALID_LIST_QUERY.
All product responses require Cache-Control:no-store and X-Content-Type-Options:nosniff.
Errors use {{"error":{{"code":"FIXED_CODE","message":"Request could not be completed."}}}};
never echo raw query, private provider text or file paths.

Write run.json as {{"build":[{{"argv":["program","argument"],"cwd":"."}}],"start":{{"argv":["program","argument"],"cwd":"."}}}}.
At most8 build commands, argv arrays, cwd within generated/; foreground server only.
Write integration.json exactly {{"stack":"{stack}","profile":"browser-session-v1","source_commit":"{commit}"}}.
Grading builds/starts the app independently and applies the same 143 HTTP assertions. Do not run full repository tests.
"""


def program_files(generated):
    auth_eval.no_symlink(generated)
    if not generated.is_dir():
        raise EvalError("discovery-invalid-program-directory")
    for path in generated.rglob("*"):
        if any(
            p in core_eval.CORE_IGNORED_PARTS for p in path.relative_to(generated).parts
        ):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise EvalError("generated-source-symlink")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise EvalError("discovery-nonregular-source")
        if path.stat().st_size > 2_000_000:
            raise EvalError("generated-source-too-large")
        yield path


def boundary_check(generated, stack, source, commit):
    if auth_eval.fingerprint(generated.parent) != source:
        raise EvalError("source-modified")
    list(program_files(generated))
    provenance = generated / "integration.json"
    if provenance.stat().st_size > 64_000 or json.loads(provenance.read_text()) != {
        "stack": stack,
        "profile": "browser-session-v1",
        "source_commit": commit,
    }:
        raise EvalError("provenance-mismatch")
    auth_eval.load_run(generated)


def copy_evidence(generated, source):
    matches = {"auth": set(), "core": set()}
    for path in program_files(generated):
        data = path.read_bytes()
        if len(data) <= 200:
            continue
        digest = hashlib.sha256(data).hexdigest()
        for name, expected in source.items():
            category = (
                "auth"
                if name.startswith("implementations/")
                else "core"
                if name.startswith("libraries/")
                else None
            )
            if (
                category
                and Path(name).suffix in {".py", ".go", ".java", ".rs", ".mjs", ".ts"}
                and not {"test", "tests", "fixtures"}.intersection(Path(name).parts)
                and "test" not in Path(name).name.lower()
                and expected == digest
            ):
                matches[category].add(name)
    return {k: sorted(v) for k, v in matches.items()} | {
        "kind": "exact-source-file-match-over-200-bytes",
        "api_reuse_proven": False,
    }


def neutralize(template, metadata):
    instructions = template / "AGENTS.md"
    if instructions.exists():
        instructions.chmod(0o600)
    instructions.write_text(INSTRUCTIONS)
    instructions.chmod(0o444)
    files = auth_eval.fingerprint(template)
    return metadata | {
        "upstream_source_sha256": metadata["source_sha256"],
        "upstream_implementation_source_sha256": metadata[
            "implementation_source_sha256"
        ],
        "instruction_overlay": "neutral-discovery",
        "discovery_agents_sha256": hashlib.sha256(
            instructions.read_bytes()
        ).hexdigest(),
        "source_sha256": auth_eval.digest_hashes(files),
        "implementation_source_sha256": auth_eval.digest_hashes(
            {k: v for k, v in files.items() if not k.startswith("catalog/")}
        ),
    }


def feature_evidence(generated, source, stack, commit):
    auth = {"passed": False, "runtime_causality_proven": False}
    try:
        metadata = core_eval.dependency_evidence(generated) if stack == "java" else ""
        auth_eval.reuse_check(
            generated,
            stack,
            source,
            commit,
            ignored_parts=core_eval.CORE_IGNORED_PARTS,
            metadata_evidence=metadata,
        )
        auth["passed"] = True
    except (EvalError, OSError, ValueError, SyntaxError):
        pass
    text = "\n".join(
        p.read_text(errors="replace")
        for p in program_files(generated)
        if p.suffix in {".py", ".go", ".java", ".rs", ".toml", ".xml"}
    )
    hints = {
        "authorization": (
            "feature_standards.authorization",
            "NewPolicy",
            "AuthorizationPolicy",
            "Policy",
        ),
        "listing": (
            "feature_standards.listing",
            "ParseQuery",
            "parseQuery",
            "parse_query",
        ),
    }
    return {
        "auth": auth,
        **{
            k: "candidate" if any(name in text for name in names) else False
            for k, names in hints.items()
        },
        "kind": "weak-namespace-or-public-name-signals",
        "route_review": "pending-independent-source-review",
    }


def summarize(rows, metadata, planned, blocked=None):
    public = []
    for row in rows:
        item = {
            k: row.get(k)
            for k in (
                "stack",
                "sequence",
                "passed",
                "original_http_passed",
                "original_error_code",
                "error_code",
                "source_unchanged",
                "original_result_sha256",
                "prompt_sha256",
                "trace_sha256",
                "agent_seconds",
                "elapsed_seconds",
                "model_selection",
                "cli_version",
            )
        }
        item.update(
            tokens=reading.tokens(row),
            http_assertions=len(row.get("checks", [])),
            reported_models=(row.get("agent") or {}).get("models", []),
            static_reuse={
                "passed": bool((row.get("static_reuse") or {}).get("passed")),
                "runtime_causality_proven": False,
            },
            auth_reuse={
                "passed": bool(
                    ((row.get("feature_evidence") or {}).get("auth") or {}).get(
                        "passed"
                    )
                ),
                "runtime_causality_proven": False,
            },
            feature_hints={
                k: (row.get("feature_evidence") or {}).get(k)
                for k in ("authorization", "listing")
            },
            route_review="pending-independent-source-review",
            exact_copy_counts={
                k: len((row.get("copy_evidence") or {}).get(k, []))
                for k in ("auth", "core")
            },
            reading_counts={
                k: (row.get("reading_evidence") or {}).get(k)
                for k in (
                    "list",
                    "full_context",
                    "compact_context",
                    "doc_read_commands",
                    "doc_search_commands",
                    "unclassified_commands",
                )
            },
        )
        public.append(item)
    return {
        "suite": "core-discovery-v1",
        **metadata,
        "limits": LIMITS,
        "planned_model_calls": planned,
        "actual_model_calls": len(rows),
        "passed": sum(bool(r["passed"]) for r in rows),
        "blocked": blocked,
        "complete": len(rows) == planned and blocked is None,
        "runs": public,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stack", choices=(*auth_eval.STACKS, "all"), default="all")
    args = parser.parse_args()
    if (
        not re.fullmatch(auth_eval.MODEL_PATTERN, args.model)
        or not re.fullmatch(r"[a-f0-9]{40}", args.source_commit)
        or not 1 <= args.timeout <= 600
        or shutil.which("codex") is None
    ):
        parser.error("Fixed model/source, timeout1..600 and Codex CLI required")
    archive, catalog = reading.local_artifact(
        args.artifact, args.artifact_sha256, args.source_commit
    )
    output = auth_eval.prepare_output(args.output)
    task_bytes = (ROOT / "evals/core/tasks.json").read_bytes()
    tasks = json.loads(task_bytes)
    stacks = auth_eval.STACKS if args.stack == "all" else (args.stack,)
    rows, blocked = [], None
    with tempfile.TemporaryDirectory(prefix="feature-discovery-source-") as temporary:
        template = Path(temporary).resolve() / "source"
        metadata = catalog | neutralize(
            template,
            core_eval.freeze_sources(
                ROOT, template, archive, commit=args.source_commit
            ),
        )
        metadata.update(
            requested_model=args.model,
            timeout_seconds=args.timeout,
            tasks_sha256=hashlib.sha256(task_bytes).hexdigest(),
        )
        for key, path in (
            ("runner_sha256", __file__),
            ("auth_runner_sha256", auth_eval.__file__),
            ("core_runner_sha256", core_eval.__file__),
            ("reading_runner_sha256", reading.__file__),
            ("trace_runner_sha256", ROOT / "tools/reading_trace.py"),
            ("source_evidence_sha256", ROOT / "tools/source_evidence.py"),
        ):
            metadata[key] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        metadata["runner_source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        source = auth_eval.fingerprint(template)
        contract = core_eval.trial_contract()
        contract.prompt_builder, contract.artifact_checker = prompt, boundary_check
        contract.profile = "discovery-http-v1"
        reading.checkpoint(
            output / "progress.json", summarize(rows, metadata, len(stacks))
        )
        for stack in stacks:
            name = f"{stack}-discovery-trial-1"
            result = auth_eval.run_trial(
                ROOT,
                output / name,
                stack,
                "discovery",
                args.timeout,
                model=args.model,
                template=template,
                source_metadata=metadata,
                tasks=tasks,
                sequence=len(rows) + 1,
                contract=contract,
            )
            rows.append(result)
            result["original_http_passed"], result["original_error_code"] = (
                result["passed"],
                result["error_code"],
            )
            retained = output / name
            trace = retained / "trace.jsonl"
            try:
                result["original_result_sha256"] = hashlib.sha256(
                    (retained / "result.json").read_bytes()
                ).hexdigest()
                result["prompt_sha256"] = hashlib.sha256(
                    prompt(stack, args.source_commit, tasks, "discovery").encode()
                ).hexdigest()
                result["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
                result["copy_evidence"] = copy_evidence(
                    retained / "snapshot/generated", source
                )
                result["static_reuse"] = reading.static_reuse(
                    retained / "snapshot/generated", source, stack, args.source_commit
                )
                result["feature_evidence"] = feature_evidence(
                    retained / "snapshot/generated", source, stack, args.source_commit
                )
                result["reading_evidence"] = reading_evidence(
                    trace, stack, retained / "snapshot"
                )
            except (EvalError, OSError, ValueError, TypeError, KeyError):
                result["passed"], result["error_code"] = False, "postprocessing-failed"
            blocked = reading.terminal_block_reason(
                trace,
                (retained / "agent.log").read_text(errors="replace")
                if result["original_error_code"] is not None
                else "",
            )
            auth_eval.write_json(retained / "analysis.json", result)
            reading.checkpoint(
                output / "progress.json",
                summarize(rows, metadata, len(stacks), blocked),
            )
            print(
                f"{len(rows)}/{len(stacks)} {stack}/discovery: {'PASS' if result['passed'] else result['error_code']}",
                flush=True,
            )
            if blocked:
                break
        report = summarize(rows, metadata, len(stacks), blocked)
        auth_eval.write_json(output / "summary.json", report)
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
