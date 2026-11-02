"""Opt-in account adapter checks on a disposable schema-2 database only."""

import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_postgres import safe_test_database_url

from feature_auth import AuthError, Settings, create_app
from feature_auth.postgres import PostgresStore, token_hash, valid_phc

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "replacement-password-is-long"
ORIGIN = "http://127.0.0.1:5173"


@pytest.fixture
def account_pg_settings():
    raw = os.environ.get("AUTH_ACCOUNT_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AUTH_ACCOUNT_TEST_DATABASE_URL is not set")
    url = safe_test_database_url(raw, os.environ)
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT version FROM feature_auth.schema_version").fetchall() == [(2,)]
        conn.execute("DELETE FROM feature_auth.users WHERE id NOT IN ('demo-user','other-user')")
        conn.execute(
            "TRUNCATE feature_auth.sessions,feature_auth.login_attempts,"
            "feature_auth.account_tokens,feature_auth.account_attempts,"
            "feature_auth.account_mail_limits,feature_auth.mail_outbox"
        )
    return Settings(
        True,
        "",
        "",
        secure_cookie=False,
        store="postgres",
        database_url=url,
        account_lifecycle=True,
    )


def query(settings, sql, params=()):
    with psycopg.connect(settings.database_url) as conn:
        return conn.execute(sql, params).fetchall()


def register_verified(settings, store, email="python-account@example.com"):
    store.account("register", "127.0.0.1", email, "", PASSWORD)
    token = query(
        settings, "SELECT token FROM feature_auth.mail_outbox WHERE recipient=%s", (email,)
    )[0][0]
    store.account("verify-confirm", "127.0.0.1", "", token, "")
    return email


def test_account_real_gateway_schema_gate_and_password_reset(account_pg_settings):
    settings = account_pg_settings
    store = PostgresStore(settings)
    with pytest.raises(ValueError, match="unavailable or incompatible"):
        PostgresStore(replace(settings, account_lifecycle=False))
    email = "한@python.example.com"
    store.account("register", "127.0.0.1", email, "", PASSWORD)
    row = query(
        settings,
        "SELECT id,password_hash,enabled,admin_enabled FROM feature_auth.users WHERE email=%s",
        (email,),
    )[0]
    assert not row[2] and row[3] and valid_phc(row[1])
    with pytest.raises(AuthError) as error:
        store.authenticate("127.0.0.1", email, PASSWORD, "")
    assert error.value.status == 401
    token = query(
        settings, "SELECT token FROM feature_auth.mail_outbox WHERE recipient=%s", (email,)
    )[0][0]
    assert len(token) == 43
    assert query(settings, "SELECT token_hash FROM feature_auth.account_tokens") == [
        (token_hash(token),)
    ]
    store.account("verify-confirm", "127.0.0.1", "", token, "")
    with pytest.raises(AuthError) as error:
        store.account("verify-confirm", "127.0.0.1", "", token, "")
    assert (error.value.status, error.value.code) == (400, "INVALID_TOKEN")
    one, _ = store.authenticate("127.0.0.1", email, PASSWORD, "")
    two, _ = store.authenticate("127.0.0.1", email, PASSWORD, "")
    store.account("reset-request", "127.0.0.1", email, "", "")
    reset = query(
        settings,
        "SELECT token FROM feature_auth.mail_outbox WHERE recipient=%s AND kind='reset'",
        (email,),
    )[0][0]
    store.account("reset-confirm", "127.0.0.1", "", reset, NEW_PASSWORD)
    assert store.get_session(one) is None and store.get_session(two) is None
    assert store.authenticate("127.0.0.1", email, NEW_PASSWORD, "")[1].user["email"] == email
    with pytest.raises(AuthError) as error:
        store.authenticate("127.0.0.1", email, PASSWORD, "")
    assert error.value.code == "INVALID_CREDENTIALS"


def test_account_semantic_errors_commit_rate_counter(account_pg_settings):
    store = PostgresStore(account_pg_settings)
    for _ in range(10):
        with pytest.raises(AuthError) as error:
            store.account("verify-confirm", "127.0.0.1", "", secrets.token_urlsafe(32), "")
        assert error.value.code == "INVALID_TOKEN"
    with pytest.raises(AuthError) as error:
        store.account("verify-confirm", "127.0.0.1", "", secrets.token_urlsafe(32), "")
    assert error.value.status == 429
    assert int(error.value.headers["Retry-After"]) > 0


def test_exhausted_account_rate_gate_does_not_hash_password(account_pg_settings):
    settings = account_pg_settings
    store = PostgresStore(settings)
    calls = []

    class CountingHasher:
        def hash(self, password):
            calls.append(password)
            return "not-used-because-the-peer-is-limited"

    store.hasher = CountingHasher()
    for action in ("register", "reset-confirm"):
        query(
            settings,
            "INSERT INTO feature_auth.account_attempts(peer,action,hits,expires_at) "
            "VALUES ('127.0.0.1',%s,10,clock_timestamp()+interval '60 seconds') RETURNING hits",
            (action,),
        )
        with pytest.raises(AuthError) as error:
            store.account(action, "127.0.0.1", "limited@example.com", "A" * 43, PASSWORD)
        assert error.value.status == 429
        assert query(
            settings, "SELECT hits FROM feature_auth.account_attempts WHERE action=%s", (action,)
        ) == [(10,)]
    assert calls == [], "rate-limited account requests must not execute Argon2"


def test_account_deferred_commit_failure_has_no_http_success(account_pg_settings):
    settings = account_pg_settings
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("""CREATE FUNCTION feature_auth.reject_python_account_commit()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'deferred test failure'; END $$""")
        conn.execute("""CREATE CONSTRAINT TRIGGER reject_python_account_commit
            AFTER INSERT ON feature_auth.mail_outbox DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION feature_auth.reject_python_account_commit()""")
    try:
        with TestClient(create_app(settings=settings), client=("127.0.0.1", 54321)) as client:
            response = client.post(
                "/auth/register",
                json={"email": "rollback@example.com", "password": PASSWORD},
                headers={"Origin": ORIGIN},
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
            assert "set-cookie" not in response.headers
        assert query(
            settings, "SELECT count(*) FROM feature_auth.users WHERE email='rollback@example.com'"
        ) == [(0,)]
        assert query(settings, "SELECT count(*) FROM feature_auth.mail_outbox") == [(0,)]
    finally:
        with psycopg.connect(settings.database_url) as conn:
            conn.execute("DROP TRIGGER reject_python_account_commit ON feature_auth.mail_outbox")
            conn.execute("DROP FUNCTION feature_auth.reject_python_account_commit()")


def test_password_reset_serializes_inflight_old_password_login(account_pg_settings):
    settings = account_pg_settings
    store, reset_store = PostgresStore(settings), PostgresStore(settings)
    email = register_verified(settings, store)
    store.account("reset-request", "127.0.0.1", email, "", "")
    token = query(settings, "SELECT token FROM feature_auth.mail_outbox WHERE kind='reset'")[0][0]
    verifying, release = threading.Event(), threading.Event()
    original = store.hasher

    class PausedHasher:
        def verify(self, encoded, password):
            verifying.set()
            assert release.wait(5)
            return original.verify(encoded, password)

    store.hasher = PausedHasher()
    with ThreadPoolExecutor(max_workers=2) as executor:
        login = executor.submit(store.authenticate, "127.0.0.1", email, PASSWORD, "")
        assert verifying.wait(3)
        resetting = executor.submit(
            reset_store.account, "reset-confirm", "127.0.0.1", "", token, NEW_PASSWORD
        )
        blocked = False
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not resetting.done():
                blocked = (
                    query(
                        settings,
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND wait_event_type='Lock' AND query LIKE %s",
                        ("SELECT feature_auth.account_apply%",),
                    )[0][0]
                    > 0
                )
                if blocked:
                    break
                time.sleep(0.02)
            assert blocked, "reset did not wait for the in-flight login user lock"
        finally:
            release.set()
        old_session = login.result(timeout=4)[0]
        resetting.result(timeout=4)
    assert reset_store.get_session(old_session) is None
    assert reset_store.authenticate("127.0.0.1", email, NEW_PASSWORD, "")[1].user["email"] == email
