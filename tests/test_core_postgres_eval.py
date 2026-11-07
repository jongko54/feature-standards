"""PostgreSQL evaluation boundary tests; no model, PostgreSQL or build execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import core_postgres_eval as pg

COMMIT = "a" * 40
TASKS = json.loads((ROOT / "evals/core/tasks.json").read_text())
VALID = """from fastapi import Depends
from feature_auth import create_app, current_user
from feature_standards.authorization import Policy
from feature_standards.postgres_listing import PostgresListing, VisibilityScope
app = create_app()
policy = Policy([])
store = PostgresListing(schema=schema, table=table, columns=columns,
                        tenant_column="tenant_id", owner_column="owner_id")
def documents(user=Depends(current_user)):
    return store.page(connection, raw_query, VisibilityScope("tenant-a", user["id"]))
"""
FACTORY_VALID = (
    VALID.split("store = ", 1)[0]
    + """def adapter():
    return PostgresListing(schema=schema, table=table, columns=columns,
                           tenant_column="tenant_id", owner_column="owner_id")
def documents(user=Depends(current_user)):
    store = adapter()
    return store.page(connection, raw_query, VisibilityScope("tenant-a", user["id"]))
"""
)


class SourceAndPromptTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_frozen_python_source_candidate_is_accepted(self):
        pg.source_validator(ROOT, {"catalog_version": "0.4.0"}, ("python",))
        for path in pg.SOURCE_PATHS:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_other_stack_is_rejected_before_source_reads(self):
        with self.assertRaisesRegex(pg.EvalError, "postgres-eval-python-only"):
            pg.source_validator(Path("/missing-source"), {}, ("go",))

    def test_wrong_candidate_version_or_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            for relative in pg.SOURCE_PATHS:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            package = root / "libraries/python/pyproject.toml"
            package.write_text(
                package.read_text().replace('version = "0.2.0"', 'version = "0.1.0"')
            )
            with self.assertRaisesRegex(
                pg.EvalError, "postgres-source-profile-mismatch"
            ):
                pg.source_validator(root, {}, ("python",))
            shutil.copyfile(ROOT / "libraries/python/pyproject.toml", package)
            catalog = root / "features/listing/catalog.json"
            data = json.loads(catalog.read_text())
            data["profiles"] = [
                p for p in data["profiles"] if p["id"] != "postgres-list-v1"
            ]
            catalog.write_text(json.dumps(data))
            with self.assertRaisesRegex(
                pg.EvalError, "postgres-source-profile-mismatch"
            ):
                pg.source_validator(root, {}, ("python",))
        with self.assertRaisesRegex(pg.EvalError, "postgres-source-profile-mismatch"):
            pg.source_validator(ROOT, {"catalog_version": "0.3.2"}, ("python",))

    def test_prompt_has_three_compact_profiles_and_runtime_only_database(self):
        text = pg.prompt("python", COMMIT, TASKS, "catalog_compact")
        commands = [line for line in text.splitlines() if line.startswith("node ")]
        self.assertEqual(len(commands), 3)
        for command, feature, profile in zip(
            commands,
            ("auth", "authorization", "listing"),
            ("browser-session-v1", "rbac-v1", "postgres-list-v1"),
        ):
            self.assertIn(
                f"--feature {feature} --stack python --profile {profile} --compact",
                command,
            )
        for marker in (
            "CORE_LISTING_CONNINFO",
            "CORE_LISTING_SCHEMA",
            "CORE_LISTING_TABLE",
            "CORE_MEMBERSHIP_FILE",
            "PostgresListing",
            "VisibilityScope",
            "documents/{id}",
            "idle",
            "psycopg.sql.Identifier",
            "10000",
            "100",
            "no-store",
            "nosniff",
        ):
            self.assertIn(marker, text)
        self.assertIn("grader alone creates and seeds", text)
        self.assertIn("original authenticated subject", text)
        self.assertIn('"profile":"browser-session-v1"', text)
        self.assertNotIn("--profile offset-list-v1", text)
        self.assertNotIn("own-a", text)
        for stack, condition in (("go", "catalog_compact"), ("python", "manual")):
            with self.assertRaises(pg.EvalError):
                pg.prompt(stack, COMMIT, TASKS, condition)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.generated = Path(self.temporary.name).resolve()
        (self.generated / "integration.json").write_text(
            json.dumps(
                {
                    "stack": "python",
                    "profile": "browser-session-v1",
                    "source_commit": COMMIT,
                }
            )
        )

    def evidence(self, text=VALID, source=None):
        (self.generated / "app.py").write_text(text)
        return pg.static_reuse(self.generated, source or {}, "python", COMMIT)

    def test_pg_instance_page_accepts_public_api_without_materialized_parser(self):
        evidence = self.evidence()
        self.assertTrue(evidence["passed"], evidence)
        self.assertEqual(
            set(evidence["public_api_calls"]),
            {"Policy", "PostgresListing", "VisibilityScope", "PostgresListing.page"},
        )
        self.assertFalse(evidence["runtime_causality_proven"])

    def test_module_and_instance_aliases_are_recognized(self):
        text = VALID.replace(
            "from feature_standards.postgres_listing import PostgresListing, VisibilityScope",
            "from feature_standards import postgres_listing as db",
        )
        text = text.replace("PostgresListing(", "db.PostgresListing(").replace(
            "VisibilityScope(", "db.VisibilityScope("
        )
        text = text.replace("def documents", "reader = store\ndef documents").replace(
            "return store.page", "return reader.page"
        )
        self.assertTrue(self.evidence(text)["passed"])

    def test_verified_public_consumer_constructor_and_page_shapes_are_recognized(self):
        text = (ROOT / "examples/core-python-postgres/app.py").read_text()
        result = self.evidence(text)
        self.assertTrue(result["passed"], result)

    def test_zero_argument_top_level_factory_page_flow_is_recognized(self):
        for text in (
            FACTORY_VALID,
            FACTORY_VALID.replace(
                "def adapter():\n", 'def adapter():\n    """Fresh public reader."""\n'
            ),
            FACTORY_VALID.replace(
                "from feature_standards.postgres_listing import PostgresListing, VisibilityScope",
                "from feature_standards import postgres_listing as db",
            )
            .replace("PostgresListing(", "db.PostgresListing(")
            .replace("VisibilityScope(", "db.VisibilityScope("),
        ):
            with self.subTest(shape="simple factory"):
                evidence = self.evidence(text)
                self.assertTrue(evidence["passed"], evidence)
                self.assertIn("PostgresListing.page", evidence["public_api_calls"])
                self.assertFalse(evidence["runtime_causality_proven"])

    def test_factory_inference_rejects_unsupported_return_and_call_shapes(self):
        for text in (
            FACTORY_VALID.replace("def adapter():", "@decorate\ndef adapter():"),
            FACTORY_VALID.replace("def adapter():", "async def adapter():"),
            FACTORY_VALID.replace("def adapter():", "def adapter(option=None):"),
            FACTORY_VALID.replace("store = adapter()", "store = adapter(option=True)"),
            FACTORY_VALID.replace("store = adapter()", "store = adapter(1)"),
            FACTORY_VALID.replace(
                "    return PostgresListing(",
                "    if condition:\n        return PostgresListing(",
            ),
            FACTORY_VALID.replace(
                "def adapter():\n    return PostgresListing(",
                "def outer():\n    def adapter():\n        return PostgresListing(",
            ),
            FACTORY_VALID.replace(
                "def adapter():\n", "def adapter():\n    prepare()\n"
            ),
        ):
            with self.subTest(shape="unsupported factory"):
                self.assertFalse(self.evidence(text)["passed"])

    def test_unrelated_local_page_is_not_credited_as_factory_adapter_page(self):
        text = FACTORY_VALID.replace(
            "def adapter():\n    return PostgresListing(",
            "def adapter():\n    return LocalReader( ",
        )
        text += "\nunused = PostgresListing(schema=schema)\nclass LocalReader:\n    def __init__(self, **kwargs): pass\n    def page(self, *args): return {}\n"
        self.assertFalse(self.evidence(text)["passed"])

    def test_strings_imports_and_unrelated_page_are_not_reuse(self):
        for text in (
            VALID.replace("return store.page", "return fake.page"),
            VALID.replace("policy = Policy([])", 'policy = "Policy([])"'),
            VALID.replace('VisibilityScope("tenant-a", user["id"])', "None"),
            VALID.replace(
                'PostgresListing(schema=schema, table=table, columns=columns,\n                        tenant_column="tenant_id", owner_column="owner_id")',
                "object()",
            ),
        ):
            with self.subTest(text=text):
                self.assertFalse(self.evidence(text)["passed"])
        materialized = VALID.replace("return store.page", "return page")
        self.assertFalse(self.evidence(materialized)["passed"])

    def test_auth_provenance_boundary_and_exact_core_copy_are_rejected(self):
        self.assertFalse(
            self.evidence(VALID.replace("Depends(current_user)", "None"))["passed"]
        )
        copied = self.generated / "copy.py"
        copied.write_text(VALID)
        source = {
            "libraries/python/feature_standards/postgres_listing.py": hashlib.sha256(
                copied.read_bytes()
            ).hexdigest()
        }
        result = self.evidence(source=source)
        self.assertEqual(result["error_code"], "copied-core-source-file")
        copied.unlink()
        (self.generated / "integration.json").write_text("{}")
        self.assertEqual(self.evidence()["error_code"], "provenance-mismatch")

    def test_generated_source_symlink_is_rejected(self):
        target = self.generated / "target.txt"
        target.write_text("untrusted")
        (self.generated / "linked.py").symlink_to(target)
        self.assertEqual(self.evidence()["error_code"], "generated-source-symlink")


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def executemany(self, statement, rows):
        self.owner.batches.append((statement.as_string(), list(rows)))


class FakeConnection(FakeCursor):
    def execute(self, statement, parameters=None):
        self.owner.statements.append(
            (
                statement.as_string() if hasattr(statement, "as_string") else statement,
                parameters,
            )
        )

    def cursor(self):
        return FakeCursor(self.owner)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import conninfo, sql

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.generated = Path(self.temporary.name).resolve() / "generated"
        self.generated.mkdir()
        self.events, self.batches, self.statements = [], [], []
        self.connects = []
        owner = self
        fixture_conninfo = conninfo.make_conninfo(
            host="/owned/socket",
            hostaddr="",
            port=5432,
            user="feature_listing_test",
            dbname="postgres",
            options="",
            sslmode="disable",
        )

        class Database:
            temporary = Path("/owned-fixture")
            cluster_started = True
            schema = "core_listing_fixture"
            conninfo = fixture_conninfo

            def __enter__(self):
                owner.events.append("database-enter")
                return self

            def __exit__(self, *_):
                owner.events.append("database-exit")

        def connect(value, **kwargs):
            self.connects.append((value, kwargs))
            return FakeConnection(self)

        self.runtime = (
            Database,
            types.SimpleNamespace(
                connect=connect, sql=sql, conninfo=conninfo, Error=psycopg.Error
            ),
        )
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        self.load_runtime = patch.object(
            pg, "_load_runtime", return_value=self.runtime
        ).start()
        patch.object(pg, "source_validator").start()

    def test_fixture_is_lazy_and_external_configuration_is_rejected_before_io(self):
        with ExitStack() as resources:
            contract = pg.trial_contract(resources)
            self.assertEqual(self.events, [])
            self.load_runtime.assert_not_called()
            for name in (
                "FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL",
                "PGHOSTADDR",
                "PGSERVICE",
                "PGSERVICEFILE",
                "PGOPTIONS",
            ):
                with (
                    self.subTest(name=name),
                    patch.dict(os.environ, {name: ""}),
                    self.assertRaisesRegex(
                        pg.EvalError, "postgres-eval-owned-fixture-only"
                    ),
                ):
                    contract.prepare_grader(self.generated, {})
            self.assertEqual(self.events, [])
            self.assertEqual(self.connects, [])
            self.load_runtime.assert_not_called()

    def test_prepare_seeds_exact_four_rows_and_app_has_a_select_only_role(self):
        with ExitStack() as resources:
            contract = pg.trial_contract(resources)
            env = {}
            contract.prepare_grader(self.generated, env)
            self.assertEqual(self.events, ["database-enter"])
            self.assertEqual(
                self.batches[0][1],
                [
                    ("own-b", "tenant-a", "demo-user", "Beta", 2, False),
                    ("other-owner", "tenant-a", "other-user", "Private", 10, True),
                    ("other-tenant", "tenant-b", "demo-user", "Secret", 99, True),
                    ("own-a", "tenant-a", "demo-user", "Alpha", 2, True),
                ],
            )
            self.assertIn(
                'INSERT INTO "core_listing_fixture"."documents"', self.batches[0][0]
            )
            self.assertEqual(self.batches[0][0].count("%s"), 6)
            from psycopg.conninfo import conninfo_to_dict

            fields = conninfo_to_dict(env["CORE_LISTING_CONNINFO"])
            self.assertTrue(fields["user"].startswith("core_listing_reader_"))
            self.assertEqual(fields["host"], "/owned/socket")
            self.assertEqual(fields["hostaddr"], "")
            self.assertEqual(fields["options"], "")
            self.assertEqual(env["CORE_LISTING_SCHEMA"], "core_listing_fixture")
            self.assertEqual(env["CORE_LISTING_TABLE"], "documents")
            self.assertNotIn("FEATURE_STANDARDS_LISTING_DATABASE_URL", env)
            membership = Path(env["CORE_MEMBERSHIP_FILE"])
            self.assertEqual(json.loads(membership.read_text()), pg.core_eval.VIEWER)
            self.assertEqual(membership.stat().st_mode & 0o777, 0o600)
            grants = "\n".join(query for query, _ in self.statements)
            self.assertIn(
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS",
                grants,
            )
            self.assertIn(
                'GRANT SELECT ON TABLE "core_listing_fixture"."documents"', grants
            )
            self.assertNotIn("GRANT ALL", grants)
            self.assertNotIn("GRANT INSERT", grants)
        self.assertEqual(self.events[-1], "database-exit")
        self.assertIn("DROP ROLE", self.statements[-1][0])

    def test_runtime_input_changes_are_rejected_before_loading_or_starting_db(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as resources:
            root = Path(temporary).resolve()
            for relative in (
                "tests/postgres_listing_conformance.py",
                "tests/fixtures/core_listing.sql",
                "evals/core/tasks.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(TASKS) if relative.endswith(".json") else "fixture"
                )
            with patch.object(pg, "ROOT", root):
                contract = pg.trial_contract(resources)
                (root / "tests/fixtures/core_listing.sql").write_text(
                    "changed after model started"
                )
                with self.assertRaisesRegex(
                    pg.EvalError, "postgres-runtime-inputs-changed"
                ):
                    contract.prepare_grader(self.generated, {})
            self.load_runtime.assert_not_called()
            self.assertEqual(self.events, [])

    def test_existing_http_checks_then_live_bulk_data_boundary_and_fresh_session(self):
        with ExitStack() as resources:
            contract = pg.trial_contract(resources)
            env = {}
            contract.prepare_grader(self.generated, env)

            def base(*_):
                self.events.append("base-http")
                self.assertEqual(len(self.batches), 1)
                return ["base-http-check"]

            def request(_port, method, path, _origin, _deadline, **kwargs):
                if method == "POST":
                    self.events.append("fresh-login")
                    return (
                        200,
                        {"Set-Cookie": "fs_session=" + "x" * 43 + "; Path=/"},
                        {"csrfToken": "c" * 43},
                    )
                self.assertEqual(path, "/api/documents?sort=id&limit=1&offset=10000")
                self.assertEqual(kwargs["cookie"], "fs_session=" + "x" * 43)
                rows = self.batches[0][1] + self.batches[1][1]
                visible = sorted(
                    (r for r in rows if r[1:3] == ("tenant-a", "demo-user")),
                    key=lambda r: r[0],
                )
                selected = visible[10000]
                self.assertEqual(len(rows), 10005)
                self.assertEqual(len(visible), 10003)
                self.assertEqual(len({row[0] for row in rows}), len(rows))
                self.assertEqual(selected[0], "bulk-10000")
                return (
                    200,
                    {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                    {
                        "items": [
                            {
                                "id": selected[0],
                                "name": selected[3],
                                "score": selected[4],
                                "active": selected[5],
                            }
                        ],
                        "total": len(visible),
                        "limit": 1,
                        "offset": 10000,
                        "nextOffset": None,
                    },
                )

            with (
                patch.object(pg.core_eval, "core_http_grade", side_effect=base),
                patch.object(pg.auth_eval, "request", side_effect=request),
            ):
                checks = contract.http_grader(
                    self.generated, env, 1234, "http://127.0.0.1:1234", 999
                )
            self.assertEqual(checks[0], "base-http-check")
            self.assertIn("postgres-large-page", checks)
            self.assertEqual(
                self.events[:3], ["database-enter", "base-http", "fresh-login"]
            )
            self.assertEqual(len(self.batches[1][1]), 10001)

    def test_wrong_large_total_or_navigation_result_fails(self):
        for changes in (
            {"total": 2},
            {"nextOffset": 10001},
            {"items": []},
            {"items": [{"id": "bulk-10000", "name": "Bulk", "score": 0, "active": 1}]},
            {"limit": True},
        ):
            with (
                self.subTest(changes=changes),
                tempfile.TemporaryDirectory() as name,
                ExitStack() as resources,
            ):
                generated = Path(name).resolve()
                contract = pg.trial_contract(resources)
                env = {}
                contract.prepare_grader(generated, env)
                body = {
                    "items": [
                        {"id": "bulk-10000", "name": "Bulk", "score": 0, "active": True}
                    ],
                    "total": 10003,
                    "limit": 1,
                    "offset": 10000,
                    "nextOffset": None,
                } | changes
                with (
                    patch.object(pg.core_eval, "core_http_grade", return_value=[]),
                    patch.object(
                        pg.auth_eval,
                        "request",
                        side_effect=[
                            (200, {"Set-Cookie": "fs_session=" + "x" * 43}, {}),
                            (
                                200,
                                {
                                    "Cache-Control": "no-store",
                                    "X-Content-Type-Options": "nosniff",
                                },
                                body,
                            ),
                        ],
                    ),
                    self.assertRaisesRegex(pg.EvalError, "postgres-large-page"),
                ):
                    contract.http_grader(generated, env, 1234, "origin", 999)

    def test_failed_base_http_never_adds_bulk_and_fixture_is_cleaned(self):
        with (
            self.assertRaisesRegex(pg.EvalError, "base-failed"),
            ExitStack() as resources,
        ):
            contract = pg.trial_contract(resources)
            env = {}
            contract.prepare_grader(self.generated, env)
            with patch.object(
                pg.core_eval,
                "core_http_grade",
                side_effect=pg.EvalError("base-failed"),
            ):
                contract.http_grader(self.generated, env, 1234, "origin", 999)
        self.assertEqual(len(self.batches), 1)
        self.assertEqual(self.events[-1], "database-exit")

    def test_non_owned_fixture_cannot_reach_grader_connect(self):
        self.runtime[0].temporary = None
        with (
            ExitStack() as resources,
            self.assertRaisesRegex(pg.EvalError, "postgres-eval-owned-fixture-only"),
        ):
            pg.trial_contract(resources).prepare_grader(self.generated, {})
        self.assertEqual(self.connects, [])

    def test_partial_role_grant_failure_is_sanitized_and_cleans_owned_resources(self):
        execute = FakeConnection.execute

        def failed_grant(connection, statement, parameters=None):
            if statement.as_string().startswith("GRANT SELECT"):
                raise self.runtime[1].Error("private-provider-detail")
            return execute(connection, statement, parameters)

        with (
            self.assertRaisesRegex(pg.EvalError, "^postgres-eval-fixture-unavailable$"),
            ExitStack() as resources,
            patch.object(FakeConnection, "execute", failed_grant),
        ):
            pg.trial_contract(resources).prepare_grader(self.generated, {})
        self.assertEqual(self.events[-1], "database-exit")
        self.assertIn("DROP ROLE", self.statements[-1][0])


class MainTests(unittest.TestCase):
    def test_thin_main_passes_hooks_and_cleanup_outlives_common_server_stop(self):
        events = []

        def common_main(*, experiment):
            self.assertEqual(experiment["id"], pg.PROFILE)
            self.assertEqual(experiment["conditions"], ("catalog_compact",))
            self.assertEqual(experiment["allowed_stacks"], ("python",))
            self.assertEqual(experiment["default_repeats"], 1)
            self.assertEqual(experiment["source_validator"], pg.source_validator)
            self.assertEqual(experiment["reuse_checker"], pg.static_reuse)
            self.assertEqual(
                Path(experiment["source_file"]).resolve(), Path(pg.__file__).resolve()
            )
            experiment["contract_factory"]()
            events.append("server-stop")
            raise pg.EvalError("grading-failed")

        def contract(resources):
            events.append("contract-created")
            resources.callback(events.append, "fixture-cleanup")

        with (
            patch.object(pg.reading, "main", side_effect=common_main),
            patch.object(pg, "trial_contract", side_effect=contract),
            self.assertRaisesRegex(pg.EvalError, "grading-failed"),
        ):
            pg.main()
        self.assertEqual(events, ["contract-created", "server-stop", "fixture-cleanup"])


if __name__ == "__main__":
    unittest.main()
