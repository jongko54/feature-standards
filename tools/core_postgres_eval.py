"""One Python source-candidate PostgreSQL integration feasibility observation."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import tomllib
import uuid
from contextlib import ExitStack
from pathlib import Path

import auth_eval
import core_eval
import core_reading_eval as reading
from auth_eval import EvalError

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "auth-rbac-postgres-v1"
CONDITIONS = ("catalog_compact",)
SOURCE_PATHS = (
    "implementations/python-fastapi/README.md",
    "implementations/python-fastapi/feature_auth/__init__.py",
    "libraries/python/README.md",
    "libraries/python/pyproject.toml",
    "libraries/python/feature_standards/authorization.py",
    "libraries/python/feature_standards/listing.py",
    "libraries/python/feature_standards/postgres_listing.py",
    "features/listing/catalog.json",
    "features/listing/postgres-list-v1.md",
    "docs/postgres-listing.md",
    "examples/core-python-postgres/README.md",
    "examples/core-python-postgres/app.py",
)
LIMITS = [
    "One Python integration feasibility observation, not an efficiency comparison or population estimate.",
    "Python core 0.2.0 and postgres-list-v1 are source candidates, not registry-publication evidence.",
    "Tokens are this execution's observed counts, not price, savings, unique prompt size or model internal reasoning.",
    "Static public-API call cues, unchanged source and independent HTTP success are distinct evidence; runtime reuse causality is not proved.",
    "The grader owns an isolated temporary PostgreSQL cluster; no application, shared test or production database is used.",
    "The large-row check covers scoped SQL data beyond 10000 rows and bounded navigation, not load, cursor traversal or a security audit.",
    "Authentication remains browser-session-v1 memory; no other language, React, SMTP or deployment is measured.",
]
_UNSAFE_ENV = (
    "FEATURE_STANDARDS_LISTING_TEST_DATABASE_URL",
    "PGHOSTADDR",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGOPTIONS",
)
RUNTIME_INPUTS = (
    "tests/postgres_listing_conformance.py",
    "tests/fixtures/core_listing.sql",
    "evals/core/tasks.json",
)


def runtime_inputs():
    captured = {}
    for relative in RUNTIME_INPUTS:
        path = ROOT / relative
        auth_eval.no_symlink(path)
        if not path.is_file() or not 0 < path.stat().st_size < 2_000_000:
            raise EvalError("postgres-runtime-inputs-unavailable")
        captured[relative] = path.read_bytes()
    return captured


def runtime_hashes(captured):
    return {name: hashlib.sha256(data).hexdigest() for name, data in captured.items()}


def source_validator(template, metadata, stacks):
    """Fail before a model call when the frozen source lacks the selected API."""
    if tuple(stacks) != ("python",):
        raise EvalError("postgres-eval-python-only")
    _owned_environment_guard()
    try:
        root = Path(template)
        if any(not (root / path).is_file() for path in SOURCE_PATHS):
            raise ValueError("missing selected source")
        package = tomllib.loads((root / "libraries/python/pyproject.toml").read_text())
        catalog = json.loads((root / "features/listing/catalog.json").read_text())
        profile = next(p for p in catalog["profiles"] if p["id"] == "postgres-list-v1")
        stack = next(s for s in catalog["stacks"] if s["id"] == "python")
        override = profile["stack_overrides"]["python"]
        if (
            metadata.get("catalog_version", "0.4.0") != "0.4.0"
            or package["project"]["version"] != "0.2.0"
            or "postgres" not in package["project"]["optional-dependencies"]
            or stack["package"]["version"] != "0.2.0"
            or stack["package"]["published"] is not False
            or "postgres-list-v1" not in stack["profiles"]
            or profile["specification"] != "features/listing/postgres-list-v1.md"
            or override["consumer"] != "examples/core-python-postgres"
            or override["entrypoints"][0]["path"]
            != "libraries/python/feature_standards/postgres_listing.py"
        ):
            raise ValueError("wrong selected source")
        tree = ast.parse(
            (
                root / "libraries/python/feature_standards/postgres_listing.py"
            ).read_text()
        )
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        if not {"PostgresListing", "VisibilityScope"}.issubset(classes) or not any(
            isinstance(node, ast.FunctionDef) and node.name == "page"
            for node in classes["PostgresListing"].body
        ):
            raise ValueError("missing public API")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        StopIteration,
        SyntaxError,
    ) as exc:
        raise EvalError("postgres-source-profile-mismatch") from exc
    inputs = runtime_hashes(runtime_inputs())
    if (
        metadata.get("tasks_sha256", inputs["evals/core/tasks.json"])
        != inputs["evals/core/tasks.json"]
    ):
        raise EvalError("postgres-runtime-inputs-changed")
    metadata["postgres_runtime_inputs_sha256"] = inputs


def prompt(stack, commit, tasks, condition):
    if stack != "python":
        raise EvalError("postgres-eval-python-only")
    if condition not in CONDITIONS:
        raise EvalError("invalid-postgres-condition")
    return f'''{tasks["stacks"]["python"]}
First run these three context commands from generated/:
node ../catalog/package/src/cli.mjs context --feature auth --stack python --profile browser-session-v1 --compact
node ../catalog/package/src/cli.mjs context --feature authorization --stack python --profile rbac-v1 --compact
node ../catalog/package/src/cli.mjs context --feature listing --stack python --profile postgres-list-v1 --compact
Read the selected public API/consumer paths. Profile IDs are not document filenames.

Current directory generated/ is writable; ../ is fixed read-only source at {commit}.
The CLI 0.4.0 archive and Python core 0.2.0 are local source candidates; do not infer registry publication.
Import existing auth and core packages as local path dependencies, with the core postgres extra.
Use feature_auth.create_app and current_user, Policy, ListingSchema,
feature_standards.postgres_listing.PostgresListing and VisibilityScope, and the adapter's instance page call.
Never copy library implementations or substitute the materialized page helper.
Read ../implementations/python-fastapi/README.md, ../libraries/python/README.md,
../docs/postgres-listing.md and ../examples/core-python-postgres/app.py as needed.
Only create files under generated/. Keep dependency/build outputs in conventional caches.

Keep /auth/* and GET /api/profile returning {{"user":{{"id":...,"email":...}}}} through the real existing session.
Preserve browser-session-v1 memory settings from AUTH_HOST, AUTH_PORT, AUTH_ALLOWED_ORIGIN and AUTH_*.
The grader injects demo=true/secure=false on loopback and checks real login/CSRF/logout/revocation.
Use a foreground server with the injected host/port and --no-proxy-headers.
Add GET /api/documents AND GET /api/documents/{{id}}. The PG example only supplies the collection route;
you must implement the item route with a parameterized DB read and the same policy.
Return only id/name/score/active. Missing and inaccessible item IDs both return403 FORBIDDEN.
Policy grants viewer documents:list at tenant scope and viewer documents:read at owner scope.
Every product request authenticates first and loads CURRENT membership from CORE_MEMBERSHIP_FILE.
The grader creates that private JSON file only AFTER you finish and rewrites it between requests; never create/cache it.
Its valid object is {{"subjectId":"demo-user","tenantId":"tenant-a","roles":["viewer"]}}; roles may be [].
Capture the original authenticated subject before a provider call, pass a copy of a mutable user map,
and compare returned subjectId against that original. Mismatch/no permission =>403 FORBIDDEN.
Missing/unreadable/invalid JSON or {{"unavailable":true}} =>generic503 AUTHORIZATION_UNAVAILABLE.
Never trust HTTP headers/query/body for membership, tenant, subject, roles, relation or columns.

The grader alone creates and seeds an owned temporary PostgreSQL cluster/schema/table AFTER model completion.
Do not create a DB, connect/probe/seed/migrate during generation, or embed fixture records in the app.
At runtime CORE_LISTING_CONNINFO is opaque psycopg keyword conninfo for a private Unix socket,
with explicit host/hostaddr/user/dbname/options. It is not the demo's TCP-only test URI.
Use psycopg.connect(os.environ["CORE_LISTING_CONNINFO"]) in an internal request connection factory;
do not send it through the example connect_database URL guard or fall back to AUTH_DATABASE_URL.
CORE_LISTING_SCHEMA and CORE_LISTING_TABLE are trusted runtime identifiers, not HTTP inputs.
The runtime app role has SELECT only; the grader retains the separate writer connection and changes rows after startup.
The supplied table has id text primary key; tenant_id text not null; owner_id nullable text;
name nonempty bounded text, score bigint within +/-9007199254740991 and active boolean; all public fields are NOT NULL.
IDs use [A-Za-z0-9][A-Za-z0-9._:-]{{0,63}}; names have <=256 scalars/1024 UTF-8 bytes and no ASCII controls.
Public columns are id/name/score/active; scope columns are tenant_id/owner_id. Do not expose scope columns.
Construct ListingSchema with sort fields id:string,name:string,score:integer,active:boolean
and filter fields name:string,score:integer,active:boolean. Construct PostgresListing with that schema,
table=(CORE_LISTING_SCHEMA, CORE_LISTING_TABLE), the explicit logical->DB public column map,
tenant_column="tenant_id", owner_column="owner_id". Never add client-selected SQL predicates.
Resolve collection/read policy and apply visibility BEFORE filtered totals: viewer uses
VisibilityScope(trusted_tenant, original_authenticated_subject). Both arguments are required;
explicit owner_id=None is tenant-wide and requires an actual tenant read grant.
Call adapter.page(connection, original_raw_query_without_question_mark, scope) on a fresh idle,
exclusively owned connection, then close it. page performs strict parsing and one read-only REPEATABLE READ
transaction for count/page. Active caller transactions are rejected; do not query first on that connection.
Retain raw query bytes before framework coercion; strict decoding/parser errors =>400 INVALID_LIST_QUERY.
Optional prevalidation may call parse_query, but never replace page with custom paging SQL.
For the separate item lookup, use psycopg.sql.Identifier for trusted relation/column identifiers
and bound placeholders for the requested ID and scope values; never interpolate values or raw SQL fragments.
String comparisons/sorting use COLLATE "C", and non-ID ties use ID ascending.
limit is1..100, offset0..10000; total can exceed10000. nextOffset=null when the next offset exceeds10000,
even if more rows remain. No cursor or unbounded traversal is supplied.
Map trusted schema/scope/transaction/data failures to generic500 and LISTING_UNAVAILABLE to generic503.
All product responses, including errors, require Cache-Control:no-store and X-Content-Type-Options:nosniff.
Use fixed generic messages; never expose SQL, conninfo, file paths, provider details or raw input.
No SMTP, React, other language, deployment or full repository test suite is needed.

Write run.json exactly {{"build":[{{"argv":["program","argument"],"cwd":"."}}],"start":{{"argv":["program","argument"],"cwd":"."}}}}.
Build accepts at most8 commands; cwd stays within generated/. Use argv arrays, not shell command strings.
Write integration.json exactly {{"stack":"python","profile":"browser-session-v1","source_commit":"{commit}"}}.
The grader independently builds/starts the app after completion. Do not ask questions, edit reference source,
commit/push, daemonize, read account credentials, or run repository-wide tests. Finish with short run instructions.
'''


def _qualified(node, bindings):
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified(node.value, bindings)
        return parent + "." + node.attr if parent else None
    return None


def _public_calls(tree):
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "feature_standards"
        ):
            bindings.update(
                {a.asname or a.name: node.module + "." + a.name for a in node.names}
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("feature_standards"):
                    bindings[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
    constructors = {
        "feature_standards.authorization.Policy": "Policy",
        "feature_standards.Policy": "Policy",
        "feature_standards.postgres_listing.PostgresListing": "PostgresListing",
        "feature_standards.postgres_listing.VisibilityScope": "VisibilityScope",
    }
    calls, instances = set(), set()

    def is_constructor(node):
        return (
            isinstance(node, ast.Call)
            and constructors.get(_qualified(node.func, bindings)) == "PostgresListing"
        )

    assignments = [
        n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
    ]
    # A small fixed point recognizes aliases and `store or PostgresListing(...)`.
    for _ in range(len(assignments) + 1):
        before = set(instances)
        for assignment in assignments:
            value = assignment.value
            values = value.values if isinstance(value, ast.BoolOp) else [value]
            if any(is_constructor(v) or _qualified(v, {}) in instances for v in values):
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                instances.update(filter(None, (_qualified(t, {}) for t in targets)))
        if before == instances:
            break
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = constructors.get(_qualified(node.func, bindings))
        if name:
            calls.add(name)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "page"
            and (
                is_constructor(node.func.value)
                or _qualified(node.func.value, {}) in instances
            )
        ):
            calls.add("PostgresListing.page")
    return calls


def postgres_reuse_check(generated, stack, source, commit):
    """Static executable call cues, never proof of runtime data flow or causality."""
    if stack != "python":
        raise EvalError("postgres-eval-python-only")
    auth_eval.reuse_check(
        generated, stack, source, commit, ignored_parts=core_eval.CORE_IGNORED_PARTS
    )
    digests = {
        digest
        for name, digest in source.items()
        if name.startswith("libraries/")
        and Path(name).suffix in {".py", ".go", ".java", ".rs"}
        and "test" not in name.lower()
    }
    used = set()
    for path in generated.rglob("*"):
        if any(
            part in core_eval.CORE_IGNORED_PARTS
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
            if path.suffix == ".py":
                used.update(_public_calls(ast.parse(data)))
    required = {"Policy", "PostgresListing", "VisibilityScope", "PostgresListing.page"}
    if not required.issubset(used):
        raise EvalError("postgres-library-reuse-evidence-missing")
    return sorted(required)


def static_reuse(generated, source, stack, commit):
    evidence = {
        "kind": "static-public-auth-rbac-postgres-call-evidence",
        "runtime_causality_proven": False,
    }
    try:
        calls = postgres_reuse_check(generated, stack, source, commit)
        return evidence | {"passed": True, "public_api_calls": calls}
    except (EvalError, OSError, ValueError, SyntaxError) as exc:
        return evidence | {
            "passed": False,
            "error_code": str(exc)
            if isinstance(exc, EvalError)
            else "static-check-unavailable",
        }


def _owned_environment_guard():
    if any(name in os.environ for name in _UNSAFE_ENV):
        raise EvalError("postgres-eval-owned-fixture-only")


def _load_runtime():
    """Import the optional driver/harness only after the model has completed."""
    import psycopg

    specification = importlib.util.spec_from_file_location(
        "_core_postgres_eval_listing_fixture",
        ROOT / "tests/postgres_listing_conformance.py",
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.ListingDatabase, psycopg


def _insert_documents(database, driver, documents):
    statement = driver.sql.SQL(
        "INSERT INTO {} (id, tenant_id, owner_id, name, score, active) VALUES (%s, %s, %s, %s, %s, %s)"
    ).format(driver.sql.Identifier(database.schema, "documents"))
    rows = (
        (d["id"], d["tenantId"], d["ownerId"], d["name"], d["score"], d["active"])
        for d in documents
    )
    with driver.connect(database.conninfo) as connection, connection.cursor() as cursor:
        cursor.executemany(statement, rows)


def _drop_reader(database, driver, role):
    with driver.connect(database.conninfo, autocommit=True) as connection:
        connection.execute(
            driver.sql.SQL("REVOKE SELECT ON TABLE {} FROM {}").format(
                driver.sql.Identifier(database.schema, "documents"),
                driver.sql.Identifier(role),
            )
        )
        connection.execute(
            driver.sql.SQL("REVOKE USAGE ON SCHEMA {} FROM {}").format(
                driver.sql.Identifier(database.schema), driver.sql.Identifier(role)
            )
        )
        connection.execute(
            driver.sql.SQL("DROP ROLE {}").format(driver.sql.Identifier(role))
        )


def _reader_conninfo(database, driver, resources):
    role = "core_listing_reader_" + uuid.uuid4().hex
    with driver.connect(database.conninfo, autocommit=True) as connection:
        connection.execute(
            driver.sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(driver.sql.Identifier(role))
        )
        resources.callback(_drop_reader, database, driver, role)
        connection.execute(
            driver.sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                driver.sql.Identifier(database.schema), driver.sql.Identifier(role)
            )
        )
        connection.execute(
            driver.sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
                driver.sql.Identifier(database.schema, "documents"),
                driver.sql.Identifier(role),
            )
        )
    return driver.conninfo.make_conninfo(database.conninfo, user=role)


def _large_http_grade(database, driver, port, origin, deadline, checks):
    _insert_documents(
        database,
        driver,
        (
            {
                "id": f"bulk-{n:05d}",
                "tenantId": "tenant-a",
                "ownerId": "demo-user",
                "name": "Bulk",
                "score": 0,
                "active": True,
            }
            for n in range(10001)
        ),
    )

    def expect(name, actual, expected):
        # JSON equality is type-sensitive: Python otherwise treats True as 1.
        if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise EvalError(name)
        checks.append(name)

    status, headers, _ = auth_eval.request(
        port,
        "POST",
        "/auth/login",
        origin,
        deadline,
        body={
            "email": "demo@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    expect("postgres-relogin-200", status, 200)
    cookie = next(
        (v for k, v in headers.items() if k.lower() == "set-cookie"), ""
    ).split(";", 1)[0]
    expect(
        "postgres-relogin-cookie",
        bool(re.fullmatch(r"fs_session=[A-Za-z0-9_-]{43}", cookie)),
        True,
    )
    status, headers, body = auth_eval.request(
        port,
        "GET",
        "/api/documents?sort=id&limit=1&offset=10000",
        origin,
        deadline,
        cookie=cookie,
    )
    expect("postgres-large-status", status, 200)
    expect(
        "postgres-large-page",
        body,
        {
            "items": [{"id": "bulk-10000", "name": "Bulk", "score": 0, "active": True}],
            "total": 10003,
            "limit": 1,
            "offset": 10000,
            "nextOffset": None,
        },
    )
    headers = {k.lower(): v for k, v in headers.items()}
    expect("postgres-large-no-store", headers.get("cache-control"), "no-store")
    expect("postgres-large-nosniff", headers.get("x-content-type-options"), "nosniff")
    return checks


def trial_contract(resources):
    """The outer lifetime ends only after the common runner stops its server."""
    cases = {}
    captured = runtime_inputs()
    expected_hashes = runtime_hashes(captured)
    documents = json.loads(captured["evals/core/tasks.json"])["documents"]

    def check_runtime_inputs():
        if runtime_hashes(runtime_inputs()) != expected_hashes:
            raise EvalError("postgres-runtime-inputs-changed")

    def artifact_checker(generated, stack, source, commit):
        source_validator(generated.parent, {}, (stack,))
        postgres_reuse_check(generated, stack, source, commit)

    def prepare_grader(generated, env):
        _owned_environment_guard()
        if generated in cases:
            raise EvalError("postgres-fixture-already-prepared")
        check_runtime_inputs()
        source_validator(generated.parent, {}, ("python",))
        try:
            database_type, driver = _load_runtime()
        except ImportError as exc:
            raise EvalError("postgres-eval-dependencies-unavailable") from exc
        try:
            database = resources.enter_context(database_type())
            if database.temporary is None or not database.cluster_started:
                raise EvalError("postgres-eval-owned-fixture-only")
            check_runtime_inputs()
            _insert_documents(database, driver, documents)
            conninfo = _reader_conninfo(database, driver, resources)
            core_eval.create_membership_file(generated, env)
            env.update(
                CORE_LISTING_CONNINFO=conninfo,
                CORE_LISTING_SCHEMA=database.schema,
                CORE_LISTING_TABLE="documents",
            )
            cases[generated] = (database, driver)
        except (OSError, RuntimeError, driver.Error) as exc:
            raise EvalError("postgres-eval-fixture-unavailable") from exc

    def http_grader(generated, env, port, origin, deadline):
        if generated not in cases:
            raise EvalError("postgres-fixture-not-prepared")
        checks = core_eval.core_http_grade(
            port, origin, deadline, Path(env["CORE_MEMBERSHIP_FILE"])
        )
        database, driver = cases[generated]
        try:
            return _large_http_grade(database, driver, port, origin, deadline, checks)
        except driver.Error as exc:
            raise EvalError("postgres-eval-fixture-unavailable") from exc

    return auth_eval.TrialContract(
        profile=PROFILE,
        prompt_builder=prompt,
        artifact_checker=artifact_checker,
        prepare_grader=prepare_grader,
        http_grader=http_grader,
        ignored_parts=core_eval.CORE_CACHE_PARTS,
    )


def main():
    with ExitStack() as resources:
        return reading.main(
            experiment={
                "id": PROFILE,
                "conditions": CONDITIONS,
                "prompt": prompt,
                "contract_factory": lambda: trial_contract(resources),
                "source_file": __file__,
                "default_repeats": 1,
                "limits": LIMITS,
                "allowed_stacks": ("python",),
                "reuse_checker": static_reuse,
                "source_validator": source_validator,
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
