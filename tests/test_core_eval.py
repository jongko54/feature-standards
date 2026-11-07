"""Deterministic grader/safety tests; these are not AI performance evidence."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import secrets
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "libraries/python"))
import auth_eval
import core_eval
from feature_standards.listing import ListingError, ListingSchema, page, parse_query

REPLAY_SPEC = importlib.util.spec_from_file_location(
    "core_smoke_replay", ROOT / "evals/core/replay_smoke.py"
)
replay_smoke = importlib.util.module_from_spec(REPLAY_SPEC)
REPLAY_SPEC.loader.exec_module(replay_smoke)

DOCUMENTS = [
    {
        "id": "own-b",
        "name": "Beta",
        "score": 2,
        "active": False,
        "tenantId": "tenant-a",
        "ownerId": "demo-user",
    },
    {
        "id": "other-owner",
        "name": "Private",
        "score": 10,
        "active": True,
        "tenantId": "tenant-a",
        "ownerId": "other-user",
    },
    {
        "id": "other-tenant",
        "name": "Secret",
        "score": 99,
        "active": True,
        "tenantId": "tenant-b",
        "ownerId": "demo-user",
    },
    {
        "id": "own-a",
        "name": "Alpha",
        "score": 2,
        "active": True,
        "tenantId": "tenant-a",
        "ownerId": "demo-user",
    },
]
USER = {"id": "demo-user", "email": "demo@example.com"}


class CoreHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value=None, cookie=None):
        body = json.dumps(value).encode() if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie + "; HttpOnly; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, code):
        self.reply(
            status,
            {"error": {"code": code, "message": "Request could not be completed."}},
        )

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/auth/login":
            if json.loads(raw) != {
                "email": "demo@example.com",
                "password": "correct-horse-battery-staple",
            }:
                self.error(401, "INVALID_CREDENTIALS")
                return
            cookie, csrf = (
                "fs_session=" + secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
            )
            self.server.sessions[cookie] = csrf
            self.reply(200, {"user": USER, "csrfToken": csrf}, cookie)
        elif self.path == "/auth/logout":
            cookie = self.headers.get("Cookie")
            if cookie not in self.server.sessions:
                self.error(401, "UNAUTHENTICATED")
            elif self.headers.get("X-CSRF-Token") != self.server.sessions[cookie]:
                self.error(403, "CSRF_INVALID")
            else:
                self.server.sessions.pop(cookie)
                self.reply(204)
        else:
            self.error(404, "NOT_FOUND")

    def do_GET(self):
        if self.headers.get("Cookie") not in self.server.sessions:
            self.error(401, "UNAUTHENTICATED")
            return
        path = urlsplit(self.path)
        if path.path in ("/api/profile", "/auth/me"):
            self.reply(200, {"user": USER})
            return
        try:
            membership = json.loads(self.server.membership_file.read_text())
            if not isinstance(membership, dict) or membership.get("unavailable"):
                raise ValueError
            roles = membership["roles"]
            if not isinstance(roles, list):
                raise TypeError
        except (ValueError, TypeError, KeyError, OSError):
            self.error(503, "AUTHORIZATION_UNAVAILABLE")
            return
        if self.server.fault == "ignore-revoke":
            roles = ["viewer"]
        if self.server.fault == "role-header" and self.headers.get("X-Role") == "admin":
            roles = ["viewer"]
        if "viewer" not in roles or membership.get("subjectId") != USER["id"]:
            self.error(403, "FORBIDDEN")
            return
        visible = [
            document
            for document in DOCUMENTS
            if document["tenantId"] == membership.get("tenantId")
            and document["ownerId"] == USER["id"]
        ]

        def project(document):
            return {key: document[key] for key in ("id", "name", "score", "active")}

        if path.path == "/api/documents":
            schema = ListingSchema(
                {
                    "id": "string",
                    "name": "string",
                    "score": "integer",
                    "active": "boolean",
                },
                {"name": "string", "score": "integer", "active": "boolean"},
            )
            try:
                result = page(
                    [project(document) for document in visible],
                    parse_query(path.query, schema),
                    schema,
                )
                if self.server.fault == "unscoped-total":
                    result["total"] = len(DOCUMENTS)
                self.reply(200, result)
            except ListingError:
                self.error(400, "INVALID_LIST_QUERY")
        elif path.path.startswith("/api/documents/"):
            document = next(
                (
                    document
                    for document in visible
                    if document["id"] == path.path.rsplit("/", 1)[1]
                ),
                None,
            )
            self.reply(200, project(document)) if document else self.error(
                403, "FORBIDDEN"
            )
        else:
            self.error(404, "NOT_FOUND")


class CoreEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="core-eval-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def membership(self):
        path = self.root / "membership.json"
        auth_eval.write_json(
            path,
            {"subjectId": "demo-user", "tenantId": "tenant-a", "roles": ["viewer"]},
        )
        return path

    def server(self, fault=None):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
        server.sessions = {}
        server.membership_file = self.membership()
        server.fault = fault
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_independent_grader_accepts_real_loopback_contract(self):
        server = self.server()
        checks = core_eval.core_http_grade(
            server.server_port,
            f"http://127.0.0.1:{server.server_port}",
            time.monotonic() + 10,
            server.membership_file,
        )
        self.assertIn("core-revocation-403", checks)
        self.assertIn("core-scoped-total", checks)
        self.assertIn("core-old-cookie-401", checks)
        self.assertGreaterEqual(len(checks), 35)

    def test_independent_grader_rejects_unscoped_totals(self):
        server = self.server("unscoped-total")
        with self.assertRaisesRegex(auth_eval.EvalError, "core-scoped-total"):
            core_eval.core_http_grade(
                server.server_port,
                "http://127.0.0.1",
                time.monotonic() + 10,
                server.membership_file,
            )

    def test_independent_grader_rejects_ignored_revocation(self):
        server = self.server("ignore-revoke")
        with self.assertRaisesRegex(auth_eval.EvalError, "core-revocation-403"):
            core_eval.core_http_grade(
                server.server_port,
                "http://127.0.0.1",
                time.monotonic() + 10,
                server.membership_file,
            )

    def test_independent_grader_rejects_role_header_privilege_escalation(self):
        server = self.server("role-header")
        with self.assertRaisesRegex(auth_eval.EvalError, "core-forged-role-403"):
            core_eval.core_http_grade(
                server.server_port,
                "http://127.0.0.1",
                time.monotonic() + 10,
                server.membership_file,
            )

    def archive(self, names):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, kind in names:
                item = tarfile.TarInfo(name)
                item.type = kind
                content = b"test"
                if kind == tarfile.REGTYPE:
                    item.size = len(content)
                    archive.addfile(item, io.BytesIO(content))
                else:
                    item.linkname = "/tmp/unsafe"
                    archive.addfile(item)
        return stream.getvalue()

    def test_archive_accepts_normal_files_and_rejects_path_or_link_escapes(self):
        destination = self.root / "safe"
        core_eval.extract_archive(
            self.archive([("package/src/cli.mjs", tarfile.REGTYPE)]), destination
        )
        self.assertEqual((destination / "package/src/cli.mjs").read_bytes(), b"test")
        for index, member in enumerate(
            [
                ("../escape", tarfile.REGTYPE),
                ("/absolute", tarfile.REGTYPE),
                ("package/../escape", tarfile.REGTYPE),
                ("package/link", tarfile.SYMTYPE),
                ("package/link", tarfile.LNKTYPE),
                ("package/node_modules/x", tarfile.REGTYPE),
            ]
        ):
            with self.subTest(member=member), self.assertRaises(auth_eval.EvalError):
                core_eval.extract_archive(
                    self.archive([member]), self.root / str(index)
                )

    def test_membership_fixture_cannot_clobber_or_follow_a_symlink(self):
        generated = self.root / "generated"
        generated.mkdir()
        fixed = generated / "membership.json"
        fixed.write_text("keep")
        with self.assertRaises(auth_eval.EvalError):
            core_eval.create_membership_file(generated, {}, filename="membership.json")
        fixed.unlink()
        target = self.root / "outside"
        target.write_text("keep")
        fixed.symlink_to(target)
        with self.assertRaises(auth_eval.EvalError):
            core_eval.create_membership_file(generated, {}, filename="membership.json")
        self.assertEqual(target.read_text(), "keep")

    def test_auth_only_code_is_rejected_as_core_reuse(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": "a" * 40,
            },
        )
        (generated / "app.py").write_text(
            "from feature_auth import create_app, current_user\napp = create_app()\ndef profile(request): return current_user(request)\n"
        )
        with self.assertRaisesRegex(
            auth_eval.EvalError, "core-library-reuse-evidence-missing"
        ):
            core_eval.core_reuse_check(generated, "python", {}, "a" * 40)

    def test_unused_core_imports_and_exact_library_copies_are_rejected(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": "a" * 40,
            },
        )
        auth = "from feature_auth import create_app, current_user\napp = create_app()\ndef profile(request): return current_user(request)\n"
        imports = "from feature_standards.authorization import Policy\nfrom feature_standards.listing import parse_query, page\n"
        path = generated / "app.py"
        path.write_text(auth + imports)
        with self.assertRaisesRegex(
            auth_eval.EvalError, "core-library-reuse-evidence-missing"
        ):
            core_eval.core_reuse_check(generated, "python", {}, "a" * 40)
        path.write_text(
            auth
            + imports
            + "def product():\n return page([], parse_query('', None), Policy([]))\n"
        )
        core_eval.core_reuse_check(generated, "python", {}, "a" * 40)
        with self.assertRaisesRegex(auth_eval.EvalError, "copied-core-source-file"):
            core_eval.core_reuse_check(
                generated,
                "python",
                {
                    "libraries/python/feature_standards/listing.py": hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                },
                "a" * 40,
            )

    def test_frozen_source_uses_requested_git_objects_and_omits_secrets_skills(self):
        source_archive = self.archive(
            [
                ("libraries/python/library.py", tarfile.REGTYPE),
                (".env", tarfile.REGTYPE),
                (".agents/skills/x/SKILL.md", tarfile.REGTYPE),
                ("docs/superpowers/plans/x.md", tarfile.REGTYPE),
            ]
        )
        # Git archive is an uncompressed tar. The fake contains only fixed fixture bytes.
        stream = io.BytesIO()
        with (
            tarfile.open(fileobj=io.BytesIO(source_archive), mode="r:gz") as original,
            tarfile.open(fileobj=stream, mode="w:") as target,
        ):
            for member in original.getmembers():
                target.addfile(member, original.extractfile(member))
        catalog = self.archive([("package/src/cli.mjs", tarfile.REGTYPE)])
        destination = self.root / "frozen"
        with patch.object(
            core_eval.subprocess, "check_output", return_value=stream.getvalue()
        ) as command:
            result = core_eval.freeze_sources(
                self.root, destination, catalog, commit="a" * 40
            )
        command.assert_called_once_with(
            ["git", "archive", "--format=tar", "a" * 40], cwd=self.root
        )
        self.assertEqual(result["source_commit"], "a" * 40)
        self.assertFalse(result["source_dirty"])
        self.assertFalse((destination / ".env").exists())
        self.assertFalse((destination / ".agents").exists())
        self.assertFalse((destination / "docs/superpowers").exists())
        self.assertEqual(
            (destination / "AGENTS.md").read_text(), core_eval.SHARED_INSTRUCTIONS
        )
        self.assertEqual(
            result["source_sha256"],
            auth_eval.digest_hashes(auth_eval.fingerprint(destination)),
        )
        self.assertTrue(
            all(
                path.stat().st_mode & 0o222 == 0
                for path in destination.rglob("*")
                if path.is_file()
            )
        )

    def test_catalog_public_bytes_must_match_reviewed_sha256_and_integrity(self):
        data = self.archive([("package/src/cli.mjs", tarfile.REGTYPE)])
        digest = hashlib.sha256(data).hexdigest()
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
        docs = self.root / "docs"
        docs.mkdir()
        receipt = {
            "name": "feature-standards",
            "version": "0.3.2",
            "sourceCommit": core_eval.SOURCE_COMMIT,
            "localArtifactSha256": digest,
            "registry_verified": True,
            "public_download_verified": True,
            "dist": {"integrity": integrity},
        }
        (docs / "npm-release-0.3.2.json").write_text(json.dumps(receipt))
        metadata = json.dumps(
            {
                "name": "feature-standards",
                "version": "0.3.2",
                "dist": {
                    "integrity": integrity,
                    "tarball": "https://registry.npmjs.org/feature-standards/-/feature-standards-0.3.2.tgz",
                },
            }
        ).encode()
        with (
            patch.object(core_eval, "CATALOG_SHA256", digest),
            patch.object(core_eval, "_public_get", side_effect=[metadata, data]),
        ):
            archive, record = core_eval.catalog_archive(self.root)
        self.assertEqual(archive, data)
        self.assertTrue(record["catalog_public_download_verified"])
        with (
            patch.object(core_eval, "CATALOG_SHA256", digest),
            patch.object(core_eval, "_public_get", side_effect=[metadata, b"modified"]),
            self.assertRaisesRegex(auth_eval.EvalError, "catalog-artifact-mismatch"),
        ):
            core_eval.catalog_archive(self.root)

    def test_untrusted_registry_urls_and_duplicate_archive_members_fail(self):
        for url in (
            "http://registry.npmjs.org/a",
            "https://evil.example/a",
            "https://name:password@registry.npmjs.org/a",
        ):
            with (
                self.subTest(url=url),
                patch.object(core_eval, "urlopen") as request,
                self.assertRaises(auth_eval.EvalError),
            ):
                core_eval._public_get(url, 100)
            request.assert_not_called()
        with self.assertRaisesRegex(auth_eval.EvalError, "duplicate-archive-member"):
            core_eval.extract_archive(
                self.archive(
                    [
                        ("package/file", tarfile.REGTYPE),
                        ("package/FILE", tarfile.REGTYPE),
                    ]
                ),
                self.root / "duplicate",
            )

    def test_pair_order_alternates_across_stacks_and_repeats(self):
        order = ("baseline", "catalog")
        self.assertEqual(
            [core_eval.pair_order(order, 0, index, 4) for index in range(4)],
            [order, tuple(reversed(order)), order, tuple(reversed(order))],
        )
        self.assertEqual(core_eval.pair_order(order, 1, 0, 1), tuple(reversed(order)))

    def test_each_stack_flips_pair_order_on_second_four_stack_repeat(self):
        conditions = ("baseline", "catalog")
        for stack in range(4):
            first = core_eval.pair_order(conditions, 0, stack, 4)
            second = core_eval.pair_order(conditions, 1, stack, 4)
            self.assertEqual(second, tuple(reversed(first)))

    def test_core_checker_accepts_uv_cache_but_auth_default_remains_strict(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": "a" * 40,
            },
        )
        (generated / "app.py").write_text(
            "from feature_auth import create_app, current_user\nfrom feature_standards import Policy, parse_query, page\napp=create_app()\ndef profile(request): return current_user(request)\ndef product(): return page([],parse_query('',None),Policy([]))\n"
        )
        cache = generated / ".uv-cache"
        cache.mkdir()
        (cache / "cache-link").symlink_to(self.root / "not-source")
        with self.assertRaisesRegex(auth_eval.EvalError, "generated-source-symlink"):
            auth_eval.reuse_check(generated, "python", {}, "a" * 40)
        core_eval.core_reuse_check(generated, "python", {}, "a" * 40)

    def test_python_module_import_style_is_valid_core_reuse(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "python",
                "profile": "browser-session-v1",
                "source_commit": "a" * 40,
            },
        )
        (generated / "app.py").write_text(
            "from feature_auth import create_app, current_user\nfrom feature_standards import authorization as az, listing as ls\napp=create_app()\ndef profile(request): return current_user(request)\ndef product(): return ls.page([],ls.parse_query('',None),az.Policy([]))\n"
        )
        core_eval.core_reuse_check(generated, "python", {}, "a" * 40)

    def test_java_one_line_namespaced_pom_is_valid_dependency_evidence(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(
            generated / "integration.json",
            {
                "stack": "java",
                "profile": "browser-session-v1",
                "source_commit": "a" * 40,
            },
        )
        (generated / "Main.java").write_text(
            "import dev.featurestandards.auth.AuthService;\nimport dev.featurestandards.core.authorization.AuthorizationPolicy;\nimport dev.featurestandards.core.listing.Listing;\nclass Main { void product() { policy.decide(); Listing.parseQuery(); Listing.page(); }}\n"
        )
        (generated / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies><dependency><artifactId>java-spring-auth</artifactId></dependency><dependency><artifactId>feature-standards-core</artifactId></dependency></dependencies></project>'
        )
        core_eval.core_reuse_check(generated, "java", {}, "a" * 40)

    def test_java_string_wildcard_does_not_hide_another_files_api_calls(self):
        generated = self.root / "generated"
        generated.mkdir()
        auth_eval.write_json(generated / "integration.json", {
            "stack":"java","profile":"browser-session-v1","source_commit":"a"*40})
        auth = generated / "A.java"
        controller = generated / "B.java"
        advice = generated / "C.java"
        pom = generated / "pom.xml"
        auth.write_text('import dev.featurestandards.auth.AuthService;\nclass A { String path = "/**"; }\n')
        controller.write_text(
            "import dev.featurestandards.core.authorization.*;\n"
            "import dev.featurestandards.core.listing.Listing;\n"
            "class B { void route() { policy.decide(); Listing.parseQuery(); Listing.page(); } }\n")
        advice.write_text("/** independent advice comment */\nclass C {}\n")
        pom.write_text("<project><dependencies><dependency><artifactId>java-spring-auth</artifactId></dependency><dependency><artifactId>feature-standards-core</artifactId></dependency></dependencies></project>")
        files = [auth, controller, advice, pom]
        original_rglob = Path.rglob
        def ordered(path, pattern):
            if path == generated:
                return iter([p for p in files if p.match(pattern)])
            return original_rglob(path, pattern)
        with patch.object(Path, "rglob", ordered):
            core_eval.core_reuse_check(generated, "java", {}, "a" * 40)

    def test_model_and_timeout_validation_happens_before_account_or_output_work(self):
        base = [
            "core_eval.py",
            "--stack",
            "python",
            "--condition",
            "both",
            "--output",
            str(self.root / "output"),
        ]
        for options in (
            [],
            ["--model=-invalid"],
            ["--model=fixture-model", "--timeout=0"],
        ):
            with (
                patch.object(sys, "argv", base + options),
                patch.object(core_eval, "catalog_archive") as download,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as rejected,
            ):
                core_eval.main()
            self.assertEqual(rejected.exception.code, 2)
            download.assert_not_called()
        self.assertFalse((self.root / "output").exists())

    def test_fake_cli_contract_hooks_are_not_model_performance_evidence(self):
        template = self.root / "template"
        template.mkdir()
        (template / "source.txt").write_text("fixed-source")
        cli = self.root / "fake-cli"
        cli.write_text(
            f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\nif '--version' in sys.argv:\n print('fixture-core-cli 1.0');raise SystemExit(0)\nPath('prompt.txt').write_text(sys.stdin.read())\nprint(json.dumps({{'type':'turn.completed','usage':{{'input_tokens':1,'cached_input_tokens':0,'output_tokens':1}}}}))\n"
        )
        cli.chmod(0o700)
        cli.write_text(
            cli.read_text().replace(
                "Path('prompt.txt')",
                "Path('.uv-cache').mkdir(); Path('.uv-cache/link').symlink_to('../../source.txt'); Path('prompt.txt')",
            )
        )
        events = []

        def artifacts(generated, stack, source, commit):
            events.append("artifact-check")
            self.assertEqual(
                (generated / "prompt.txt").read_text(), "core-fixture-task"
            )

        def prepare(generated, env):
            events.append("prepare-grader")
            core_eval.create_membership_file(generated, env)

        def http(generated, env, port, origin, deadline):
            events.append("http-grader")
            self.assertTrue(Path(env["CORE_MEMBERSHIP_FILE"]).is_file())
            return ["fixture-only"]

        contract = auth_eval.TrialContract(
            profile="fixture-core",
            prompt_builder=lambda *args: "core-fixture-task",
            artifact_checker=artifacts,
            prepare_grader=prepare,
            http_grader=http,
        )
        contract.ignored_parts = (".uv-cache",)

        def grade(generated, output, env, port, origin, deadline, *, http_grader):
            return http_grader(port, origin, deadline)

        with patch.object(auth_eval, "grade", grade):
            result = auth_eval.run_trial(
                self.root,
                self.root / "trial",
                "python",
                "catalog",
                10,
                model="fixture-model",
                cli=str(cli),
                template=template,
                source_metadata={
                    "source_commit": "a" * 40,
                    "source_dirty": False,
                    "source_sha256": auth_eval.digest_hashes(
                        auth_eval.fingerprint(template)
                    ),
                },
                contract=contract,
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["profile"], "fixture-core")
        self.assertIsNone(result["baseline_ref"])
        self.assertEqual(events, ["artifact-check", "prepare-grader", "http-grader"])
        self.assertTrue(result["source_unchanged"])
        self.assertFalse((self.root / "trial/snapshot/generated/.uv-cache").exists())
        self.assertEqual(
            (self.root / "trial/result.json").stat().st_mode & 0o777, 0o600
        )


class ReplaySafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name).resolve()
        self.generated = self.work / "generated"
        self.generated.mkdir()
        self.trace = self.work / "trace.jsonl"
        with tempfile.TemporaryDirectory(prefix="feature-auth-eval-") as name:
            self.original = Path(name).resolve()

    def event(self, command="pwd", root=None):
        root = root or self.original
        self.trace.write_text(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": command,
                        "exit_code": 0,
                        "aggregated_output": str(root / "snapshot/generated") + "\n",
                    },
                }
            )
            + "\n"
        )

    def test_replay_output_overlap_normalizes_parent_components_first(self):
        with self.assertRaisesRegex(auth_eval.EvalError, "output-overlaps-original"):
            replay_smoke.replay(self.work, self.work / "bridge/../replay-new")
        with self.assertRaisesRegex(auth_eval.EvalError, "output-overlaps-original"):
            replay_smoke.replay(Path.home(), Path("~/replay-new"))
        self.assertFalse((self.work / "replay-new").exists())

    def test_workspace_needs_independent_trace_and_consistent_artifact_references(self):
        self.event()
        source = self.generated / "pom.xml"
        source.write_text(str(self.original / "snapshot/libraries/java"))
        self.assertEqual(
            replay_smoke.proven_root(self.trace, self.generated), self.original
        )
        self.event(command="echo claimed-pwd")
        with self.assertRaisesRegex(auth_eval.EvalError, "unproven"):
            replay_smoke.proven_root(self.trace, self.generated)
        self.trace.write_text(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "echo catalog/package/src/cli.mjs context",
                        "exit_code": 0,
                        "aggregated_output": json.dumps(
                            {
                                "readPath": str(
                                    self.original / "snapshot/catalog/package/README.md"
                                )
                            }
                        ),
                    },
                }
            )
            + "\n"
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "unproven"):
            replay_smoke.proven_root(self.trace, self.generated)
        self.event()
        source.write_text(
            str(self.original.parent / "feature-auth-eval-aaaaaaaa/snapshot")
        )
        with self.assertRaisesRegex(auth_eval.EvalError, "conflicting"):
            replay_smoke.proven_root(self.trace, self.generated)

    def test_workspace_rejects_existing_symlink_and_wrong_parent(self):
        self.event()
        self.original.symlink_to(self.generated, target_is_directory=True)
        try:
            with self.assertRaisesRegex(auth_eval.EvalError, "symlink"):
                replay_smoke.proven_root(self.trace, self.generated)
        finally:
            self.original.unlink()
        self.original.mkdir()
        try:
            with self.assertRaisesRegex(auth_eval.EvalError, "exists"):
                replay_smoke.proven_root(self.trace, self.generated)
        finally:
            self.original.rmdir()
        self.event(root=self.work / "feature-auth-eval-aaaaaaaa")
        with self.assertRaisesRegex(auth_eval.EvalError, "outside-owned-temp"):
            replay_smoke.proven_root(self.trace, self.generated)

    def test_generated_hash_ignores_only_exact_fixture_and_tool_cache(self):
        source = self.generated / "main.py"
        source.write_text("print('original')")
        fixture = self.generated / ".core-membership-" / "not-a-fixture.json"
        fixture.parent.mkdir()
        fixture.write_text("trusted-looking file is still source")
        before = replay_smoke.selected_files(self.generated)
        reference = auth_eval.fingerprint(self.work)
        self.assertTrue(replay_smoke.unchanged(self.work, before, reference))
        source.write_text("print('changed')")
        self.assertNotEqual(before, replay_smoke.selected_files(self.generated))
        self.assertFalse(replay_smoke.unchanged(self.work, before, reference))
        cache = self.generated / ".uv-cache"
        cache.mkdir()
        (cache / "link").symlink_to(self.work)
        self.assertIn(
            str(fixture.relative_to(self.generated)),
            replay_smoke.selected_files(self.generated),
        )
        source.unlink()
        source.symlink_to(fixture)
        with self.assertRaisesRegex(auth_eval.EvalError, "generated-symlink"):
            replay_smoke.selected_files(self.generated)

    def test_cleanup_refuses_replaced_root(self):
        self.original.mkdir(mode=0o700)
        owner = self.original.stat()
        identity = owner.st_dev, owner.st_ino
        displaced = self.original.with_name(self.original.name + "-displaced")
        self.original.rename(displaced)
        self.original.mkdir()
        try:
            with self.assertRaisesRegex(auth_eval.EvalError, "replaced"):
                replay_smoke.remove_owned_root(self.original, identity)
            self.assertTrue(self.original.is_dir())
            self.assertTrue(displaced.is_dir())
        finally:
            self.original.rmdir()
            displaced.rmdir()
