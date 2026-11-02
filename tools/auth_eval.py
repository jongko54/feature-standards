"""Run bounded, isolated auth integration tasks and grade their HTTP behavior."""

from __future__ import annotations

import argparse
import ast
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REF = "2a18bbd50f142b2fc0a991fe0d40ccf7032476b9"
STACKS = ("python", "go", "java", "rust")
IGNORED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "target",
    "dist",
    "bin",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "test-results",
    "playwright-report",
}
SCOPES = {
    "implementations",
    "examples",
    "features",
    "skills",
    ".agents",
    "docs",
    "tests",
    "clients",
}
ROOT_FILES = {"AGENTS.md", "README.md", "feature-standards.json"}
TOOL_FILES = {
    "auth_catalog.py",
    "auth_db.py",
    "mail_worker.py",
    "pyproject.toml",
    "uv.lock",
}


class EvalError(Exception):
    """Only safe, fixed diagnostic codes are surfaced in reports."""


def private_file(path: Path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def write_json(path: Path, value: dict) -> None:
    with private_file(path) as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def no_symlink(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise EvalError("symlink-path")


def prepare_output(path: Path, root: Path = ROOT) -> Path:
    path = path.expanduser().absolute()
    no_symlink(path)
    path = path.resolve()
    if path.exists() or not path.parent.is_dir():
        raise EvalError("output-must-be-new-with-existing-parent")
    if path.is_relative_to(root.resolve()) and not path.is_relative_to(
        root / "eval-results"
    ):
        raise EvalError("repository-output-must-be-under-eval-results")
    path.mkdir(mode=0o700)
    return path


def source_files(root: Path) -> list[Path]:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    selected = []
    for name in filter(None, names):
        relative = Path(name)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if relative.name.startswith(".env") and relative.name != ".env.example":
            continue
        allowed = (
            name in ROOT_FILES
            or relative.parts[0] in SCOPES
            or (
                len(relative.parts) == 2
                and relative.parts[0] == "tools"
                and relative.name in TOOL_FILES
            )
        )
        if not allowed or name == "docs/ai-integration-plan.md":
            continue
        source = root / relative
        if source.is_file() or source.is_symlink():
            selected.append(relative)
    return sorted(set(selected))


def snapshot(root: Path, destination: Path, condition: str) -> dict:
    destination.mkdir(mode=0o700)
    for relative in source_files(root):
        if condition == "baseline" and (
            relative.parts[0] == ".agents"
            or str(relative)
            in {
                "feature-standards.json",
                "tools/auth_catalog.py",
                "docs/ai-integration.md",
            }
            or str(relative).startswith("skills/integrate-auth/references/")
        ):
            continue
        source, target = root / relative, destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            if Path(
                os.readlink(source)
            ).is_absolute() or not source.resolve().is_relative_to(root.resolve()):
                raise EvalError("snapshot-link-escape")
            referent = destination / source.resolve().relative_to(root.resolve())
            target.symlink_to(os.path.relpath(referent, target.parent))
        else:
            shutil.copy2(source, target)
    if condition == "baseline":
        for name in ("AGENTS.md", "README.md", "skills/integrate-auth/SKILL.md"):
            try:
                data = subprocess.check_output(
                    ["git", "show", f"{BASELINE_REF}:{name}"], cwd=root
                )
            except subprocess.CalledProcessError as exc:
                raise EvalError("baseline-source-unavailable") from exc
            (destination / name).write_bytes(data)
    for path in destination.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    return fingerprint(destination)


def fingerprint(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == "generated" or any(
            part in IGNORED_PARTS for part in relative.parts
        ):
            continue
        if path.is_symlink():
            result[str(relative)] = "link:" + os.readlink(path)
        elif path.is_file():
            result[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def parse_trace(path: Path) -> dict:
    completed = failed = commands = malformed = 0
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    usage_turns = 0
    model = None
    path_references = {"skill": 0, "manifest": 0}
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                malformed += 1
                continue
            if not isinstance(event, dict):
                malformed += 1
                continue
            kind = event.get("type")
            candidate = event.get("model")
            if isinstance(candidate, str) and re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", candidate
            ):
                model = candidate
            if kind == "item.completed" and isinstance(event.get("item"), dict):
                commands += event["item"].get("type") == "command_execution"
                text = event["item"].get("command", "")
                if (
                    isinstance(text, str)
                    and event["item"].get("type") == "command_execution"
                ):
                    path_references["skill"] += "skills/integrate-auth/SKILL.md" in text
                    path_references["manifest"] += "feature-standards.json" in text
            if kind in {"turn.failed", "error"}:
                failed += 1
            if kind == "turn.completed":
                completed += 1
                item = event.get("usage")
                if isinstance(item, dict) and all(
                    type(item.get(key)) is int and item[key] >= 0 for key in usage
                ):
                    usage_turns += 1
                    for key in usage:
                        usage[key] += item[key]
    return {
        "completed": completed > 0 and failed == 0 and malformed == 0,
        "completed_turns": completed,
        "command_count": commands,
        "malformed_events": malformed,
        "usage_complete": completed > 0 and usage_turns == completed,
        "usage": usage if usage_turns else None,
        "model": model,
        "command_path_references": path_references,
    }


class ProcessTree:
    """Track observed descendants, including children that create their own session."""

    def __init__(self, child: subprocess.Popen):
        self.child = child
        self.known = {}
        self.groups = {child.pid}
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.scan()
        self.worker = threading.Thread(target=self.watch, daemon=True)
        self.worker.start()

    def scan(self) -> dict:
        try:
            listing = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,pgid=,lstart="],
                capture_output=True,
                text=True,
                check=False,
                timeout=1,
            )
            records = {}
            for line in listing.stdout.splitlines():
                fields = line.split(maxsplit=3)
                if len(fields) == 4:
                    records[int(fields[0])] = (
                        int(fields[1]),
                        int(fields[2]),
                        fields[3],
                    )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {}
        with self.lock:
            owners = {
                pid
                for pid, stamp in self.known.items()
                if pid in records and records[pid][2] == stamp
            }
            if self.child.poll() is None:
                owners.add(self.child.pid)
            while True:
                added = {
                    pid for pid, (parent, _, _) in records.items() if parent in owners
                }
                if added.issubset(owners):
                    break
                owners.update(added)
            for pid in owners & records.keys():
                _, group, stamp = records[pid]
                self.known[pid] = stamp
                if group == pid:
                    self.groups.add(group)
            return {pid: records[pid] for pid in owners & records.keys()}

    def watch(self) -> None:
        while not self.finished.wait(0.2):
            self.scan()

    def close(self) -> None:
        self.finished.set()
        self.worker.join(timeout=2)


def stop_group(child: subprocess.Popen, tree: ProcessTree | None = None) -> None:
    if tree:
        tree.close()
    for action in (signal.SIGTERM, signal.SIGKILL):
        observed = tree.scan() if tree else {}
        groups = {child.pid} | {
            group for _, group, _ in observed.values() if tree and group in tree.groups
        }
        for group in groups:
            try:
                os.killpg(group, action)
            except ProcessLookupError:
                pass
        for pid in observed:
            try:
                os.kill(pid, action)
            except ProcessLookupError:
                pass
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue
        # Also kill descendants after a wrapper has exited.
        if action == signal.SIGTERM:
            continue
        return


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise EvalError("timeout")
    return seconds


def execute(
    argv: list[str],
    cwd: Path,
    env: dict,
    log: Path,
    deadline: float,
    stdin=None,
    stderr_log: Path | None = None,
) -> int:
    with private_file(log) as stream:
        errors = private_file(stderr_log) if stderr_log else None
        try:
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=stream,
                stderr=errors or stream,
                start_new_session=True,
            )
            tree = ProcessTree(child)
            try:
                child.communicate(input=stdin, timeout=remaining(deadline))
                return child.returncode
            except subprocess.TimeoutExpired as exc:
                raise EvalError("timeout") from exc
            finally:
                stop_group(child, tree)
        finally:
            if errors:
                errors.close()


def command(value: object, generated: Path) -> tuple[list[str], Path]:
    if not isinstance(value, dict) or set(value) != {"argv", "cwd"}:
        raise EvalError("invalid-command")
    argv, cwd = value["argv"], value["cwd"]
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 64
        or any(
            not isinstance(arg, str) or not arg or "\0" in arg or len(arg) > 8192
            for arg in argv
        )
        or not isinstance(cwd, str)
        or Path(cwd).is_absolute()
    ):
        raise EvalError("invalid-command")
    location = generated / cwd
    no_symlink(location)
    location = location.resolve()
    if not location.is_relative_to(generated.resolve()) or not location.is_dir():
        raise EvalError("command-cwd-escape")
    return argv, location


def load_run(
    generated: Path,
) -> tuple[list[tuple[list[str], Path]], tuple[list[str], Path]]:
    path = generated / "run.json"
    no_symlink(path)
    if path.stat().st_size > 64_000:
        raise EvalError("invalid-run-json")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise EvalError("invalid-run-json") from exc
    if not isinstance(value, dict) or set(value) != {"build", "start"}:
        raise EvalError("invalid-run-json")
    if not isinstance(value["build"], list) or len(value["build"]) > 8:
        raise EvalError("invalid-run-json")
    return [command(item, generated) for item in value["build"]], command(
        value["start"], generated
    )


def reuse_check(generated: Path, stack: str, source: dict, commit: str) -> None:
    provenance = generated / "integration.json"
    no_symlink(provenance)
    value = json.loads(provenance.read_text())
    if value != {
        "stack": stack,
        "profile": "browser-session-v1",
        "source_commit": commit,
    }:
        raise EvalError("provenance-mismatch")
    sources = []
    python_trees = []
    implementation_hashes = {
        digest
        for name, digest in source.items()
        if name.startswith("implementations/")
        and Path(name).suffix in {".py", ".go", ".java", ".rs"}
        and Path(name).stem not in {"main", "app"}
        and "test" not in Path(name).name.lower()
    }
    for path in generated.rglob("*"):
        relative = path.relative_to(generated)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            raise EvalError("generated-source-symlink")
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
            if len(data) > 2_000_000:
                raise EvalError("generated-source-too-large")
            if (
                len(data) > 200
                and hashlib.sha256(data).hexdigest() in implementation_hashes
            ):
                raise EvalError("copied-source-file")
            sources.append(data.decode("utf-8"))
            if path.suffix == ".py":
                try:
                    python_trees.append(ast.parse(data))
                except SyntaxError as exc:
                    raise EvalError("generated-python-syntax") from exc
    text = "\n".join(sources)
    if stack == "python":
        used = set()
        for tree in python_trees:
            imported = {}
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "feature_auth":
                    imported.update(
                        {alias.asname or alias.name: alias.name for alias in node.names}
                    )
                if isinstance(node, ast.Import):
                    modules.update(
                        alias.asname or alias.name
                        for alias in node.names
                        if alias.name == "feature_auth"
                    )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # A dependency injection reference such as Depends(current_user) is executable use.
                for expression in (node.func, *node.args):
                    if isinstance(expression, ast.Name) and expression.id in imported:
                        used.add(imported[expression.id])
                    if (
                        isinstance(expression, ast.Attribute)
                        and isinstance(expression.value, ast.Name)
                        and expression.value.id in modules
                    ):
                        used.add(expression.attr)
        if not {"current_user", "create_app"}.issubset(used):
            raise EvalError("library-reuse-evidence-missing")
        return
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
    patterns = {
        "python": (
            r"(?:from\s+feature_auth\s+import|import\s+feature_auth)",
            r"current_user",
        ),
        "go": (
            r"github.com/jongko54/feature-standards/implementations/go-net-http/auth",
            r"CurrentUser",
        ),
        "java": (r"import\s+dev\.featurestandards\.auth\.", r"java-spring-auth"),
        "rust": (
            r"feature-standards-auth\s*=",
            r"feature_standards_auth",
            r"current_user",
        ),
    }
    if not all(re.search(pattern, text) for pattern in patterns[stack]):
        raise EvalError("library-reuse-evidence-missing")


def request(
    port: int,
    method: str,
    path: str,
    origin: str,
    deadline: float,
    *,
    body=None,
    cookie=None,
    csrf=None,
):
    headers = {"Origin": origin}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if cookie is not None:
        headers["Cookie"] = cookie
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=min(2, remaining(deadline))
    )
    try:
        connection.request(
            method, path, json.dumps(body) if body is not None else None, headers
        )
        response = connection.getresponse()
        payload = response.read(16_385)
        if len(payload) > 16_384:
            raise EvalError("response-too-large")
        try:
            value = json.loads(payload) if payload else None
        except ValueError:
            value = None
        return response.status, dict(response.getheaders()), value
    finally:
        connection.close()


def http_grade(port: int, origin: str, deadline: float) -> list[str]:
    checks = []

    def expect(name, actual, wanted):
        if actual != wanted:
            raise EvalError("http-" + name)
        checks.append(name)

    expect(
        "anonymous-401", request(port, "GET", "/api/profile", origin, deadline)[0], 401
    )
    expect(
        "forged-cookie-401",
        request(
            port,
            "GET",
            "/api/profile",
            origin,
            deadline,
            cookie="fs_session=" + "z" * 43,
        )[0],
        401,
    )
    for name, email, password in (
        ("wrong-password-401", "demo@example.com", "incorrect-password"),
        ("unknown-user-401", "unknown@example.com", "correct-horse-battery-staple"),
    ):
        expect(
            name,
            request(
                port,
                "POST",
                "/auth/login",
                origin,
                deadline,
                body={"email": email, "password": password},
            )[0],
            401,
        )
    status, headers, session = request(
        port,
        "POST",
        "/auth/login",
        origin,
        deadline,
        body={"email": "demo@example.com", "password": "correct-horse-battery-staple"},
    )
    expect("login-200", status, 200)
    if not isinstance(session, dict) or not isinstance(session.get("user"), dict):
        raise EvalError("http-login-shape")
    user, csrf = session["user"], session.get("csrfToken")
    if (
        user.get("email") != "demo@example.com"
        or not user.get("id")
        or not isinstance(csrf, str)
        or len(csrf) != 43
    ):
        raise EvalError("http-login-shape")
    raw_cookie = next((v for k, v in headers.items() if k.lower() == "set-cookie"), "")
    cookie = raw_cookie.split(";", 1)[0]
    if not re.fullmatch(r"fs_session=[A-Za-z0-9_-]{43}", cookie):
        raise EvalError("http-login-cookie")
    status2, headers2, session2 = request(
        port,
        "POST",
        "/auth/login",
        origin,
        deadline,
        body={"email": "demo@example.com", "password": "correct-horse-battery-staple"},
    )
    expect("independent-login-200", status2, 200)
    cookie2 = next(
        (v for k, v in headers2.items() if k.lower() == "set-cookie"), ""
    ).split(";", 1)[0]
    csrf2 = session2.get("csrfToken") if isinstance(session2, dict) else None
    expect(
        "independent-cookie",
        bool(re.fullmatch(r"fs_session=[A-Za-z0-9_-]{43}", cookie2))
        and cookie2 != cookie,
        True,
    )
    expect(
        "independent-csrf",
        isinstance(csrf2, str) and len(csrf2) == 43 and csrf2 != csrf,
        True,
    )
    expect(
        "cross-session-csrf-403",
        request(
            port, "POST", "/auth/logout", origin, deadline, cookie=cookie, csrf=csrf2
        )[0],
        403,
    )
    status, _, profile = request(
        port, "GET", "/api/profile", origin, deadline, cookie=cookie
    )
    expect("profile-200", status, 200)
    expect(
        "profile-user", isinstance(profile, dict) and profile.get("user") == user, True
    )
    expect(
        "bad-csrf-403",
        request(
            port, "POST", "/auth/logout", origin, deadline, cookie=cookie, csrf="wrong"
        )[0],
        403,
    )
    expect(
        "bad-csrf-preserves-session",
        request(port, "GET", "/api/profile", origin, deadline, cookie=cookie)[0],
        200,
    )
    expect(
        "logout-204",
        request(
            port, "POST", "/auth/logout", origin, deadline, cookie=cookie, csrf=csrf
        )[0],
        204,
    )
    expect(
        "old-cookie-401",
        request(port, "GET", "/api/profile", origin, deadline, cookie=cookie)[0],
        401,
    )
    expect(
        "old-cookie-auth-me-401",
        request(port, "GET", "/auth/me", origin, deadline, cookie=cookie)[0],
        401,
    )
    expect(
        "independent-session-preserved",
        request(port, "GET", "/api/profile", origin, deadline, cookie=cookie2)[0],
        200,
    )
    expect(
        "second-logout-204",
        request(
            port, "POST", "/auth/logout", origin, deadline, cookie=cookie2, csrf=csrf2
        )[0],
        204,
    )
    expect(
        "second-old-cookie-401",
        request(port, "GET", "/api/profile", origin, deadline, cookie=cookie2)[0],
        401,
    )
    return checks


def environment(port: int, origin: str) -> dict:
    keys = (
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "SHELL",
        "JAVA_HOME",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "CODEX_HOME",
        "OPENAI_API_KEY",
    )
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env.update(
        AUTH_STORE="memory",
        AUTH_ACCOUNT_LIFECYCLE="false",
        AUTH_DEMO="true",
        AUTH_COOKIE_SECURE="false",
        AUTH_HOST="127.0.0.1",
        AUTH_PORT=str(port),
        AUTH_ALLOWED_ORIGIN=origin,
        AUTH_SESSION_TTL_SECONDS="1800",
        AUTH_RATE_LIMIT_MAX="20",
        AUTH_RATE_LIMIT_WINDOW_SECONDS="60",
    )
    return env


def grade(
    generated: Path, output: Path, env: dict, port: int, origin: str, deadline: float
) -> list[str]:
    builds, (argv, cwd) = load_run(generated)
    # Credentials authenticate only the model CLI; generated programs do not inherit them.
    env = {
        key: value
        for key, value in env.items()
        if key not in {"OPENAI_API_KEY", "CODEX_HOME"}
    }
    for index, (build, location) in enumerate(builds):
        no_symlink(location)
        if execute(build, location, env, output / f"build-{index}.log", deadline) != 0:
            raise EvalError("build-failed")
    no_symlink(cwd)
    with private_file(output / "server.log") as log:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        tree = ProcessTree(child)
        try:
            ready_deadline = min(deadline, time.monotonic() + 60)
            while remaining(ready_deadline):
                if child.poll() is not None:
                    raise EvalError("server-exited")
                try:
                    request(port, "GET", "/api/profile", origin, ready_deadline)
                    break
                except (OSError, http.client.HTTPException):
                    time.sleep(min(0.1, remaining(ready_deadline)))
            return http_grade(port, origin, deadline)
        finally:
            stop_group(child, tree)


def prompt(stack: str, commit: str) -> str:
    task = json.loads((ROOT / "evals/auth/tasks.json").read_text())[stack]
    return f"""{task}

현재 디렉터리는 쓰기 가능한 generated/이고 상위 ../가 읽기 전용 참조 저장소입니다.
기존 공개 인증 라이브러리를 의존성으로 가져오세요. 인증 구현 파일이나 인증 로직을 복사하지 마세요.
새 파일은 현재 디렉터리 아래에만 만드세요. ../의 코드·설정·지침을 바꾸지 마세요.
프로필은 browser-session-v1, 출처 커밋은 {commit}입니다. React·DB·메일·배포는 필요 없습니다.
앱은 AUTH_HOST, AUTH_PORT, AUTH_ALLOWED_ORIGIN과 공통 AUTH_* 설정을 사용해야 합니다.
grader가 메모리 demo=true, secure=false와 loopback port/origin을 주입합니다.
보호 API GET /api/profile은 JSON {{"user": {{"id": "...", "email": "..."}}}}를 반환합니다.
익명401, 로그인200, 보호 API200, 잘못된 CSRF 로그아웃403/세션유지, 정상 로그아웃204,
복사한 이전 cookie의 보호 API401과 /auth/me401을 만족해야 합니다.
run.json은 {{"build":[{{"argv":["실행파일","인자"],"cwd":"."}}],"start":{{"argv":["실행파일","인자"],"cwd":"."}}}} 입니다.
build는 빈 목록도 허용하며 최대 8개입니다. cwd는 모두 generated 내부 상대 경로입니다.
run.json argv는 shell 문자열이 아닌 실제 인자 목록입니다. 서버는 foreground로 실행합니다.
integration.json은 정확히 {{"stack":"{stack}","profile":"browser-session-v1","source_commit":"{commit}"}}를 기록합니다.
자동 grader가 빌드·실행하므로 의존성 다운로드나 전체 저장소 테스트에 시간을 쓰지 않아도 됩니다.
사용자에게 질문하거나 Git commit/push를 하지 마세요. 완료하면 생성한 경로와 실행법만 간단히 보고하세요.
"""


def run_trial(
    root: Path,
    output: Path,
    stack: str,
    condition: str,
    timeout: int,
    *,
    cli: str = "codex",
) -> dict:
    started = time.monotonic()
    deadline = started + timeout
    output.mkdir(mode=0o700)
    commit = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    )
    # A workspace beneath the real repo could inherit its AGENTS.md and Git root.
    # Use a separate resolved temporary location, then retain only reviewable sources.
    workspace = tempfile.TemporaryDirectory(prefix="feature-auth-eval-")
    work = Path(workspace.name).resolve() / "snapshot"
    before = snapshot(root, work, condition)
    subprocess.run(
        [
            "git",
            "-c",
            "init.templateDir=",
            "init",
            "-q",
            "--initial-branch=eval",
            str(work),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    generated = work / "generated"
    generated.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = environment(port, origin)
    try:
        version = subprocess.run(
            [cli, "--version"],
            cwd=generated,
            env=env,
            capture_output=True,
            check=False,
            timeout=min(5, remaining(deadline)),
        )
        cli_version = version.stdout.decode("utf-8", errors="replace").strip()
        if version.returncode != 0 or not re.fullmatch(
            r"[A-Za-z0-9 ._+/-]{1,120}", cli_version
        ):
            cli_version = None
    except (OSError, subprocess.TimeoutExpired):
        cli_version = None
    result = {
        "stack": stack,
        "condition": condition,
        "source_commit": commit,
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root
            ).strip()
        ),
        "cli_version": cli_version,
        "baseline_ref": BASELINE_REF,
        "snapshot_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()
        ).hexdigest(),
        "passed": False,
        "checks": [],
        "error_code": None,
        "agent": None,
        "source_unchanged": False,
    }
    trace = output / "trace.jsonl"
    argv = [
        cli,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--json",
        "--skip-git-repo-check",
        "-c",
        'approval_policy="never"',
        "-c",
        'shell_environment_policy.inherit="core"',
        "-C",
        str(generated),
        "-",
    ]
    agent_started = time.monotonic()
    try:
        # Reserve a third of the total budget for builds and independent grading.
        code = execute(
            argv,
            generated,
            env,
            trace,
            min(deadline, started + timeout * 0.67),
            prompt(stack, commit).encode(),
            output / "agent.log",
        )
        result["agent_seconds"] = round(time.monotonic() - agent_started, 3)
        result["agent"] = parse_trace(trace)
        if code != 0:
            raise EvalError("agent-failed")
        if not result["agent"]["completed"]:
            raise EvalError("agent-trace-incomplete")
        if fingerprint(work) != before:
            raise EvalError("source-modified")
        reuse_check(generated, stack, before, commit)
        result["checks"] = grade(generated, output, env, port, origin, deadline)
        if fingerprint(work) != before:
            raise EvalError("source-modified")
        result["passed"] = True
    except EvalError as exc:
        result["error_code"] = str(exc)
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        result["error_code"] = "artifact-or-runtime-error"
    finally:
        result["source_unchanged"] = fingerprint(work) == before
        result.setdefault("agent_seconds", round(time.monotonic() - agent_started, 3))
        if trace.exists() and result["agent"] is None:
            result["agent"] = parse_trace(trace)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        shutil.copytree(
            work,
            output / "snapshot",
            symlinks=True,
            ignore=shutil.ignore_patterns(*IGNORED_PARTS),
        )
        write_json(output / "result.json", result)
        workspace.cleanup()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", choices=STACKS, required=True)
    parser.add_argument("--condition", choices=("baseline", "skill"), required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds")
    if shutil.which("codex") is None:
        parser.error("codex CLI is required")
    try:
        output = prepare_output(args.output)
        results = [
            run_trial(
                ROOT,
                output / f"trial-{index + 1}",
                args.stack,
                args.condition,
                args.timeout,
            )
            for index in range(args.repeats)
        ]
        summary = {
            "stack": args.stack,
            "condition": args.condition,
            "repeats": args.repeats,
            "passed": sum(item["passed"] for item in results),
            "runs": results,
        }
        write_json(output / "summary.json", summary)
    except (EvalError, OSError, subprocess.SubprocessError):
        print("Auth evaluation could not initialize; inspect private local outputs.")
        return 2
    print(
        f"Auth integration evaluation: {summary['passed']}/{args.repeats} passed. Private outputs written."
    )
    return 0 if summary["passed"] == args.repeats else 1


if __name__ == "__main__":
    raise SystemExit(main())
