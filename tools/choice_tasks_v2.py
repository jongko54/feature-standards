"""Paired optional-guidance tasks with an independent private-data ticket grader.

The v1 documents task and its 143 checks remain unchanged. The treatment only
appends one optional documentation pointer to the common v2 task body.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode

import auth_eval
import choice_tasks
import core_discovery_eval as discovery
import core_eval
from auth_eval import EvalError

SCENARIOS = ("documents", "tickets")
CONDITIONS = ("baseline", "sdk-pointer")
TICKETS_ASSERTIONS = 727
PUBLIC_FIELDS = ("id", "subject", "priority", "closed")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z", re.ASCII)
BUILD_GUIDANCE = """
SDK dependency, vendored/copied source, or direct implementation are all accepted.

BUILD guidance (applies to every implementation approach):
The grader runs build again in the existing workspace after generation. All build commands must be rerunnable.
A .venv may already exist. When uv is available, `uv venv --python 3.13 --allow-existing .venv` followed by
`uv pip install --python .venv/bin/python ...` works; do not assume a uv-created environment contains pip.
Generated source and configuration files must each be at most 2,000,000 bytes.
Keep dependency and build outputs in conventional .venv, .cache, target or bin directories.
Use normal online dependency resolution when packages are absent from local caches; do not force offline resolution.
"""


def _validate_selection(scenario, condition=None):
    if scenario not in SCENARIOS:
        raise EvalError("unsupported-guidance-scenario")
    if condition is not None and condition not in CONDITIONS:
        raise EvalError("unsupported-guidance-condition")


def expected_assertions(scenario):
    _validate_selection(scenario)
    return 143 if scenario == "documents" else TICKETS_ASSERTIONS


def ticket_fixture(seed: str) -> list[dict]:
    """Fresh synthetic rows derived solely from a private paired-trial seed."""
    if not isinstance(seed, str) or not seed:
        raise EvalError("invalid-ticket-fixture-seed")
    digest = hashlib.sha256(seed.encode()).hexdigest()
    token = digest[:10]
    # Deliberate ties, Unicode scalar ordering, both booleans, and three scopes.
    shapes = (
        ("Access + %41 Ω", 2, False, "tenant-a", "demo-user"),
        ("Access + %41 Ω", 2, True, "tenant-a", "demo-user"),
        ("Renewal", 5, False, "tenant-a", "demo-user"),
        ("\ue000 queue", 1, True, "tenant-a", "demo-user"),
        ("𐀀 queue", 3, False, "tenant-a", "demo-user"),
        ("Dispatch", 4, False, "tenant-a", "other-user"),
        ("Access + %41 Ω", 1, True, "tenant-a", "other-user"),
        ("Dispatch archive", 5, True, "tenant-a", "other-user"),
        ("Foreign", 5, False, "tenant-b", "demo-user"),
        ("Foreign archive", 4, True, "tenant-b", "other-user"),
        ("Foreign queue", 2, False, "tenant-b", "other-user"),
    )
    rows = [
        {
            "id": f"t-{token}-{index:02d}",
            "subject": f"{subject} {token}",
            "priority": priority,
            "closed": closed,
            "tenantId": tenant,
            "ownerId": owner,
        }
        for index, (subject, priority, closed, tenant, owner) in enumerate(shapes)
    ]
    random.Random(int(digest, 16)).shuffle(rows)
    return rows


def ticket_fixture_bytes(data: list[dict]) -> bytes:
    """Canonical private-fixture bytes shared with paired-trial provenance."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _valid_text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return False
    try:
        return len(value.encode("utf-8", "strict")) <= 1024 and not any(
            ord(char) < 32 or ord(char) == 127 for char in value
        )
    except UnicodeError:
        return False


def _validate_ticket_data(rows):
    """Validate the grader fixture, without sharing an application parser/oracle."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise EvalError("invalid-ticket-fixture")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(field), str) or not IDENTIFIER.fullmatch(row[field])
            for field in ("id", "tenantId", "ownerId")
        ):
            raise EvalError("invalid-ticket-fixture")
        priority = row.get("priority")
        if (
            row["id"] in seen
            or not _valid_text(row.get("subject"))
            or type(priority) not in (int, float)
            or not 1 <= priority <= 5
            or priority != int(priority)
            or type(row.get("closed")) is not bool
        ):
            raise EvalError("invalid-ticket-fixture")
        seen.add(row["id"])


def prompt(stack, commit, tasks, condition, *, scenario):
    _validate_selection(scenario, condition)
    if stack not in auth_eval.STACKS:
        raise EvalError("unsupported-guidance-stack")
    old = choice_tasks.prompt(stack, commit, tasks, "documents")
    if scenario == "documents":
        ambiguous = (
            "Viewer may list its tenant collection but may read only its own documents. "
            "Restrict visibility before\nfilters, totals, sort and slicing."
        )
        if old.count(ambiguous) != 1 or old.count(choice_tasks.NEUTRAL_GUIDANCE) != 1:
            raise EvalError("upstream-guidance-task-shape-changed")
        common = old.replace(
            ambiguous,
            "Viewer requires owner read visibility in its tenant for BOTH collection and detail. "
            "Restrict visibility before\nfilters, totals, sort and slicing.",
        ).replace(choice_tasks.NEUTRAL_GUIDANCE, BUILD_GUIDANCE)
    else:
        before, separator, _ = old.partition("Product contract:\n")
        if not separator:
            raise EvalError("upstream-guidance-task-shape-changed")
        common = before + _tickets_body(stack, commit) + BUILD_GUIDANCE
    if condition == "sdk-pointer":
        return common + (
            f"\nOPTIONAL: ../docs/ai-entry/{stack}.md describes available SDK entrypoints.\n"
        )
    return common


def _tickets_body(stack, commit):
    return f"""Product contract:
Serve GET /api/tickets, GET /api/tickets/{{id}}, and GET /api/tickets/summary.
Runtime data is a JSON list from the private file named by TICKETS_DATA_FILE, read on each product request.
Grading creates this file AFTER generation, rewrites it between requests, and uses fresh synthetic rows.
Do not create/cache it or hard-code ticket values. A SHAPE example (not grader data) is
{{"id":"sample","subject":"Sample ticket","priority":2,"closed":false,"tenantId":"sample-tenant","ownerId":"sample-owner"}}.
Return only id/subject/priority/closed; tenantId and ownerId are private.
Data has at most10000 rows with unique IDs. id/tenantId/ownerId match [A-Za-z0-9][A-Za-z0-9._:-]{{0,63}}.
subject is nonempty valid Unicode, <=256 scalars/1024 UTF-8 bytes, no ASCII controls;
priority is an integer numeric value 1..5 (integral JSON numbers allowed, booleans rejected); closed is a JSON boolean.
Validate ALL rows, including inaccessible rows. Missing/unreadable/malformed JSON, non-list data, duplicate IDs,
missing/invalid fields or types => generic503 TICKETS_UNAVAILABLE. Restored data must work on the next request.

Authenticate first with the true session identity, then load CURRENT membership from CORE_MEMBERSHIP_FILE,
then load ticket data. Both private files are created after generation; do not cache their contents.
Membership is {{"subjectId":"demo-user","tenantId":"tenant-a","roles":["viewer"]}}; roles may be [].
Membership provider schema: a JSON object with required subjectId, tenantId and roles fields.
subjectId and tenantId must be strings matching [A-Za-z0-9][A-Za-z0-9._:-]{{0,63}}.
roles must be a JSON array of at most 16 unique strings, each matching [a-z][a-z0-9_-]{{0,63}}; [] is valid.
Missing/unreadable/malformed membership JSON, a non-object value, missing/invalid required fields,
invalid identifier syntax, duplicate roles, more than 16 roles, or {{"unavailable":true}} => generic503 AUTHORIZATION_UNAVAILABLE.
Validate provider JSON before authorization; these structural failures are503,
regardless of any policy API's invalid-principal403.
For structurally valid membership, subjectId different from the true authenticated user's ID
or no granted role (including [] or an ungranted role such as admin) =>403 FORBIDDEN.
Restored membership works on the next request.
Use explicit API-compatible role/permission/scope grants:
viewer tickets:list at tenant scope and viewer tickets:read at owner scope;
dispatcher tickets:list and dispatcher tickets:read at tenant scope.
No other roles grant access. Tenant mismatch always denies. Never trust HTTP role/tenant/subject headers or input.
For BOTH collection and detail, viewer sees only OWN rows in its tenant; dispatcher sees ALL rows in its tenant.
Require tickets:list for collection and summary, and tickets:read visibility BEFORE filters, totals, sorting or slicing.
Missing/inaccessible detail IDs both =>403 FORBIDDEN. No public provider-control endpoints.
Summary has no pagination and returns {{"total":N,"open":N,"closed":N,"priorityTotal":N}} for ALL currently visible rows.
On /api/tickets/summary reject any nonempty query (including pagination/filter/sort) =>400 INVALID_LIST_QUERY.
A bare '?' is equivalent to no query and returns the full summary.

Listing query contract (original raw query before coercion): max2048 UTF-8 bytes and16 pairs;
form-decode once, then reject duplicate/unknown keys, empty pairs, missing '=', malformed escapes,
invalid UTF-8 or ASCII control characters. limit defaults20/range1..100; offset defaults0/range0..10000;
canonical unsigned ASCII decimal only (no signs/whitespace/leading zeros). sort allows id/subject/priority/closed,
optionally '-' descending; default id ascending. Non-ID ties always use ID ascending, even for descending primary order.
Strings sort by Unicode scalar values; booleans false before true. Exact filters: filter.subject is nonempty Unicode
<=256 scalars/1024 bytes; filter.priority canonical signed safe integer (+/-9007199254740991, no plus/leading zero/-0);
filter.closed exactly true/false. No normalization or case folding. Validate before filtering.
Return {{items,total,limit,offset,nextOffset}}; total counts only visible filtered rows; nextOffset is null at the end.
Out-of-range offsets return empty items with unchanged total. Invalid query =>400 INVALID_LIST_QUERY.
Every product response, including errors, requires Cache-Control:no-store and X-Content-Type-Options:nosniff.
Errors use exactly {{"error":{{"code":"FIXED_CODE","message":"Request could not be completed."}}}};
never echo raw queries, provider text, ticket fields or file paths. No SQL/database or product mutations are needed.

Write run.json as {{"build":[{{"argv":["program","argument"],"cwd":"."}}],"start":{{"argv":["program","argument"],"cwd":"."}}}}.
At most8 build commands, argv arrays, cwd within generated/; foreground server only.
Write integration.json exactly {{"stack":"{stack}","profile":"browser-session-v1","source_commit":"{commit}"}}.
Grading builds/starts the app independently. Do not run full repository tests.
"""


def contract_factory(scenario, condition, *, ticket_data=None):
    _validate_selection(scenario, condition)
    contract = core_eval.trial_contract()
    contract.profile = f"guidance-{scenario}-http-v2"

    def build_prompt(stack, commit, tasks, supplied_condition):
        if supplied_condition != condition:
            raise EvalError("guidance-contract-condition-mismatch")
        return prompt(stack, commit, tasks, condition, scenario=scenario)

    contract.prompt_builder = build_prompt
    contract.artifact_checker = discovery.boundary_check
    if scenario == "documents":
        return contract
    rows = copy.deepcopy(
        ticket_fixture("unit-fixture-v2") if ticket_data is None else ticket_data
    )
    _validate_ticket_data(rows)

    def prepare(generated, env):
        core_eval.create_membership_file(generated, env)
        path = generated / (
            ".core-membership-tickets-" + secrets.token_hex(12) + ".json"
        )
        auth_eval.no_symlink(path)
        with auth_eval.private_file(path) as stream:
            stream.write(ticket_fixture_bytes(rows))
        env["TICKETS_DATA_FILE"] = str(path)

    contract.prepare_grader = prepare
    contract.http_grader = lambda generated, env, port, origin, deadline: (
        tickets_http_grade(
            port,
            origin,
            deadline,
            Path(env["CORE_MEMBERSHIP_FILE"]),
            Path(env["TICKETS_DATA_FILE"]),
            rows,
        )
    )
    return contract


def _public(row):
    return {field: row[field] for field in PUBLIC_FIELDS}


def _expected_page(
    rows, *, sort="id", descending=False, filters=(), limit=20, offset=0
):
    # A simple expected-result oracle for explicit valid test cases, not a parser
    # or a call into the SDK being evaluated.
    selected = [row for row in rows if all(row[key] == value for key, value in filters)]
    selected = sorted(selected, key=lambda row: row["id"])
    selected.sort(key=lambda row: row[sort], reverse=descending)
    total = len(selected)
    end = offset + limit
    return {
        "items": [_public(row) for row in selected[offset:end]],
        "total": total,
        "limit": limit,
        "offset": offset,
        "nextOffset": end if end < total else None,
    }


def _expected_summary(rows):
    return {
        "total": len(rows),
        "open": sum(not row["closed"] for row in rows),
        "closed": sum(row["closed"] for row in rows),
        "priorityTotal": sum(row["priority"] for row in rows),
    }


def _typed_equal(actual, expected):
    """Keep JSON boolean/string/number distinctions; accept integral 1.0 as 1."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_typed_equal(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_typed_equal(left, right) for left, right in zip(actual, expected))
        )
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


def tickets_http_grade(
    port,
    origin,
    deadline,
    membership_file,
    tickets_file,
    ticket_data,
    *,
    requester=None,
):
    """Independent real HTTP checks with request-local injection and private state."""
    from contextlib import contextmanager

    request = auth_eval.request if requester is None else requester
    checks = auth_eval.http_grade(port, origin, deadline)
    rows = copy.deepcopy(ticket_data)
    _validate_ticket_data(rows)
    own = sorted(
        (
            row
            for row in rows
            if row["tenantId"] == "tenant-a" and row["ownerId"] == "demo-user"
        ),
        key=lambda row: row["id"],
    )
    tenant = [row for row in rows if row["tenantId"] == "tenant-a"]
    other_owner = [row for row in tenant if row["ownerId"] != "demo-user"]
    other_tenant = [row for row in rows if row["tenantId"] != "tenant-a"]
    if len(own) < 2 or not other_owner or not other_tenant:
        raise EvalError("ticket-fixture-missing-scope-controls")
    detail = "/api/tickets/" + own[0]["id"]
    paths = ("/api/tickets", detail, "/api/tickets/summary")

    def expect(name, actual, wanted):
        if actual != wanted:
            raise EvalError(name)
        checks.append(name)

    def get(path, *, cookie=None, headers=None):
        return request(
            port, "GET", path, origin, deadline, cookie=cookie, extra_headers=headers
        )

    def response(name, actual, status, body):
        actual_status, headers, actual_body = actual
        expect(name + "-status", actual_status, status)
        expect(name + "-body", _typed_equal(actual_body, body), True)
        headers = {key.lower(): value for key, value in headers.items()}
        expect(name + "-no-store", headers.get("cache-control"), "no-store")
        expect(name + "-nosniff", headers.get("x-content-type-options"), "nosniff")

    def failure(name, actual, status, code):
        response(
            name,
            actual,
            status,
            {"error": {"code": code, "message": "Request could not be completed."}},
        )

    def replace(path, value, *, raw=False):
        if path == tickets_file and not raw:
            value = ticket_fixture_bytes(value).decode("utf-8")
            raw = True
        core_eval.update_membership(path, value, raw=raw)

    @contextmanager
    def missing(path):
        held = path.with_name(path.name + ".held")
        auth_eval.no_symlink(path)
        auth_eval.no_symlink(held)
        if held.exists():
            raise EvalError("unsafe-ticket-fixture-backup")
        path.rename(held)
        try:
            yield
        finally:
            held.rename(path)

    # No provider file is available: authentication must still win on every route.
    with missing(membership_file), missing(tickets_file):
        for path in paths:
            failure("tickets-anonymous", get(path), 401, "UNAUTHENTICATED")
            failure(
                "tickets-forged-session",
                get(path, cookie="fs_session=" + "z" * 43),
                401,
                "UNAUTHENTICATED",
            )
    status, headers, session = request(
        port,
        "POST",
        "/auth/login",
        origin,
        deadline,
        body={"email": "demo@example.com", "password": "correct-horse-battery-staple"},
    )
    expect("tickets-login-status", status, 200)
    cookie = next(
        (value for key, value in headers.items() if key.lower() == "set-cookie"), ""
    ).split(";", 1)[0]
    expect(
        "tickets-login-cookie",
        bool(re.fullmatch(r"fs_session=[A-Za-z0-9_-]{43}", cookie)),
        True,
    )
    csrf = session.get("csrfToken") if isinstance(session, dict) else None
    expect("tickets-login-csrf", isinstance(csrf, str) and len(csrf) == 43, True)
    try:
        # The membership provider must run before the product-data provider.
        with missing(tickets_file):
            replace(membership_file, {"unavailable": True})
            for path in paths:
                failure(
                    "tickets-membership-before-data",
                    get(path, cookie=cookie),
                    503,
                    "AUTHORIZATION_UNAVAILABLE",
                )
        replace(membership_file, core_eval.VIEWER)
        response(
            "tickets-viewer-list",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(own),
        )
        response(
            "tickets-viewer-detail", get(detail, cookie=cookie), 200, _public(own[0])
        )
        response(
            "tickets-viewer-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(own),
        )
        for field in PUBLIC_FIELDS:
            for descending in (False, True):
                sort = ("-" if descending else "") + field
                response(
                    "tickets-viewer-sort",
                    get("/api/tickets?sort=" + sort, cookie=cookie),
                    200,
                    _expected_page(own, sort=field, descending=descending),
                )
        for query, kwargs in (
            (
                "sort=-priority&limit=1",
                {"sort": "priority", "descending": True, "limit": 1},
            ),
            (
                "sort=-priority&limit=1&offset=1",
                {"sort": "priority", "descending": True, "limit": 1, "offset": 1},
            ),
            ("offset=10000", {"offset": 10000}),
            ("limit=100&offset=0", {"limit": 100}),
            ("filter.closed=true", {"filters": (("closed", True),)}),
            (
                "filter.closed=false&filter.priority=2",
                {"filters": (("closed", False), ("priority", 2))},
            ),
            (
                urlencode({"filter.subject": own[0]["subject"]}),
                {"filters": (("subject", own[0]["subject"]),)},
            ),
            ("filter.priority=-1", {"filters": (("priority", -1),)}),
            ("filter.priority=0", {"filters": (("priority", 0),)}),
            (
                "filter.priority=9007199254740991",
                {"filters": (("priority", 9007199254740991),)},
            ),
        ):
            response(
                "tickets-viewer-page",
                get("/api/tickets?" + query, cookie=cookie),
                200,
                _expected_page(own, **kwargs),
            )
        response(
            "tickets-summary-not-paginated",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(own),
        )
        for row in (other_owner[0], other_tenant[0]):
            failure(
                "tickets-hidden-id",
                get("/api/tickets/" + row["id"], cookie=cookie),
                403,
                "FORBIDDEN",
            )
            response(
                "tickets-hidden-filter",
                get(
                    "/api/tickets?filter.subject=" + quote(row["subject"], safe=""),
                    cookie=cookie,
                ),
                200,
                _expected_page(own, filters=(("subject", row["subject"]),)),
            )
        failure(
            "tickets-missing-id",
            get("/api/tickets/missing-ticket-control", cookie=cookie),
            403,
            "FORBIDDEN",
        )
        for query in (
            "limit=01",
            "limit=0",
            "limit=101",
            "limit=-1",
            "limit=%2B1",
            "limit=1.0",
            "limit=",
            "offset=01",
            "offset=10001",
            "offset=-1",
            "offset=%201",
            "limit=1&%6cimit=2",
            "sort=unknown",
            "sort=id,priority",
            "sort=",
            "filter.closed=1",
            "filter.closed=True",
            "filter.priority=02",
            "filter.priority=-0",
            "filter.priority=%2B2",
            "filter.priority=9007199254740992",
            "filter.subject=",
            "filter.subject=%FF",
            "filter.subject=%00",
            "filter.subject=%7F",
            "filter.subject=%",
            "filter.subject=%GG",
            "filter.subject=" + "x" * 257,
            "filter.subject=" + "x" * 2049,
            "filter.id=private-provider-detail",
            "filter.tenantId=tenant-a",
            "unknown=private-provider-detail",
            "limit=1&&offset=0",
            "limit",
            "=1",
            "limit=1&",
            "filter.subject=A&%66ilter.subject=B",
            "&".join("limit=1" for _ in range(17)),
        ):
            failure(
                "tickets-invalid-query",
                get("/api/tickets?" + query, cookie=cookie),
                400,
                "INVALID_LIST_QUERY",
            )
        response(
            "tickets-summary-empty-query",
            get(paths[2] + "?", cookie=cookie),
            200,
            _expected_summary(own),
        )
        for query in (
            "limit=1",
            "offset=1",
            "filter.closed=true",
            "sort=-priority",
            "unknown=private-provider-detail",
        ):
            failure(
                "tickets-summary-query",
                get(paths[2] + "?" + query, cookie=cookie),
                400,
                "INVALID_LIST_QUERY",
            )
        replace(membership_file, {**core_eval.VIEWER, "roles": []})
        for path in paths:
            failure("tickets-revoked", get(path, cookie=cookie), 403, "FORBIDDEN")
        forged = {
            "X-Role": "dispatcher",
            "X-Roles": "viewer,dispatcher",
            "X-Tenant-Id": "tenant-b",
            "X-Subject-Id": "other-user",
        }
        for path in paths:
            failure(
                "tickets-forged-role",
                get(path, cookie=cookie, headers=forged),
                403,
                "FORBIDDEN",
            )
        for membership in (
            {**core_eval.VIEWER, "roles": ["admin"]},
            {**core_eval.VIEWER, "subjectId": "other-user"},
        ):
            replace(membership_file, membership)
            for path in paths:
                failure(
                    "tickets-membership-denied",
                    get(path, cookie=cookie),
                    403,
                    "FORBIDDEN",
                )
        for membership, raw in (
            ({**core_eval.VIEWER, "unavailable": True}, False),
            ("private-provider-detail", True),
            ({**core_eval.VIEWER, "roles": "viewer"}, False),
            ({**core_eval.VIEWER, "roles": ["viewer", "viewer"]}, False),
        ):
            replace(membership_file, membership, raw=raw)
            for path in paths:
                failure(
                    "tickets-membership-unavailable",
                    get(path, cookie=cookie),
                    503,
                    "AUTHORIZATION_UNAVAILABLE",
                )
        with missing(membership_file):
            for path in paths:
                failure(
                    "tickets-membership-unavailable",
                    get(path, cookie=cookie),
                    503,
                    "AUTHORIZATION_UNAVAILABLE",
                )
        replace(membership_file, core_eval.VIEWER)
        response(
            "tickets-membership-recovered",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(own),
        )
        replace(membership_file, {**core_eval.VIEWER, "roles": ["dispatcher"]})
        response(
            "tickets-dispatcher-list",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(tenant),
        )
        response(
            "tickets-dispatcher-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(tenant),
        )
        response(
            "tickets-dispatcher-detail",
            get("/api/tickets/" + other_owner[0]["id"], cookie=cookie),
            200,
            _public(other_owner[0]),
        )
        response(
            "tickets-dispatcher-page",
            get("/api/tickets?sort=-priority&limit=2&offset=1", cookie=cookie),
            200,
            _expected_page(tenant, sort="priority", descending=True, limit=2, offset=1),
        )
        response(
            "tickets-dispatcher-filter",
            get("/api/tickets?filter.closed=true", cookie=cookie),
            200,
            _expected_page(tenant, filters=(("closed", True),)),
        )
        failure(
            "tickets-dispatcher-other-tenant",
            get("/api/tickets/" + other_tenant[0]["id"], cookie=cookie),
            403,
            "FORBIDDEN",
        )
        failure(
            "tickets-dispatcher-missing",
            get("/api/tickets/missing-ticket-control", cookie=cookie),
            403,
            "FORBIDDEN",
        )
        # A live membership tenant change must also affect listing and full summary.
        new_tenant = other_tenant[0]["tenantId"]
        changed = [row for row in rows if row["tenantId"] == new_tenant]
        replace(
            membership_file,
            {**core_eval.VIEWER, "tenantId": new_tenant, "roles": ["dispatcher"]},
        )
        response(
            "tickets-tenant-changed-list",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(changed),
        )
        response(
            "tickets-tenant-changed-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(changed),
        )
        failure(
            "tickets-prior-tenant-denied", get(detail, cookie=cookie), 403, "FORBIDDEN"
        )
        replace(membership_file, core_eval.VIEWER)
        # Corrupt an inaccessible row too: validate the entire trusted data file.
        corruptions = []
        for field, value in (
            ("priority", True),
            ("priority", 6),
            ("priority", 2.5),
            ("subject", 7),
            ("subject", "bad\x00private-provider-detail"),
            ("closed", 0),
            ("ownerId", None),
            ("id", "bad/id"),
        ):
            corrupt = copy.deepcopy(rows)
            corrupt[rows.index(other_tenant[0])][field] = value
            corruptions.append((corrupt, False))
        corruptions.extend(
            (
                ("private-provider-detail", True),
                ({"tickets": rows}, False),
                (rows + [rows[0]], False),
            )
        )
        with missing(tickets_file):
            for path in paths:
                failure(
                    "tickets-data-unavailable",
                    get(path, cookie=cookie),
                    503,
                    "TICKETS_UNAVAILABLE",
                )
        response(
            "tickets-data-recovered",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(own),
        )
        for value, raw in corruptions:
            replace(tickets_file, value, raw=raw)
            for path in paths:
                failure(
                    "tickets-data-unavailable",
                    get(path, cookie=cookie),
                    503,
                    "TICKETS_UNAVAILABLE",
                )
            replace(tickets_file, rows)
            response(
                "tickets-data-recovered",
                get(paths[0], cookie=cookie),
                200,
                _expected_page(own),
            )
        # A valid changed file must be visible immediately, without process restart.
        updated = copy.deepcopy(rows)
        index = next(
            index for index, row in enumerate(updated) if row["id"] == own[0]["id"]
        )
        updated[index]["closed"] = not updated[index]["closed"]
        updated[index]["priority"] = 1.0 if updated[index]["priority"] == 5 else 5.0
        replace(tickets_file, updated)
        updated_own = [
            row
            for row in updated
            if row["tenantId"] == "tenant-a" and row["ownerId"] == "demo-user"
        ]
        response(
            "tickets-data-updated-list",
            get(paths[0], cookie=cookie),
            200,
            _expected_page(updated_own),
        )
        response(
            "tickets-data-updated-detail",
            get(detail, cookie=cookie),
            200,
            _public(updated[index]),
        )
        response(
            "tickets-data-updated-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(updated_own),
        )
        replace(tickets_file, [])
        response(
            "tickets-empty-list", get(paths[0], cookie=cookie), 200, _expected_page([])
        )
        response(
            "tickets-empty-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary([]),
        )
        failure("tickets-empty-detail", get(detail, cookie=cookie), 403, "FORBIDDEN")
        replace(tickets_file, rows)
        response(
            "tickets-restored-summary",
            get(paths[2], cookie=cookie),
            200,
            _expected_summary(own),
        )
        expect(
            "tickets-logout-status",
            request(
                port, "POST", "/auth/logout", origin, deadline, cookie=cookie, csrf=csrf
            )[0],
            204,
        )
        for path in paths:
            failure(
                "tickets-old-cookie", get(path, cookie=cookie), 401, "UNAUTHENTICATED"
            )
    finally:
        replace(membership_file, core_eval.VIEWER)
        replace(tickets_file, rows)
    if len(checks) != expected_assertions("tickets"):
        raise EvalError("tickets-assertion-count-mismatch")
    return checks
