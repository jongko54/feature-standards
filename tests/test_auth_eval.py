"""Self-contained harness tests; fake CLI results are not model evaluations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "auth_eval", Path(__file__).resolve().parents[1] / "tools/auth_eval.py"
)
auth_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth_eval)

COOKIE = "fs_session=" + "a" * 43
CSRF = "b" * 43
USER = {"id": "fixture-user", "email": "demo@example.com"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        authenticated = self.headers.get("Cookie") in self.server.sessions
        self.respond(
            200 if authenticated else 401, {"user": USER} if authenticated else {}
        )

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/auth/login":
            credentials = json.loads(data)
            if credentials != {
                "email": "demo@example.com",
                "password": "correct-horse-battery-staple",
            }:
                self.respond(401, {})
                return
            cookie, csrf = (
                "fs_session=" + secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
            )
            self.server.sessions[cookie] = csrf
            self.respond(200, {"user": USER, "csrfToken": csrf}, cookie)
        elif not self.server.ignore_csrf and self.headers.get(
            "X-CSRF-Token"
        ) != self.server.sessions.get(self.headers.get("Cookie")):
            self.respond(403, {})
        else:
            self.server.sessions.pop(self.headers.get("Cookie"), None)
            self.respond(204, None)

    def respond(self, status, value, cookie=None):
        data = json.dumps(value).encode() if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie + "; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)


FAKE_SERVER = """import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "implementations/python-fastapi"))
from feature_auth import current_user, create_app
app = create_app()
cookie = "fs_session=" + "a" * 43
csrf = "b" * 43
active = False
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, status, body=None, session=False):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        if session: self.send_header("Set-Cookie", cookie + "; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        user = current_user(self.headers.get("Cookie")) if active else None
        self.reply(200 if user else 401, {"user": user} if user else {})
    def do_POST(self):
        global active
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/auth/login":
            active = True
            self.reply(200, {"user": current_user(cookie), "csrfToken": csrf}, True)
        elif self.headers.get("X-CSRF-Token") != csrf:
            self.reply(403, {})
        else:
            active = False
            self.reply(204)
HTTPServer((os.environ["AUTH_HOST"], int(os.environ["AUTH_PORT"])), Handler).serve_forever()
"""


class AuthEvalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="auth-eval-test-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)

    def trace(self, events):
        path = self.root / "trace.jsonl"
        path.write_text("\n".join(json.dumps(item) for item in events) + "\n")
        return auth_eval.parse_trace(path)

    def test_usage_missing_is_distinct_from_explicit_zero(self):
        missing = self.trace([{"type": "turn.completed"}])
        zero = self.trace(
            [
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 0,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                    },
                }
            ]
        )
        self.assertIsNone(missing["usage"])
        self.assertFalse(missing["usage_complete"])
        self.assertEqual(zero["usage"]["input_tokens"], 0)
        self.assertTrue(zero["usage_complete"])

    def test_incomplete_and_failed_traces_do_not_pass(self):
        self.assertFalse(self.trace([{"type": "thread.started"}])["completed"])
        self.assertFalse(
            self.trace([{"type": "turn.completed"}, {"type": "turn.failed"}])[
                "completed"
            ]
        )
        path = self.root / "broken.jsonl"
        path.write_text('{"type":"turn.completed"}\n{"type":')
        self.assertFalse(auth_eval.parse_trace(path)["completed"])

    def test_usage_aggregation_and_observable_path_references(self):
        result = self.trace(
            [
                {"type": "thread.started", "model": "fixture-model"},
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "cat ../feature-standards.json ../.agents/skills/integrate-auth/SKILL.md",
                    },
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 7,
                        "cached_input_tokens": 2,
                        "output_tokens": 3,
                    },
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 5,
                        "cached_input_tokens": 1,
                        "output_tokens": 4,
                    },
                },
            ]
        )
        self.assertEqual(
            result["usage"],
            {"input_tokens": 12, "cached_input_tokens": 3, "output_tokens": 7},
        )
        self.assertEqual(result["command_count"], 1)
        self.assertEqual(result["model"], "fixture-model")
        self.assertEqual(result["command_path_references"], {"skill": 1, "manifest": 1})

    def test_output_rejects_clobber_and_symlink(self):
        directory = auth_eval.prepare_output(self.root / "new")
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        with self.assertRaises(auth_eval.EvalError):
            auth_eval.prepare_output(directory)
        (self.root / "link").symlink_to(self.root / "new", target_is_directory=True)
        with self.assertRaises(auth_eval.EvalError):
            auth_eval.prepare_output(self.root / "link/child")

    def test_output_parent_segments_cannot_bypass_repository_boundary(self):
        (self.root / "eval-results").mkdir()
        with self.assertRaisesRegex(auth_eval.EvalError, "repository-output"):
            auth_eval.prepare_output(
                self.root / "eval-results/../escape", root=self.root
            )

    def test_command_cwd_cannot_escape_generated(self):
        generated = self.root / "generated"
        generated.mkdir()
        (generated / "escape").symlink_to(self.root, target_is_directory=True)
        for cwd in ("..", str(self.root), "escape"):
            with self.subTest(cwd=cwd), self.assertRaises(auth_eval.EvalError):
                auth_eval.command({"argv": ["python3"], "cwd": cwd}, generated)
        for argv in ("python3 app.py", [], ["python3", 1], ["python3", "\0"]):
            with self.subTest(argv=argv), self.assertRaises(auth_eval.EvalError):
                auth_eval.command({"argv": argv, "cwd": "."}, generated)

    def test_private_files_are_exclusive_and_mode_0600(self):
        path = self.root / "private.json"
        auth_eval.write_json(path, {"passed": True})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            auth_eval.write_json(path, {})

    def test_build_cannot_replace_start_directory_with_escape_symlink(self):
        generated = self.root / "generated"
        generated.mkdir()
        (generated / "server").mkdir()
        auth_eval.write_json(
            generated / "run.json",
            {
                "build": [
                    {
                        "argv": [
                            sys.executable,
                            "-c",
                            "import os; os.rmdir('server'); os.symlink('..', 'server')",
                        ],
                        "cwd": ".",
                    }
                ],
                "start": {
                    "argv": [
                        sys.executable,
                        "-c",
                        "raise Exception('must not execute')",
                    ],
                    "cwd": "server",
                },
            },
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "symlink-path"):
            auth_eval.grade(
                generated,
                self.root,
                os.environ.copy(),
                0,
                "http://127.0.0.1",
                time.monotonic() + 5,
            )

    def test_timeout_terminates_process_group_without_printing_logs(self):
        pid_file = self.root / "child.pid"
        script = self.root / "hang.py"
        script.write_text(
            "import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nPath(sys.argv[1]).write_text(str(p.pid))\nprint('private fixture value', flush=True)\ntime.sleep(60)\n"
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "timeout"):
            auth_eval.execute(
                [sys.executable, str(script), str(pid_file)],
                self.root,
                os.environ.copy(),
                self.root / "private.log",
                time.monotonic() + 0.5,
            )
        pid = int(pid_file.read_text())
        # A killed child can briefly remain as a zombie until the OS reaps it.
        process = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertTrue(
            process.returncode != 0 or process.stdout.strip().startswith("Z")
        )

    def test_timeout_stops_observed_child_in_separate_session(self):
        pid_file = self.root / "detached.pid"
        script = self.root / "wrapper.py"
        script.write_text(
            "import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(60)\n"
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "timeout"):
            auth_eval.execute(
                [sys.executable, str(script), str(pid_file)],
                self.root,
                os.environ.copy(),
                self.root / "wrapper.log",
                time.monotonic() + 0.7,
            )
        pid = int(pid_file.read_text())
        process = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertTrue(
            process.returncode != 0 or process.stdout.strip().startswith("Z")
        )

    def server(self, ignore_csrf=False):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.sessions = {}
        server.ignore_csrf = ignore_csrf
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_http_grader_checks_actual_loopback_lifecycle(self):
        port = self.server()
        checks = auth_eval.http_grade(
            port, f"http://127.0.0.1:{port}", time.monotonic() + 5
        )
        self.assertGreaterEqual(len(checks), 18)
        self.assertIn("old-cookie-401", checks)

    def test_http_grader_fails_closed_when_csrf_is_not_enforced(self):
        port = self.server(ignore_csrf=True)
        with self.assertRaisesRegex(auth_eval.EvalError, "http-cross-session-csrf-403"):
            auth_eval.http_grade(port, f"http://127.0.0.1:{port}", time.monotonic() + 5)

    def test_whole_auth_copy_rejected_but_consumer_glue_allowed(self):
        generated = self.root / "generated"
        generated.mkdir()
        commit = "a" * 40
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": commit,
            },
        )
        data = (
            b"from feature_auth import current_user, create_app\napp = create_app()\ndef profile(request): return current_user(request)\n"
            + b"# consumer glue\n" * 30
        )
        (generated / "app.py").write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        auth_eval.reuse_check(
            generated,
            "python",
            {"examples/consumer-python-react/app.py": digest},
            commit,
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "copied-source-file"):
            auth_eval.reuse_check(
                generated,
                "python",
                {"implementations/python-fastapi/feature_auth/core.py": digest},
                commit,
            )

    def test_python_comment_only_or_unused_import_is_not_reuse_evidence(self):
        generated = self.root / "generated"
        generated.mkdir()
        commit = "a" * 40
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": commit,
            },
        )
        for text in (
            "# from feature_auth import current_user, create_app\n# create_app() current_user(request)",
            "from feature_auth import current_user, create_app\n",
        ):
            (generated / "app.py").write_text(text)
            with self.assertRaisesRegex(
                auth_eval.EvalError, "library-reuse-evidence-missing"
            ):
                auth_eval.reuse_check(generated, "python", {}, commit)

    def test_generated_python_syntax_failure_has_safe_code(self):
        generated = self.root / "generated"
        generated.mkdir()
        commit = "a" * 40
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": commit,
            },
        )
        (generated / "app.py").write_text("def incomplete(\n")
        with self.assertRaisesRegex(auth_eval.EvalError, "^generated-python-syntax$"):
            auth_eval.reuse_check(generated, "python", {}, commit)

    def fixture_repo(self):
        root = self.root / "source"
        root.mkdir()
        for name, text in {
            "AGENTS.md": "fixture instructions",
            "README.md": "fixture readme",
            "skills/integrate-auth/SKILL.md": "fixture skill",
            "feature-standards.json": "{}",
            "implementations/python-fastapi/feature_auth/__init__.py": "def create_app(): return None\ndef current_user(cookie):\n    return {'id':'fixture-user','email':'demo@example.com'} if cookie == 'fs_session=' + 'a'*43 else None\n",
            "implementations/python-fastapi/.env": "must never be copied",
        }.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "user.name=Fixture",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=root,
            check=True,
        )
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
            .decode()
            .strip()
        )
        (root / "AGENTS.md").write_text("updated fixture instructions")
        target = root / ".agents/skills/integrate-auth"
        target.parent.mkdir(parents=True)
        target.symlink_to("../../skills/integrate-auth")
        return root, commit

    def test_snapshot_conditions_preserve_same_current_library_and_exclude_secrets(
        self,
    ):
        root, commit = self.fixture_repo()
        with patch.object(auth_eval, "BASELINE_REF", commit):
            baseline, skill = self.root / "baseline", self.root / "skill"
            auth_eval.snapshot(root, baseline, "baseline")
            auth_eval.snapshot(root, skill, "skill")
        library = "implementations/python-fastapi/feature_auth/__init__.py"
        self.assertEqual(
            (baseline / library).read_bytes(), (skill / library).read_bytes()
        )
        self.assertFalse((baseline / "feature-standards.json").exists())
        self.assertTrue((skill / ".agents/skills/integrate-auth/SKILL.md").is_file())
        self.assertEqual((baseline / "AGENTS.md").read_text(), "fixture instructions")
        self.assertEqual(
            (skill / "AGENTS.md").read_text(), "updated fixture instructions"
        )
        self.assertFalse((skill / "implementations/python-fastapi/.env").exists())
        self.assertEqual(stat.S_IMODE((skill / library).stat().st_mode) & 0o222, 0)

    def test_snapshot_rejects_absolute_symlink_even_to_source_inside_repo(self):
        root, _ = self.fixture_repo()
        (root / "skills/absolute.md").symlink_to(root / "README.md")
        with self.assertRaisesRegex(auth_eval.EvalError, "snapshot-link-escape"):
            auth_eval.snapshot(root, self.root / "snapshot", "skill")

    def test_deterministic_fake_cli_smoke_is_not_model_performance_evidence(self):
        root, commit = self.fixture_repo()
        cli = self.root / "fake-codex"
        cli.write_text(
            "#!/usr/bin/env python3\nimport json,re,sys\nfrom pathlib import Path\n"
            "if '--version' in sys.argv: print('fixture-cli 1.0'); sys.exit(0)\n"
            "text=sys.stdin.read()\ncommit=re.search(r'출처 커밋은 ([0-9a-f]{40})',text)[1]\n"
            "assert (Path.cwd().parent / '.git').is_dir()\n"
            f"Path('app.py').write_text({FAKE_SERVER!r})\n"
            "Path('run.json').write_text(json.dumps({'build':[],'start':{'argv':[sys.executable,'app.py'],'cwd':'.'}}))\n"
            "Path('integration.json').write_text(json.dumps({'stack':'python','profile':'browser-session-v1','source_commit':commit}))\n"
            "print('fixture stderr is separate',file=sys.stderr)\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':0,'cached_input_tokens':0,'output_tokens':0}}))\n"
        )
        cli.chmod(0o700)
        with patch.object(auth_eval, "BASELINE_REF", commit):
            for condition in ("baseline", "skill"):
                result = auth_eval.run_trial(
                    root, self.root / condition, "python", condition, 15, cli=str(cli)
                )
                self.assertFalse(result["passed"])
                self.assertEqual(result["error_code"], "http-wrong-password-401")
                self.assertTrue(result["source_unchanged"])
                self.assertTrue(result["source_dirty"])
                self.assertEqual(result["agent"]["usage"]["output_tokens"], 0)
                self.assertFalse((self.root / condition / "snapshot/.git").exists())


if __name__ == "__main__":
    unittest.main()
