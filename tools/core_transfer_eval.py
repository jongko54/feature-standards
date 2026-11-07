"""Compare compact routing with a brief on the fixed similar notes task."""

from pathlib import Path

import auth_eval
import core_eval
import core_reading_eval as reading
from auth_eval import EvalError

CONDITIONS = ("catalog_compact", "brief")
PROFILE = "notes-auth-rbac-offset-v1"
LIMITS = [
    "This is the fixed similar notes task: documents routes and permission names change to notes; it is not randomized.",
    "One observation per language/condition (eight calls) cannot establish generalization or a population effect.",
    "Do not pool tokens or outcomes with the original 24-call reading experiment or the separate discovery observations.",
    "Both conditions receive the same source, candidate archive, task and host; only initial reading guidance differs. Shared caches and prompt caches remain uncontrolled.",
]


def source_validator(template, metadata, stacks):
    if metadata.get("catalog_version") != "0.4.0":
        raise EvalError("transfer-brief-source-mismatch")
    try:
        for stack in stacks:
            if stack not in auth_eval.STACKS:
                raise EvalError("unsupported-transfer-selection")
            relative = f"docs/ai-briefs/{stack}.md"
            original = template / relative
            packaged = template / "catalog/package/snapshot" / relative
            for path in (original, packaged):
                auth_eval.no_symlink(path)
                if not path.is_file() or not 0 < path.stat().st_size <= 20_000:
                    raise EvalError("transfer-brief-source-mismatch")
            data = original.read_bytes()
            data.decode("utf-8", errors="strict")
            if data != packaged.read_bytes():
                raise EvalError("transfer-brief-source-mismatch")
    except (OSError, UnicodeError) as exc:
        raise EvalError("transfer-brief-source-mismatch") from exc


def prompt(stack, commit, tasks, condition):
    if condition not in CONDITIONS or stack not in auth_eval.STACKS:
        raise EvalError("unsupported-transfer-selection")
    original = reading.prompt(stack, commit, tasks, "catalog_compact")
    header, separator, body = original.partition("\n\nCurrent directory")
    if not separator:
        raise EvalError("upstream-task-shape-changed")
    body = (
        body.replace("/api/documents", "/api/notes")
        .replace("documents:list", "notes:list")
        .replace("documents:read", "notes:read")
    )
    if condition == "brief":
        header = (
            f"{tasks['stacks'][stack]}\n"
            f"First read ../catalog/package/snapshot/docs/ai-briefs/{stack}.md. "
            "Use the brief's references for this task; expand only as needed."
        )
    return header + separator + body


def notes_path(path):
    prefix = "/api/documents"
    if path == prefix or path.startswith((prefix + "/", prefix + "?")):
        return "/api/notes" + path[len(prefix) :]
    return path


def notes_http_grade(port, origin, deadline, membership_file):
    """Translate only request paths during one serial grade, restoring on failure."""
    original = auth_eval.request

    def redirected(port, method, path, *args, **kwargs):
        return original(port, method, notes_path(path), *args, **kwargs)

    auth_eval.request = redirected
    try:
        return core_eval.core_http_grade(port, origin, deadline, membership_file)
    finally:
        auth_eval.request = original


def contract_factory():
    contract = core_eval.trial_contract()
    contract.profile = PROFILE
    contract.prompt_builder = prompt
    contract.http_grader = lambda generated, env, port, origin, deadline: (
        notes_http_grade(port, origin, deadline, Path(env["CORE_MEMBERSHIP_FILE"]))
    )
    return contract


# The shared runner hashes this protocol file separately and records this ID.
EXPERIMENT = {
    "id": "core-notes-reading-transfer-v1",
    "conditions": CONDITIONS,
    "prompt": prompt,
    "contract_factory": contract_factory,
    "source_file": __file__,
    "default_repeats": 1,
    "limits": LIMITS,
    "source_validator": source_validator,
}


def main():
    return reading.main(experiment=EXPERIMENT)


if __name__ == "__main__":
    raise SystemExit(main())
