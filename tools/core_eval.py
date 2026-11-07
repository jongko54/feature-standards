"""Evaluate auth + RBAC + listing against a fixed source and public CLI snapshot."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import auth_eval
from auth_eval import EvalError

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "752e4e498e0647684c57b6e2ec749da99eaa4b79"
CATALOG_VERSION = "0.3.2"
CATALOG_SHA256 = "b89882db7f1dc165e253b6cc3e4dd57a970fddd5626417e2c382992d30c1db18"
PROFILE = "auth-rbac-offset-v1"
SCOPES = {
    "implementations",
    "libraries",
    "examples",
    "features",
    "docs",
    "skills",
    "tools",
}
SHARED_INSTRUCTIONS = """# Evaluation workspace
Write application source only in generated/. Reference source and catalog/ are read-only.
Reuse the existing feature packages. Do not copy authentication/core implementations.
Do not commit, publish, migrate a database, send mail or create background daemons.
Use foreground server commands. Local toolchains and dependencies are available.
"""
VIEWER = {"subjectId": "demo-user", "tenantId": "tenant-a", "roles": ["viewer"]}


def _safe_member(member, *, package=False):
    name = member.name
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or any(part.startswith(".env") for part in path.parts)
        or any(part in auth_eval.IGNORED_PARTS for part in path.parts)
        or not (member.isfile() or member.isdir())
        or (package and (not path.parts or path.parts[0] != "package"))
        or member.size > 2_000_000
    ):
        raise EvalError("unsafe-archive-member")
    return path


def extract_archive(data: bytes, destination: Path) -> None:
    """Only bounded, regular package files; no tar extraction links or traversal."""
    if destination.exists():
        raise EvalError("archive-destination-exists")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 512 or sum(member.size for member in members) > 10_000_000:
            raise EvalError("archive-too-large")
        names = set()
        validated = []
        for member in members:
            path = _safe_member(member, package=True)
            if str(path).casefold() in names:
                raise EvalError("duplicate-archive-member")
            names.add(str(path).casefold())
            validated.append((member, path))
        destination.mkdir(mode=0o700)
        for member, path in validated:
            target = destination / str(path)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with auth_eval.private_file(target) as output:
                    output.write(archive.extractfile(member).read())
                target.chmod(0o444)


def _public_get(url: str, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "registry.npmjs.org"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise EvalError("untrusted-registry-url")
    with urlopen(
        Request(url, headers={"User-Agent": "feature-standards-core-eval/1"}),
        timeout=20,
    ) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise EvalError("registry-response-too-large")
    return data


def catalog_archive(root: Path = ROOT) -> tuple[bytes, dict]:
    receipt_data = (root / "docs/npm-release-0.3.2.json").read_bytes()
    receipt = json.loads(receipt_data)
    if (
        receipt.get("name") != "feature-standards"
        or receipt.get("version") != CATALOG_VERSION
        or receipt.get("sourceCommit") != SOURCE_COMMIT
        or receipt.get("localArtifactSha256") != CATALOG_SHA256
        or receipt.get("registry_verified") is not True
        or receipt.get("public_download_verified") is not True
    ):
        raise EvalError("catalog-receipt-mismatch")
    metadata = json.loads(
        _public_get("https://registry.npmjs.org/feature-standards/0.3.2", 1_000_000)
    )
    if (
        metadata.get("name") != "feature-standards"
        or metadata.get("version") != CATALOG_VERSION
    ):
        raise EvalError("catalog-metadata-mismatch")
    archive = _public_get(metadata["dist"]["tarball"], 5_000_000)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
    if (
        hashlib.sha256(archive).hexdigest() != CATALOG_SHA256
        or integrity != receipt["dist"]["integrity"]
        or integrity != metadata["dist"]["integrity"]
    ):
        raise EvalError("catalog-artifact-mismatch")
    return archive, {
        "catalog_version": CATALOG_VERSION,
        "catalog_sha256": CATALOG_SHA256,
        "catalog_integrity": integrity,
        "catalog_receipt_sha256": hashlib.sha256(receipt_data).hexdigest(),
        "catalog_metadata_url": "https://registry.npmjs.org/feature-standards/0.3.2",
        "catalog_public_download_verified": True,
    }


def freeze_sources(
    root: Path, destination: Path, catalog: bytes, *, commit=SOURCE_COMMIT
):
    """Read Git objects once, ignoring the concurrently edited working tree."""
    if destination.exists() or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvalError("invalid-source-destination-or-commit")
    data = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=root)
    destination.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if not path.parts or (
                path.parts[0] not in SCOPES
                and str(path) not in {"README.md", "LICENSE", "feature-standards.json"}
            ):
                continue
            if (
                any(
                    part in auth_eval.IGNORED_PARTS or part.startswith(".env")
                    for part in path.parts
                )
                or path.parts[:2] == ("docs", "superpowers")
                or str(path).startswith("docs/validation-ai")
            ):
                continue
            path = _safe_member(member)
            target = destination / str(path)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    (destination / "AGENTS.md").write_text(SHARED_INSTRUCTIONS)
    implementation = auth_eval.fingerprint(destination)
    extract_archive(catalog, destination / "catalog")
    for path in destination.rglob("*"):
        if path.is_file():
            # Preserve executable wrappers while making source bytes read-only.
            executable = path.suffix in {".sh"} or path.name in {"mvnw"}
            path.chmod(0o555 if executable else 0o444)
    source = auth_eval.fingerprint(destination)
    return {
        "source_commit": commit,
        "source_dirty": False,
        "implementation_source_sha256": auth_eval.digest_hashes(implementation),
        "source_sha256": auth_eval.digest_hashes(source),
        "catalog_snapshot_sha256": auth_eval.digest_hashes(
            auth_eval.fingerprint(destination / "catalog")
        ),
    }


def create_membership_file(generated: Path, env: dict, *, filename=None) -> Path:
    filename = filename or (".core-membership-" + secrets.token_hex(12) + ".json")
    if Path(filename).name != filename or filename in {".", ".."}:
        raise EvalError("invalid-membership-path")
    path = generated / filename
    try:
        auth_eval.no_symlink(path)
        auth_eval.write_json(path, VIEWER)
    except (OSError, EvalError) as exc:
        raise EvalError("membership-fixture-already-exists-or-unsafe") from exc
    env["CORE_MEMBERSHIP_FILE"] = str(path)
    return path


def update_membership(path: Path, value, *, raw=False):
    auth_eval.no_symlink(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600:
        raise EvalError("unsafe-membership-fixture")
    descriptor = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "wb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise EvalError("membership-fixture-replaced")
        stream.truncate(0)
        stream.write(value.encode() if raw else json.dumps(value).encode())
        stream.flush()
        os.fsync(stream.fileno())


def core_http_grade(port, origin, deadline, membership_file):
    checks = auth_eval.http_grade(port, origin, deadline)

    def expect(name, actual, expected):
        if actual != expected:
            raise EvalError(name)
        checks.append(name)

    def get(path, *, cookie=None, headers=None):
        return auth_eval.request(
            port, "GET", path, origin, deadline, cookie=cookie, extra_headers=headers
        )

    def private(headers):
        headers = {key.lower(): value for key, value in headers.items()}
        expect("core-no-store", headers.get("cache-control"), "no-store")
        expect("core-nosniff", headers.get("x-content-type-options"), "nosniff")

    def failure(response, status, code, name):
        actual, headers, body = response
        expect(name, actual, status)
        details = body.get("error") if isinstance(body, dict) else None
        expect(
            name + "-code",
            details.get("code") if isinstance(details, dict) else None,
            code,
        )
        if "private-provider-detail" in json.dumps(body) or str(
            membership_file
        ) in json.dumps(body):
            raise EvalError("core-private-error-disclosed")
        private(headers)

    for path in ("/api/documents", "/api/documents/own-a"):
        failure(get(path), 401, "UNAUTHENTICATED", "core-anonymous-401")
        failure(
            get(path, cookie="fs_session=forged"),
            401,
            "UNAUTHENTICATED",
            "core-forged-session-401",
        )
    status, headers, session = auth_eval.request(
        port,
        "POST",
        "/auth/login",
        origin,
        deadline,
        body={"email": "demo@example.com", "password": "correct-horse-battery-staple"},
    )
    expect("core-login-200", status, 200)
    cookie = next(
        (value for key, value in headers.items() if key.lower() == "set-cookie"), ""
    ).split(";", 1)[0]
    expect(
        "core-login-cookie",
        bool(re.fullmatch(r"fs_session=[A-Za-z0-9_-]{43}", cookie)),
        True,
    )
    csrf = session.get("csrfToken") if isinstance(session, dict) else None
    expect("core-login-csrf", isinstance(csrf, str) and len(csrf) == 43, True)
    own_a = {"id": "own-a", "name": "Alpha", "score": 2, "active": True}
    own_b = {"id": "own-b", "name": "Beta", "score": 2, "active": False}
    status, headers, body = get("/api/documents/own-a", cookie=cookie)
    expect("core-owner-200", status, 200)
    expect("core-public-document", body, own_a)
    private(headers)
    for identifier in ("other-owner", "other-tenant", "missing"):
        failure(
            get("/api/documents/" + identifier, cookie=cookie),
            403,
            "FORBIDDEN",
            "core-private-resource-403",
        )
    status, headers, body = get("/api/documents?sort=-score&limit=1", cookie=cookie)
    expect("core-list-200", status, 200)
    expect(
        "core-scoped-total", body.get("total") if isinstance(body, dict) else None, 2
    )
    expect(
        "core-stable-first-page",
        body,
        {"items": [own_a], "total": 2, "limit": 1, "offset": 0, "nextOffset": 1},
    )
    private(headers)
    expect(
        "core-next-page",
        get("/api/documents?sort=-score&limit=1&offset=1", cookie=cookie)[2],
        {"items": [own_b], "total": 2, "limit": 1, "offset": 1, "nextOffset": None},
    )
    expect(
        "core-offset-end",
        get("/api/documents?offset=100", cookie=cookie)[2],
        {"items": [], "total": 2, "limit": 20, "offset": 100, "nextOffset": None},
    )
    expect(
        "core-typed-filter",
        get("/api/documents?filter.active=true&filter.score=2", cookie=cookie)[2],
        {"items": [own_a], "total": 1, "limit": 20, "offset": 0, "nextOffset": None},
    )
    for hidden in ("Private", "Secret"):
        expect(
            "core-hidden-filter-total",
            get("/api/documents?filter.name=" + hidden, cookie=cookie)[2],
            {"items": [], "total": 0, "limit": 20, "offset": 0, "nextOffset": None},
        )
    for query in (
        "limit=01",
        "limit=1&%6cimit=2",
        "sort=unknown",
        "filter.active=1",
        "filter.score=02",
        "filter.name=%FF",
        "unknown=private-provider-detail",
        "limit=1&&offset=0",
    ):
        failure(
            get("/api/documents?" + query, cookie=cookie),
            400,
            "INVALID_LIST_QUERY",
            "core-invalid-query-400",
        )
    update_membership(membership_file, {**VIEWER, "roles": []})
    failure(
        get("/api/documents", cookie=cookie), 403, "FORBIDDEN", "core-revocation-403"
    )
    forged = {
        "X-Role": "admin",
        "X-Roles": "viewer",
        "X-Tenant-Id": "tenant-b",
        "X-Subject-Id": "other-user",
    }
    for path in ("/api/documents", "/api/documents/own-a"):
        failure(
            get(path, cookie=cookie, headers=forged),
            403,
            "FORBIDDEN",
            "core-forged-role-403",
        )
    update_membership(membership_file, VIEWER)
    expect(
        "core-membership-restored", get("/api/documents/own-a", cookie=cookie)[0], 200
    )
    update_membership(membership_file, {**VIEWER, "subjectId": "other-user"})
    for path in ("/api/documents", "/api/documents/own-a"):
        failure(get(path, cookie=cookie), 403, "FORBIDDEN", "core-subject-mismatch-403")
    for value, raw in (
        ({**VIEWER, "unavailable": True}, False),
        ("private-provider-detail", True),
    ):
        update_membership(membership_file, value, raw=raw)
        for path in ("/api/documents", "/api/documents/own-a"):
            failure(
                get(path, cookie=cookie),
                503,
                "AUTHORIZATION_UNAVAILABLE",
                "core-provider-failure-503",
            )
    update_membership(membership_file, VIEWER)
    expect("core-provider-recovery", get("/api/documents", cookie=cookie)[0], 200)
    expect(
        "core-logout-204",
        auth_eval.request(
            port, "POST", "/auth/logout", origin, deadline, cookie=cookie, csrf=csrf
        )[0],
        204,
    )
    for path in ("/api/documents", "/api/documents/own-a"):
        failure(get(path, cookie=cookie), 401, "UNAUTHENTICATED", "core-old-cookie-401")
    return checks


def core_reuse_check(generated, stack, source, commit):
    auth_eval.reuse_check(generated, stack, source, commit)
    digests = {
        digest
        for name, digest in source.items()
        if name.startswith("libraries/")
        and Path(name).suffix in {".py", ".go", ".java", ".rs"}
        and "test" not in name.lower()
    }
    texts, trees = [], []
    for path in generated.rglob("*"):
        if any(
            part in auth_eval.IGNORED_PARTS
            for part in path.relative_to(generated).parts
        ):
            continue
        if path.is_file() and path.suffix in {
            ".py",
            ".go",
            ".java",
            ".rs",
            ".toml",
            ".mod",
            ".xml",
        }:
            data = path.read_bytes()
            if len(data) > 200 and hashlib.sha256(data).hexdigest() in digests:
                raise EvalError("copied-core-source-file")
            text = data.decode()
            texts.append(text)
            if path.suffix == ".py":
                trees.append(ast.parse(text))
    if stack == "python":
        used = set()
        for tree in trees:
            imported, modules = {}, {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "feature_standards"
                ):
                    imported.update(
                        {alias.asname or alias.name: alias.name for alias in node.names}
                    )
                if isinstance(node, ast.Import):
                    modules.update(
                        {
                            alias.asname or alias.name: alias.name
                            for alias in node.names
                            if alias.name.startswith("feature_standards")
                        }
                    )
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in imported:
                        used.add(imported[node.func.id])
                    if isinstance(node.func, ast.Attribute):
                        name = node.func.value
                        while isinstance(name, ast.Attribute):
                            name = name.value
                        if isinstance(name, ast.Name) and name.id in modules:
                            used.add(node.func.attr)
        good = {"Policy", "parse_query", "page"}.issubset(used)
    else:
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", "\n".join(texts), flags=re.DOTALL)
        patterns = {
            "go": (
                r"libraries/go/authorization",
                r"libraries/go/listing",
                r"\bNewPolicy\b",
                r"\bDecide\b",
                r"\bParseQuery\b",
                r"\bPage\b",
            ),
            "java": (
                r"import\s+dev\.featurestandards\.core\.authorization",
                r"import\s+dev\.featurestandards\.core\.listing",
                r"feature-standards-core",
                r"\bdecide\s*\(",
                r"\bparseQuery\s*\(",
                r"\bpage\s*\(",
            ),
            "rust": (
                r"feature-standards-core\s*=",
                r"feature_standards_core",
                r"\bPolicy\b",
                r"\bdecide\s*\(",
                r"\bparse_query\s*\(",
                r"\bpage\s*\(",
            ),
        }
        good = all(re.search(pattern, text) for pattern in patterns[stack])
    if not good:
        raise EvalError("core-library-reuse-evidence-missing")


def prompt(stack, commit, tasks, condition):
    entry = (
        f"First run node ../catalog/package/src/cli.mjs list, then context for auth/browser-session-v1, authorization/rbac-v1 and listing/offset-list-v1 with --stack {stack}. Read the selected packagedDocuments and public API guides."
        if condition == "catalog"
        else "Start at ../README.md and the selected implementation/library public API guides and consumer examples. Locate the relevant contracts manually. The same catalog is available under ../catalog/package if you independently choose to use it."
    )
    return f"""{tasks["stacks"][stack]}
{entry}

Current directory generated/ is writable; ../ contains fixed read-only source at {commit}.
Both conditions receive the same source and verified feature-standards@0.3.2 catalog bytes.
Import the existing auth and core packages as local dependencies. Never copy their implementations.
Only create source under generated/. Use foreground servers and trusted local toolchains.
Keep /auth/* and GET /api/profile returning {{"user":{{"id":...,"email":...}}}} through the real existing session.
Use browser-session-v1 memory settings from AUTH_HOST, AUTH_PORT, AUTH_ALLOWED_ORIGIN and AUTH_*.
The grader injects demo=true/secure=false on loopback, and independently checks login/CSRF/logout/cookie revocation.

Add GET /api/documents and GET /api/documents/{{id}} using the published rbac-v1 and offset-list-v1 APIs.
Use this server-owned immutable product data: {json.dumps(tasks["documents"], ensure_ascii=False)}.
Return only id/name/score/active, never tenantId/ownerId.
Policy grants viewer documents:list at tenant scope and viewer documents:read at owner scope.
Every product request must authenticate first and load CURRENT membership from the private JSON file named by CORE_MEMBERSHIP_FILE.
The grader creates that file AFTER you finish and rewrites it BETWEEN requests; do not create it yourself or cache its contents.
Its valid object is {{"subjectId":"demo-user","tenantId":"tenant-a","roles":["viewer"]}}; roles may be [].
Compare subjectId with the actual authenticated user's ID. Mismatch or no permission =>403 FORBIDDEN.
Missing/unreadable/invalid JSON or {{"unavailable":true}} => generic503 AUTHORIZATION_UNAVAILABLE.
Never accept subject/tenant/roles from HTTP headers/query/body. No public test/control/provider routes.
Scope records by documents:read BEFORE totals, filters, sorting and pagination; inaccessible or missing IDs both403.
Pass raw query before framework coercion to the core parser: sort id/name/score/active, filters name/score/active, correctly typed.
Default/stable-tie paging and all query errors follow offset-list-v1. Invalid query=>400 INVALID_LIST_QUERY.
All product responses (including errors) require Cache-Control:no-store and X-Content-Type-Options:nosniff.
Use fixed generic error messages; never echo raw input, provider details or file paths.
No React, database, SMTP, deployment or full repository test run is needed.

Write run.json exactly {{"build":[{{"argv":["program","argument"],"cwd":"."}}],"start":{{"argv":["program","argument"],"cwd":"."}}}}.
Build accepts at most8 commands; cwd must stay within generated/. Use argv arrays, not shell command strings.
Write integration.json exactly {{"stack":"{stack}","profile":"browser-session-v1","source_commit":"{commit}"}}.
The grader builds/starts the program after your completion; don't spend time testing the full repository.
Do not ask questions, change reference source, Git commit/push, daemonize servers, or read account credentials.
Finish with a short description of generated files and run instructions.
"""


def trial_contract():
    return auth_eval.TrialContract(
        profile=PROFILE,
        prompt_builder=prompt,
        artifact_checker=core_reuse_check,
        prepare_grader=create_membership_file,
        http_grader=lambda generated, env, port, origin, deadline: core_http_grade(
            port, origin, deadline, Path(env["CORE_MEMBERSHIP_FILE"])
        ),
    )


def pair_order(conditions, repeat, stack_index, stack_count):
    """Balance pair order across stacks as well as repeated rounds."""
    return (
        conditions
        if (repeat * stack_count + stack_index) % 2 == 0
        else tuple(reversed(conditions))
    )


def entrypoint_references(trace: Path):
    counts = {"catalog_cli": 0, "manual_readme": 0}
    for line in trace.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {}) if isinstance(event, dict) else {}
        if (
            isinstance(item, dict)
            and item.get("type") == "command_execution"
            and event.get("type") == "item.completed"
        ):
            text = item.get("command", "")
            if isinstance(text, str):
                counts["catalog_cli"] += "catalog/package/src/cli.mjs" in text
                counts["manual_readme"] += "README.md" in text
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", choices=(*auth_eval.STACKS, "all"), required=True)
    parser.add_argument(
        "--condition", choices=("baseline", "catalog", "both"), required=True
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        not re.fullmatch(auth_eval.MODEL_PATTERN, args.model)
        or not 1 <= args.timeout <= 600
    ):
        parser.error("A fixed model identifier and timeout1..600 are required")
    if shutil.which("codex") is None:
        parser.error("codex CLI is required")
    try:
        output = auth_eval.prepare_output(args.output)
        tasks_bytes = (ROOT / "evals/core/tasks.json").read_bytes()
        tasks = json.loads(tasks_bytes)
        archive, catalog_metadata = catalog_archive()
        stacks = auth_eval.STACKS if args.stack == "all" else (args.stack,)
        conditions = (
            ("baseline", "catalog") if args.condition == "both" else (args.condition,)
        )
        results = []
        blocked = None
        with tempfile.TemporaryDirectory(prefix="feature-core-eval-frozen-") as frozen:
            template = Path(frozen).resolve() / "source"
            metadata = freeze_sources(ROOT, template, archive)
            metadata.update(catalog_metadata)
            metadata.update(
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                auth_runner_sha256=hashlib.sha256(
                    Path(auth_eval.__file__).read_bytes()
                ).hexdigest(),
                tasks_sha256=hashlib.sha256(tasks_bytes).hexdigest(),
            )
            for repeat in range(args.repeats):
                for stack_index, stack in enumerate(stacks):
                    order = pair_order(conditions, repeat, stack_index, len(stacks))
                    for condition in order:
                        name = f"{stack}-{condition}-trial-{repeat + 1}"
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
                            repeat=repeat + 1,
                            sequence=len(results) + 1,
                            contract=trial_contract(),
                        )
                        trace = output / name / "trace.jsonl"
                        if trace.exists():
                            result["command_entrypoint_references"] = (
                                entrypoint_references(trace)
                            )
                        if result["error_code"] == "agent-failed":
                            errors = (output / name / "agent.log").read_text(
                                errors="replace"
                            )
                            if re.search(
                                r"not logged in|HTTP 401|401 Unauthorized|authentication (?:failed|required)",
                                errors,
                                re.IGNORECASE,
                            ):
                                result["error_code"] = blocked = (
                                    "cli-authentication-failed"
                                )
                            elif re.search(
                                r"model[^\n]*(?:not found|not supported|does not exist)",
                                errors,
                                re.IGNORECASE,
                            ):
                                result["error_code"] = blocked = "cli-model-unavailable"
                        (output / name / "result.json").write_text(
                            json.dumps(result, indent=2) + "\n"
                        )
                        results.append(result)
                        print(
                            f"{stack}/{condition}: {'PASS' if result['passed'] else result['error_code']}",
                            flush=True,
                        )
                        if blocked:
                            break
                    if blocked:
                        break
                if blocked:
                    break
        summary = {
            "suite": "core-catalog-entrypoint-v1",
            "profile": PROFILE,
            "stack": args.stack,
            "condition": args.condition,
            "requested_model": args.model,
            **metadata,
            "timeout_seconds": args.timeout,
            "repeats": args.repeats,
            "planned_total": len(stacks) * len(conditions) * args.repeats,
            "passed": sum(result["passed"] for result in results),
            "total": len(results),
            "blocked": blocked,
            "aggregates": {
                f"{stack}/{condition}": auth_eval.aggregate_results(
                    [
                        result
                        for result in results
                        if result["stack"] == stack and result["condition"] == condition
                    ]
                )
                for stack in stacks
                for condition in conditions
            },
            "runs": results,
        }
        auth_eval.write_json(output / "summary.json", summary)
    except (
        EvalError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ):
        print("Core evaluation could not initialize; inspect private local outputs.")
        return 2
    print(
        f"Core integration evaluation: {summary['passed']}/{summary['total']} passed. Private outputs written."
    )
    return 0 if not blocked and summary["passed"] == summary["planned_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
