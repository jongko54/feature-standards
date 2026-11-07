"""Conservative command/document-reference evidence, never model reasoning evidence."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
from pathlib import Path, PurePosixPath

PROFILES = {
    "auth": "browser-session-v1",
    "authorization": "rbac-v1",
    "listing": "offset-list-v1",
}
AUTH_ROOTS = {
    "python": "python-fastapi",
    "go": "go-net-http",
    "java": "java-spring",
    "rust": "rust-axum",
}
LIMITS = [
    "Observed CLI argv and estimated document references do not prove model understanding, skill activation, internal reasoning or runtime API reuse.",
    "Document reads/searches are conservative command estimates; ranges, truncation and output consumption are not measured. A hash identifies corresponding snapshot bytes, not bytes consumed.",
    "Only simple commands and && chains are supported. Other shell control, substitutions, heredocs, pipelines, Node -e and indirect scripts remain unclassified; coverage is incomplete.",
    "Static API call evidence and independent HTTP outcomes must be reported separately; neither proves complete anti-copy protection or production security.",
]


def _commands(command):
    if not isinstance(command, str):
        raise TypeError("invalid-command-type")
    outer = shlex.split(command)
    if outer and Path(outer[0]).name in {"sh", "bash", "zsh"}:
        if len(outer) != 3 or outer[1] not in {"-c", "-lc"}:
            raise ValueError("unsupported-shell-wrapper")
        command = outer[2]
    if any(character in command for character in "\n\r`$"):
        raise ValueError("unsupported-shell-expansion")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    commands, current = [], []
    for token in lexer:
        if token == "&&":
            if not current:
                raise ValueError("empty-shell-command")
            commands.append(current)
            current = []
        elif token and all(character in ";&|<>()" for character in token):
            raise ValueError("unsupported-shell-control")
        else:
            current.append(token)
    if not current:
        raise ValueError("empty-shell-command")
    commands.append(current)
    if any(
        argv[0]
        in {
            "cd",
            "pushd",
            "popd",
            "builtin",
            "eval",
            "source",
            ".",
            "exec",
            "command",
            "export",
            "alias",
            "unset",
            "set",
            "env",
        }
        for argv in commands
    ):
        raise ValueError("untracked-working-directory")
    return commands


def _relative(value, snapshot, original_snapshot=None):
    if any(character in value for character in "*?[]{}$`\n\r") or "\\" in value:
        return None
    if value.startswith("/"):
        if snapshot is not None and value.startswith(str(snapshot) + "/"):
            relative = value[len(str(snapshot)) + 1 :]
        elif original_snapshot is not None and value.startswith(
            original_snapshot + "/"
        ):
            relative = value[len(original_snapshot) + 1 :]
        else:
            return None
    else:
        relative = "generated/" + value
    relative = posixpath.normpath(relative)
    if relative.startswith(("../", "/")) or relative in {".", ".."}:
        return None
    return relative


def _cli(argv, stack, snapshot, original_snapshot=None):
    if (
        len(argv) < 2
        or Path(argv[0]).name != "node"
        or _relative(argv[1], snapshot, original_snapshot)
        != "catalog/package/src/cli.mjs"
    ):
        return None
    if argv[2:] == ["list"]:
        return ("list", None)
    if len(argv) < 3 or argv[2] != "context":
        return ("unmatched", None)
    values, compact, index = {}, False, 3
    while index < len(argv):
        flag = argv[index]
        if flag == "--compact" and not compact:
            compact = True
            index += 1
        elif (
            flag in {"--feature", "--profile", "--stack"}
            and flag not in values
            and index + 1 < len(argv)
        ):
            values[flag] = argv[index + 1]
            index += 2
        else:
            return ("unmatched", None)
    feature = values.get("--feature")
    if (
        values.get("--stack") != stack
        or feature not in PROFILES
        or values.get("--profile") != PROFILES[feature]
    ):
        return ("unmatched", None)
    return ("compact_context" if compact else "full_context", feature)


def _reader(argv):
    command, args = Path(argv[0]).name, argv[1:]
    if command == "cat":
        if any(
            arg.startswith("-")
            and arg not in {"--", "-n", "-b", "-s", "-v", "-A", "-E", "-T"}
            for arg in args
        ):
            return None
        return "read", [arg for arg in args if not arg.startswith("-")]
    if command in {"head", "tail"}:
        files, index = [], 0
        while index < len(args):
            arg = args[index]
            if arg in {"-n", "-c", "--lines", "--bytes"}:
                if index + 1 >= len(args) or not re.fullmatch(
                    r"[+-]?\d+", args[index + 1]
                ):
                    return None
                index += 2
                continue
            if (
                arg.startswith("-")
                and arg not in {"--", "-q", "-v"}
                and not re.fullmatch(r"-\d+", arg)
            ):
                return None
            if not arg.startswith("-"):
                files.append(arg)
            index += 1
        return "read", files
    if command == "sed":
        if args and args[0] == "-n":
            args = args[1:]
        if not args or not re.fullmatch(r"(?:\d+(?:,[\d$]+)?)?p", args[0]):
            return None
        return "read", args[1:]
    if command == "rg":
        if "--files" in args:
            return "discovery", []
        positional, index, pattern = [], 0, False
        while index < len(args):
            arg = args[index]
            if arg in {
                "-e",
                "--regexp",
                "-g",
                "--glob",
                "-t",
                "--type",
                "--max-count",
                "-m",
            }:
                if index + 1 >= len(args):
                    return None
                pattern |= arg in {"-e", "--regexp"}
                index += 2
                continue
            if arg.startswith("-") and arg not in {
                "--",
                "-n",
                "-i",
                "-S",
                "-s",
                "-l",
                "-U",
                "--hidden",
                "--line-number",
                "--no-heading",
            }:
                return None
            if not arg.startswith("-"):
                positional.append(arg)
            index += 1
        return "search", positional if pattern else positional[1:]
    return None


def _kind(path, stack):
    source = path.removeprefix("catalog/package/snapshot/")
    if source == "README.md":
        return "manual_readme"
    if source in {
        f"implementations/{AUTH_ROOTS[stack]}/README.md",
        f"libraries/{stack}/README.md",
    }:
        return "public_api_guide"
    consumers = {f"examples/core-{stack}/", f"examples/consumer-{stack}/"}
    if stack == "python":
        consumers.add("examples/consumer-python-react/")
    if any(source.startswith(prefix) for prefix in consumers) and PurePosixPath(
        source
    ).suffix in {".md", ".py", ".go", ".rs", ".java", ".toml", ".xml"}:
        return "consumer"
    if source.startswith(
        ("skills/integrate-core/", "skills/integrate-auth/")
    ) and source.endswith(".md"):
        return "skill"
    if source.startswith("features/") and source.endswith((".md", ".json", ".sql")):
        return "specification"
    if source.startswith("docs/") and source.endswith((".md", ".json")):
        return "documentation"
    return None


def _digest(snapshot, relative):
    if snapshot is None:
        return None
    path = snapshot / relative
    if any(item.is_symlink() for item in (path, *path.parents)):
        return None
    try:
        return (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file() and path.stat().st_size <= 2_000_000
            else None
        )
    except OSError:
        return None


def _original_snapshot(events):
    proven = set()
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if (
            not isinstance(item, dict)
            or item.get("type") != "command_execution"
            or type(item.get("exit_code")) is not int
            or item["exit_code"] != 0
            or item.get("status", "completed") != "completed"
        ):
            continue
        try:
            commands = _commands(item.get("command"))
        except (ValueError, TypeError):
            continue
        output = item.get("aggregated_output")
        if commands[0] == ["pwd"] and isinstance(output, str):
            first = next(
                (line.strip() for line in output.splitlines() if line.strip()), ""
            )
            if first.startswith("/") and first.endswith("/snapshot/generated"):
                proven.add(first.removesuffix("/generated"))
    return proven.pop() if len(proven) == 1 else None


def reading_evidence(trace: Path, stack: str, snapshot: Path | None = None) -> dict:
    if stack not in AUTH_ROOTS:
        raise ValueError("unsupported-stack")
    snapshot = snapshot.resolve() if snapshot is not None else None
    result = {
        "list": 0,
        "full_context": 0,
        "compact_context": 0,
        "by_feature": {
            feature: {"full_context": 0, "compact_context": 0, "failed_cli_attempts": 0}
            for feature in PROFILES
        },
        "failed_cli_attempts": 0,
        "unmatched_cli_attempts": 0,
        "doc_read_commands": 0,
        "doc_search_commands": 0,
        "documents": [],
        "unclassified_commands": 0,
        "malformed_events": 0,
        "evidence_kind": "observed-command-and-document-reference-evidence",
        "limits": list(LIMITS),
    }
    documents, seen, events = {}, set(), []
    with trace.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                events.append(json.loads(line))
            except ValueError:
                result["malformed_events"] += 1
    original_snapshot = _original_snapshot(events)
    for event in events:
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
        if isinstance(item.get("id"), str):
            key = (str(event.get("thread_id")), item["id"])
            if key in seen:
                continue
            seen.add(key)
        code, status = item.get("exit_code"), item.get("status", "completed")
        success = type(code) is int and code == 0 and status == "completed"
        failed = (type(code) is int and code != 0) or status == "failed"
        try:
            commands = _commands(item.get("command", ""))
        except (ValueError, TypeError):
            result["unclassified_commands"] += 1
            continue
        if not success and len(commands) != 1:
            result["unclassified_commands"] += 1
            continue
        for argv in commands:
            cli = _cli(argv, stack, snapshot, original_snapshot)
            if cli is not None:
                mode, feature = cli
                if failed:
                    result["failed_cli_attempts"] += 1
                    if feature is not None:
                        result["by_feature"][feature]["failed_cli_attempts"] += 1
                elif success:
                    if mode == "unmatched":
                        result["unmatched_cli_attempts"] += 1
                    else:
                        result[mode] += 1
                        if feature is not None:
                            result["by_feature"][feature][mode] += 1
                else:
                    result["unclassified_commands"] += 1
                continue
            reader = _reader(argv)
            if not success or reader is None:
                result["unclassified_commands"] += 1
                continue
            operation, paths = reader
            matched = set()
            for value in paths:
                relative = _relative(value, snapshot, original_snapshot)
                kind = _kind(relative, stack) if relative else None
                if kind and relative not in matched:
                    matched.add(relative)
                    document = documents.setdefault(
                        relative,
                        {
                            "path": relative,
                            "kind": kind,
                            "sha256": _digest(snapshot, relative),
                            "read_commands": 0,
                            "search_commands": 0,
                        },
                    )
                    document[operation + "_commands"] += 1
            if matched:
                result["doc_" + operation + "_commands"] += 1
    result["documents"] = [documents[key] for key in sorted(documents)]
    return result
