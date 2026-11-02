import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from feature_auth import AuthError, Settings, create_app

ORIGIN = "http://127.0.0.1:5173"
PASSWORD = "correct-horse-battery-staple"
TOKEN = "A" * 43
ROUTES = {
    "/auth/register": ("register", {"email": "  한@EXAMPLE.COM  ", "password": PASSWORD}),
    "/auth/email-verification/request": ("verify-request", {"email": "한@example.com"}),
    "/auth/email-verification/confirm": ("verify-confirm", {"token": TOKEN}),
    "/auth/password-reset/request": ("reset-request", {"email": "한@example.com"}),
    "/auth/password-reset/confirm": ("reset-confirm", {"token": TOKEN, "password": PASSWORD}),
}


class AccountStore:
    def __init__(self):
        self.calls = []
        self.failure = None

    def health(self):
        pass

    def close(self):
        pass

    def account(self, action, peer, email, token, password):
        self.calls.append((action, peer, email, token, password))
        if self.failure:
            raise self.failure


@pytest.fixture
def account_client():
    settings = Settings(True, "", "", secure_cookie=False, store="postgres", account_lifecycle=True)
    store = AccountStore()
    with TestClient(
        create_app(settings=settings, store=store), client=("127.0.0.1", 12345)
    ) as client:
        yield client, store


def test_lifecycle_config_requires_postgres_and_strict_boolean(monkeypatch):
    monkeypatch.setenv("AUTH_DEMO", "true")
    monkeypatch.setenv("AUTH_ACCOUNT_LIFECYCLE", "true")
    monkeypatch.setenv("AUTH_STORE", "memory")
    with pytest.raises(ValueError, match="postgres"):
        Settings.from_env()
    monkeypatch.setenv("AUTH_STORE", "postgres")
    monkeypatch.setenv("AUTH_DATABASE_URL", "postgresql://127.0.0.1/test")
    assert Settings.from_env().account_lifecycle
    for invalid in ("TRUE", ""):
        monkeypatch.setenv("AUTH_ACCOUNT_LIFECYCLE", invalid)
        with pytest.raises(ValueError, match="true or false"):
            Settings.from_env()


def test_all_account_routes_are_gated_in_old_profiles():
    settings = Settings(True, "demo@example.com", PASSWORD, secure_cookie=False)
    with TestClient(create_app(settings=settings)) as client:
        for path in ROUTES:
            for method in ("GET", "POST", "PUT"):
                assert client.request(method, path).status_code == 404
    with pytest.raises(ValueError, match="postgres"):
        with TestClient(create_app(settings=replace(settings, account_lifecycle=True))):
            pytest.fail("memory lifecycle started")


def test_routes_normalize_email_keep_password_and_never_issue_cookie(account_client):
    client, store = account_client
    assert client.get("/healthz").json()["profile"] == "browser-session-v3"
    for path, (action, body) in ROUTES.items():
        response = client.post(path, headers={"Origin": ORIGIN}, json=body)
        assert response.status_code == (204 if action.endswith("confirm") else 202)
        assert response.content == (b"" if action.endswith("confirm") else b'{"status":"accepted"}')
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "set-cookie" not in response.headers
        assert store.calls[-1] == (
            action,
            "127.0.0.1",
            "한@example.com" if "email" in body else "",
            body.get("token", ""),
            body.get("password", ""),
        )


@pytest.mark.parametrize(
    "body",
    [
        b"null",
        b"[]",
        b'{"email":"a@b","email":"c@d"}',
        b'{"email":"a@b","extra":"x"}',
        b'{"email":null}',
        b'{"email":"a@b","password":"unused"}',
        b'{"email":"\\ud800@b"}',
        b'{"email":"a@b"} {}',
        b'{"email":NaN}',
    ],
)
def test_strict_account_json_rejects_before_storage(account_client, body):
    client, store = account_client
    response = client.post(
        "/auth/password-reset/request",
        content=body,
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert store.calls == []


def test_account_password_uses_unicode_scalars_and_byte_limit(account_client):
    client, store = account_client
    for password in ("😀" * 14, "a" * 14, "한" * 342, "\ud800" * 15):
        response = client.post(
            "/auth/register",
            content=json.dumps({"email": "a@b", "password": password}),
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        assert response.status_code == 400
    for password in ("😀" * 15, " " * 15, "a" * 1024):
        response = client.post(
            "/auth/register",
            json={"email": "a@b", "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 202
        assert store.calls[-1][-1] == password


@pytest.mark.parametrize("email", ["a\x00@b", "a\r\n@b", "a b@c", "a\x7f@b"])
def test_account_email_rejects_internal_control_and_space(account_client, email):
    client, store = account_client
    response = client.post(
        "/auth/password-reset/request", json={"email": email}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 400
    assert store.calls == []


def test_account_origin_media_size_token_and_method_boundaries(account_client):
    client, store = account_client
    path = "/auth/email-verification/confirm"
    assert client.post(path, json={"token": TOKEN}).status_code == 403
    assert client.post(path, content="{}", headers={"Origin": ORIGIN}).status_code == 415
    assert (
        client.post(
            path, content="x" * 4097, headers={"Origin": ORIGIN, "Content-Type": "application/json"}
        ).status_code
        == 413
    )
    for token in ("A" * 42, "A" * 44, "+" * 43, "é" * 43):
        assert (
            client.post(path, json={"token": token}, headers={"Origin": ORIGIN}).status_code == 400
        )
    assert client.get(path).status_code == 405
    assert store.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        AuthError(400, "INVALID_TOKEN"),
        AuthError(429, "RATE_LIMITED", {"Retry-After": "59"}),
        AuthError(503, "STORAGE_UNAVAILABLE"),
    ],
)
def test_storage_outcomes_preserve_error_and_no_cookie(account_client, failure):
    client, store = account_client
    store.failure = failure
    response = client.post(
        "/auth/email-verification/confirm", json={"token": TOKEN}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == failure.status
    assert response.json()["error"]["code"] == failure.code
    assert "set-cookie" not in response.headers
    if failure.status == 429:
        assert response.headers["retry-after"] == "59"
