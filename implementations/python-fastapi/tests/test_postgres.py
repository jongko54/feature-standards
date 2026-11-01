"""Opt-in real PostgreSQL tests; use a disposable feature_standards_test* DB."""

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from feature_auth import AuthError, Settings, create_app, current_user
from feature_auth.core import DEMO_PASSWORD
from feature_auth.postgres import PostgresStore, token_hash, valid_phc

ORIGIN = "http://127.0.0.1:5173"
DEMO = {"email": "demo@example.com", "password": DEMO_PASSWORD}
OTHER = {"email": "other@example.com", "password": "other-correct-horse-password"}


def safe_test_database_url(raw, environ):
    """Test-only allowlist; never pass an unchecked DSN to destructive fixtures."""
    error = "PostgreSQL tests require a disposable loopback URL without routing overrides"
    if any(name.startswith("PG") and value for name, value in environ.items()):
        raise ValueError(error)
    parsed = urlsplit(raw)
    port = parsed.port if parsed.port is not None else 5432
    database = unquote(parsed.path.removeprefix("/"))
    if (
        parsed.scheme not in ("postgresql", "postgres")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or not re.fullmatch(r"feature_standards_test[A-Za-z0-9_]*", database)
        or not 1 <= port <= 65535
        or parsed.fragment
        or parsed.netloc.count("@") > 1
        or parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        not in ([], [("sslmode", "disable")])
    ):
        raise ValueError(error)
    # Pin localhost to a numeric loopback address and write every routing field.
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    userinfo = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    return urlunsplit(
        (parsed.scheme, f"{userinfo}{host}:{port}", "/" + database, "sslmode=disable", "")
    )


@pytest.mark.parametrize(
    "query",
    [
        "host=production.example&dbname=production",
        "hostaddr=203.0.113.10",
        "dbname=production",
        "service=production",
        "%68ost=production.example",
        "sslmode=disable&host=production.example",
        "sslmode=disable&sslmode=prefer",
    ],
)
def test_test_database_guard_rejects_query_routing_overrides(query):
    with pytest.raises(ValueError):
        safe_test_database_url("postgresql://127.0.0.1/feature_standards_test?" + query, {})


@pytest.mark.parametrize(
    "name", ["PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE"]
)
def test_test_database_guard_rejects_libpq_routing_environment(name):
    with pytest.raises(ValueError):
        safe_test_database_url(
            "postgresql://127.0.0.1/feature_standards_test", {name: "production"}
        )


@pytest.mark.parametrize(
    "raw,host,port,database",
    [
        (
            "postgresql://tester@localhost/feature_standards_test",
            "127.0.0.1",
            "5432",
            "feature_standards_test",
        ),
        (
            "postgresql://tester@127.0.0.1:51105/feature_standards_test_pygo?sslmode=disable",
            "127.0.0.1",
            "51105",
            "feature_standards_test_pygo",
        ),
        (
            "postgres://tester@[::1]:51105/feature_standards_test_ipv6",
            "::1",
            "51105",
            "feature_standards_test_ipv6",
        ),
    ],
)
def test_test_database_guard_pins_driver_routing(raw, host, port, database):
    parsed = psycopg.conninfo.conninfo_to_dict(safe_test_database_url(raw, {}))
    assert parsed["host"] == host
    assert parsed["port"] == port
    assert parsed["dbname"] == database
    assert parsed["sslmode"] == "disable"
    assert not ({"hostaddr", "service"} & parsed.keys())


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://production.example/feature_standards_test",
        "postgresql://127.0.0.1/production",
        "postgresql://127.0.0.1/feature_standards_test%2Fproduction",
        "postgresql://127.0.0.1:0/feature_standards_test",
        "postgresql://127.0.0.1/feature_standards_test#host=production.example",
    ],
)
def test_test_database_guard_rejects_unsafe_surface(raw):
    with pytest.raises(ValueError):
        safe_test_database_url(raw, {})


@pytest.fixture
def pg_settings():
    url = os.environ.get("AUTH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AUTH_TEST_DATABASE_URL is not set")
    try:
        url = safe_test_database_url(url, os.environ)
    except ValueError as error:
        pytest.fail(str(error))
    with psycopg.connect(url) as conn:
        conn.execute("TRUNCATE feature_auth.sessions, feature_auth.login_attempts")
    return Settings(True, "", "", secure_cookie=False, store="postgres", database_url=url)


def test_phc_rejects_unsupported_and_noncanonical_hashes():
    assert not valid_phc("$argon2id$v=19$m=8,t=1,p=1$AAAA$AAAA")
    assert not valid_phc("$argon2i$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "A" * 43)
    assert valid_phc("$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "A" * 43)
    assert not valid_phc("$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 21 + "B$" + "A" * 43)


def test_startup_failure_redacts_credentials():
    settings = Settings(
        True,
        "",
        "",
        store="postgres",
        database_url="postgresql://owner:never-print-this@127.0.0.1:1/feature_standards_test?sslmode=disable",
    )
    with pytest.raises(ValueError) as caught:
        PostgresStore(settings)
    assert "never-print-this" not in str(caught.value)
    assert "postgresql://" not in str(caught.value)


def test_settings_database_mode_ignores_memory_credentials(monkeypatch):
    monkeypatch.setenv("AUTH_STORE", "postgres")
    monkeypatch.setenv("AUTH_DATABASE_URL", "postgresql://127.0.0.1/feature_standards_test")
    monkeypatch.setenv("AUTH_DEMO", "false")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGIN", "https://app.example.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.delenv("AUTH_USER_EMAIL", raising=False)
    monkeypatch.delenv("AUTH_USER_PASSWORD", raising=False)
    settings = Settings.from_env()
    assert settings.email == settings.password == ""


def test_shared_rotation_and_two_users(pg_settings):
    one, two = PostgresStore(pg_settings), PostgresStore(pg_settings)
    token, value = one.authenticate("127.0.0.1", **DEMO, old_token="")
    assert two.get_session(token) == value
    other_token, other = two.authenticate("127.0.0.1", **OTHER, old_token="")
    assert other.user == {"id": "other-user", "email": OTHER["email"]}
    rotated, _ = two.authenticate("127.0.0.1", **DEMO, old_token=token)
    assert one.get_session(token) is None
    assert one.get_session(other_token) == other
    with psycopg.connect(pg_settings.database_url) as conn:
        hashes = [
            bytes(row[0]) for row in conn.execute("SELECT token_hash FROM feature_auth.sessions")
        ]
    assert token_hash(rotated) in hashes
    assert all(len(digest) == 32 for digest in hashes)
    with pytest.raises(AuthError) as caught:
        one.logout(rotated, "wrong")
    assert caught.value.code == "CSRF_INVALID"
    session = one.get_session(rotated)
    two.logout(rotated, session.csrf)
    assert one.get_session(rotated) is None
    assert one.get_session(other_token) is not None


def test_shared_atomic_failures_and_canonical_peer(pg_settings):
    settings = replace(pg_settings, rate_limit_max=2)
    stores = [PostgresStore(settings), PostgresStore(settings)]

    def fail(index):
        try:
            stores[index % 2].authenticate(
                "0:0:0:0:0:0:0:1" if index % 2 else "::1", DEMO["email"], "wrong", ""
            )
        except AuthError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(fail, range(8)))
    assert statuses.count(401) == 2
    assert statuses.count(429) == 6
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT host(peer), failures FROM feature_auth.login_attempts"
        ).fetchall()
    assert rows == [("::1", 2)]


def test_db_time_expiry_and_disabled_user(pg_settings):
    store = PostgresStore(pg_settings)
    token, value = store.authenticate("127.0.0.1", **DEMO, old_token="")
    with psycopg.connect(pg_settings.database_url) as conn:
        conn.execute(
            "UPDATE feature_auth.sessions "
            "SET created_at=clock_timestamp()-interval '2 seconds',"
            "expires_at=clock_timestamp()-interval '1 second' WHERE token_hash=%s",
            (token_hash(token),),
        )
    assert store.get_session(token) is None
    store.logout(token, "")
    token, _ = store.authenticate("127.0.0.1", **DEMO, old_token="")
    try:
        with psycopg.connect(pg_settings.database_url) as conn:
            conn.execute("UPDATE feature_auth.users SET enabled=false WHERE id='demo-user'")
        assert store.get_session(token) is None
        with pytest.raises(AuthError) as caught:
            store.authenticate("127.0.0.1", **DEMO, old_token="")
        assert caught.value.code == "INVALID_CREDENTIALS"
    finally:
        with psycopg.connect(pg_settings.database_url) as conn:
            conn.execute("UPDATE feature_auth.users SET enabled=true WHERE id='demo-user'")


def test_runtime_database_failure_and_dependency_fail_closed(pg_settings):
    store = PostgresStore(pg_settings)
    app = create_app(settings=pg_settings, store=store)

    @app.get("/protected")
    def protected(user: dict = Depends(current_user)):  # noqa: B008
        return user

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post("/auth/login", json=DEMO, headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert client.get("/healthz").json()["profile"] == "browser-session-v2"
        assert client.get("/protected").json() == response.json()["user"]
        store._url = "postgresql://127.0.0.1:1/feature_standards_test?sslmode=disable"
        for method, path, kwargs in (
            ("GET", "/auth/me", {}),
            ("GET", "/protected", {}),
            ("GET", "/healthz", {}),
            ("POST", "/auth/login", {"json": DEMO}),
            ("POST", "/auth/logout", {}),
        ):
            response = client.request(method, path, headers={"Origin": ORIGIN}, **kwargs)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "set-cookie" not in response.headers


def test_corrupt_phc_is_503_and_does_not_revoke_previous_session(pg_settings):
    store = PostgresStore(pg_settings)
    token, _ = store.authenticate("127.0.0.1", **DEMO, old_token="")
    with psycopg.connect(pg_settings.database_url) as conn:
        encoded = conn.execute(
            "SELECT password_hash FROM feature_auth.users WHERE id='demo-user'"
        ).fetchone()[0]
        conn.execute("UPDATE feature_auth.users SET password_hash='corrupt' WHERE id='demo-user'")
    try:
        with pytest.raises(AuthError) as caught:
            store.authenticate("127.0.0.1", **DEMO, old_token=token)
        assert caught.value.code == "STORAGE_UNAVAILABLE"
        assert store.get_session(token) is not None
    finally:
        with psycopg.connect(pg_settings.database_url) as conn:
            conn.execute(
                "UPDATE feature_auth.users SET password_hash=%s WHERE id='demo-user'", (encoded,)
            )


def test_schema_mismatch_fails_before_startup(pg_settings):
    with psycopg.connect(pg_settings.database_url) as conn:
        conn.execute("DELETE FROM feature_auth.schema_version")
    try:
        with pytest.raises(ValueError, match="unavailable or incompatible"):
            with TestClient(create_app(settings=pg_settings)):
                pytest.fail("app started without schema version 1")
    finally:
        with psycopg.connect(pg_settings.database_url) as conn:
            conn.execute("INSERT INTO feature_auth.schema_version(version) VALUES (1)")


def test_commit_failure_does_not_issue_cookie_or_revoke_old_session(pg_settings):
    app = create_app(settings=pg_settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        first = client.post("/auth/login", json=DEMO, headers={"Origin": ORIGIN})
        assert first.status_code == 200
        old_token = client.cookies.get("fs_session")
        with psycopg.connect(pg_settings.database_url) as conn:
            conn.execute("""CREATE FUNCTION feature_auth.reject_python_test_commit()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'test deferred failure'; END $$""")
            conn.execute("""CREATE CONSTRAINT TRIGGER reject_python_test_commit
                AFTER INSERT OR DELETE ON feature_auth.sessions
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION feature_auth.reject_python_test_commit()""")
        try:
            for path, kwargs in (("/auth/login", {"json": DEMO}), ("/auth/logout", {})):
                response = client.post(
                    path,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrfToken"]},
                    **kwargs,
                )
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
                assert "set-cookie" not in response.headers
                assert client.cookies.get("fs_session") == old_token
                assert client.get("/auth/me").json() == first.json()
        finally:
            with psycopg.connect(pg_settings.database_url) as conn:
                conn.execute("DROP TRIGGER reject_python_test_commit ON feature_auth.sessions")
                conn.execute("DROP FUNCTION feature_auth.reject_python_test_commit()")
