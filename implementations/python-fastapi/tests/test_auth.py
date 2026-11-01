from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import AuthError, AuthState, Settings, create_app, normalize_email

ORIGIN = "http://127.0.0.1:5173"
CREDENTIALS = {"email": "demo@example.com", "password": "correct-horse-battery-staple"}


@pytest.fixture
def configured(monkeypatch):
    for key in (
        "AUTH_USER_EMAIL",
        "AUTH_USER_PASSWORD",
        "AUTH_SESSION_TTL_SECONDS",
        "AUTH_RATE_LIMIT_MAX",
        "AUTH_RATE_LIMIT_WINDOW_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_DEMO", "true")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGIN", ORIGIN)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")


@pytest.fixture
def client(configured):
    with TestClient(create_app()) as client:
        yield client


def login(client, **kwargs):
    return client.post("/auth/login", headers={"Origin": ORIGIN}, json=kwargs or CREDENTIALS)


def test_login_me_logout_revokes_copied_cookie(client):
    assert client.get("/auth/me").status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert response.json()["user"] == {"id": "demo-user", "email": "demo@example.com"}
    token = response.json()["csrfToken"]
    cookie = client.cookies.get("fs_session")
    assert len(token) >= 43
    assert len(cookie) >= 43
    assert cookie != token
    assert client.get("/auth/me").json() == response.json()
    logout = client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": token})
    assert logout.status_code == 204
    assert logout.content == b""
    assert "Max-Age=0" in logout.headers["set-cookie"]
    response = client.get("/auth/me", headers={"Cookie": f"fs_session={cookie}"})
    assert response.status_code == 401


def test_csrf_failure_preserves_session_and_origin_required(client):
    assert client.post("/auth/login", json=CREDENTIALS).status_code == 403
    assert (
        client.post(
            "/auth/login", headers={"Origin": "https://evil.example"}, json=CREDENTIALS
        ).json()["error"]["code"]
        == "ORIGIN_DENIED"
    )
    token = login(client).json()["csrfToken"]
    for headers in ({"Origin": ORIGIN}, {"Origin": ORIGIN, "X-CSRF-Token": "wrong"}):
        response = client.post("/auth/logout", headers=headers)
        assert response.json()["error"]["code"] == "CSRF_INVALID"
        assert client.get("/auth/me").status_code == 200
    assert (
        client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": token}).status_code
        == 204
    )
    assert client.post("/auth/logout", headers={"Origin": ORIGIN}).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        b"null",
        b"[]",
        b'{"email":"demo@example.com","email":"demo@example.com","password":"x"}',
        b'{"email":"demo@example.com","password":"x","extra":1}',
        b'{"email":"demo@example.com","password":null}',
        b'{"email":"missing-at","password":"x"}',
        b'{"email":"demo@example.com","password":""}',
        b'{"email":"demo@example.com","password":"\xff"}',
        b'{"email":"demo@example.com","password":"\\ud800"}',
        b'{"email":"demo@example.com","password":NaN}',
    ],
)
def test_strict_body_rejects_invalid_request(client, body):
    response = client.post(
        "/auth/login", headers={"Origin": ORIGIN, "Content-Type": "application/json"}, content=body
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_size_media_type_and_utf8_limits(client):
    response = client.post("/auth/login", headers={"Origin": ORIGIN}, content=b"{}")
    assert response.status_code == 415
    response = client.post(
        "/auth/login",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        content=b" " * 4097,
    )
    assert response.status_code == 413
    response = login(client, email="demo@example.com", password="한" * 342)
    assert response.status_code == 400
    response = login(client, email="  DEMO@EXAMPLE.COM ", password=CREDENTIALS["password"])
    assert response.status_code == 200


@pytest.mark.parametrize(
    "email",
    [
        "\u001cdemo@example.com",
        "\u00a0demo@example.com",
        "demo@example.com\u00a0",
    ],
)
def test_unicode_whitespace_is_preserved_for_authentication(client, email):
    response = login(client, email=email, password=CREDENTIALS["password"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_ascii_space_and_letter_normalization_authenticates(client):
    response = login(
        client, email="\t\n\v\f\r DEMO@EXAMPLE.COM \t\n\v\f\r", password=CREDENTIALS["password"]
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == CREDENTIALS["email"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("\t\n\v\f\r OWNER@EXAMPLE.COM \t\n\v\f\r", "owner@example.com"),
        ("\u001cOWNER@EXAMPLE.COM", "\u001cowner@example.com"),
        ("\u00a0OWNER@EXAMPLE.COM\u00a0", "\u00a0owner@example.com\u00a0"),
        ("İOWNER@EXAMPLE.COM", "İowner@example.com"),
        ("ÉOWNER@EXAMPLE.COM", "Éowner@example.com"),
    ],
)
def test_normalization_has_language_independent_ascii_rules(raw, expected):
    assert normalize_email(raw) == expected


def test_environment_and_requests_preserve_non_ascii_case(configured, monkeypatch):
    monkeypatch.setenv("AUTH_DEMO", "false")
    monkeypatch.setenv("AUTH_USER_EMAIL", " \tİOWNER@EXAMPLE.COM\r\n")
    monkeypatch.setenv("AUTH_USER_PASSWORD", "a-local-test-password")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGIN", "https://app.example.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    with TestClient(create_app(), base_url="https://app.example.com") as client:
        response = client.post(
            "/auth/login",
            headers={"Origin": "https://app.example.com"},
            json={"email": "İowner@example.com", "password": "a-local-test-password"},
        )
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "İowner@example.com"
        response = client.post(
            "/auth/login",
            headers={"Origin": "https://app.example.com"},
            json={"email": "i\u0307owner@example.com", "password": "a-local-test-password"},
        )
        assert response.status_code == 401


def test_new_login_invalidates_previous_session_only(client):
    first = login(client)
    old_cookie = client.cookies.get("fs_session")
    client.cookies.clear()
    assert login(client).status_code == 200
    independent_cookie = client.cookies.get("fs_session")
    second = client.post(
        "/auth/login",
        headers={"Origin": ORIGIN, "Cookie": f"fs_session={old_cookie}"},
        json=CREDENTIALS,
    )
    assert second.json()["csrfToken"] != first.json()["csrfToken"]
    assert client.cookies.get("fs_session") != old_cookie
    assert (
        client.get("/auth/me", headers={"Cookie": f"fs_session={independent_cookie}"}).status_code
        == 200
    )
    response = client.get("/auth/me", headers={"Cookie": f"fs_session={old_cookie}"})
    assert response.status_code == 401


def test_absolute_expiry_is_not_extended_by_read(configured):
    current = [100.0]
    with TestClient(create_app(clock=lambda: current[0])) as client:
        login(client)
        current[0] += 1799
        assert client.get("/auth/me").status_code == 200
        current[0] += 1
        assert client.get("/auth/me").status_code == 401
        assert client.post("/auth/logout", headers={"Origin": ORIGIN}).status_code == 204


def test_failed_login_limit_ignores_spoofed_forwarding_and_expires(configured):
    current = [100.0]
    with TestClient(create_app(clock=lambda: current[0])) as client:
        for index in range(5):
            response = client.post(
                "/auth/login",
                headers={"Origin": ORIGIN, "X-Forwarded-For": f"192.0.2.{index}"},
                json={"email": "absent@example.com", "password": "wrong"},
            )
            assert response.status_code == 401
        response = login(client)
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0
        current[0] += 60
        assert login(client).status_code == 200


def test_unknown_route_method_and_cache_headers(client):
    for method, path, status, code in (
        ("GET", "/auth/missing", 404, "NOT_FOUND"),
        ("GET", "/auth/login", 405, "METHOD_NOT_ALLOWED"),
        ("POST", "/auth/me", 405, "METHOD_NOT_ALLOWED"),
        ("GET", "/auth/me", 401, "UNAUTHENTICATED"),
    ):
        response = client.request(method, path)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "key,value",
    [
        ("AUTH_COOKIE_SECURE", "perhaps"),
        ("AUTH_ALLOWED_ORIGIN", "https://*.example.com"),
        ("AUTH_ALLOWED_ORIGIN", "http://example.com"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173/path"),
        ("AUTH_SESSION_TTL_SECONDS", "0"),
        ("AUTH_RATE_LIMIT_MAX", "-1"),
        ("AUTH_RATE_LIMIT_WINDOW_SECONDS", "no"),
        ("AUTH_DEMO", "false"),
    ],
)
def test_unsafe_or_invalid_config_fails_at_startup(configured, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        with TestClient(create_app()):
            pass


def test_production_requires_https_and_secure_cookie(configured, monkeypatch):
    monkeypatch.setenv("AUTH_DEMO", "false")
    monkeypatch.setenv("AUTH_USER_EMAIL", "owner@example.com")
    monkeypatch.setenv("AUTH_USER_PASSWORD", "a-local-test-password")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGIN", "https://app.example.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    with TestClient(create_app(), base_url="https://app.example.com") as client:
        response = client.post(
            "/auth/login",
            headers={"Origin": "https://app.example.com"},
            json={"email": "owner@example.com", "password": "a-local-test-password"},
        )
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "owner@example.com"
        assert "; Secure" in response.headers["set-cookie"]


def test_concurrent_failures_cannot_bypass_limit(configured, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMIT_MAX", "2")
    state = AuthState(Settings.from_env(), lambda: 100.0)

    def attempt(index):
        try:
            state.authenticate("same-peer", CREDENTIALS["email"], f"wrong-{index}", "")
        except AuthError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(8)))
    assert statuses.count(401) == 2
    assert statuses.count(429) == 6


def test_expired_records_are_pruned(configured):
    current = [100.0]
    state = AuthState(Settings.from_env(), lambda: current[0])
    token, _ = state.authenticate("good-peer", **CREDENTIALS, old_token="")
    with pytest.raises(AuthError):
        state.authenticate("bad-peer", CREDENTIALS["email"], "wrong", "")
    assert len(state.sessions) == 1
    assert len(state.failures) == 1
    current[0] += 1800
    assert state.get_session(token) is None
    assert state.sessions == {}
    assert state.failures == {}


def test_unsupported_store_is_rejected(configured, monkeypatch):
    monkeypatch.setenv("AUTH_STORE", "unsupported")
    with pytest.raises(ValueError, match="AUTH_STORE"):
        with TestClient(create_app()):
            pass


def test_postgres_requires_database_url(configured, monkeypatch):
    monkeypatch.setenv("AUTH_STORE", "postgres")
    monkeypatch.delenv("AUTH_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="AUTH_DATABASE_URL"):
        with TestClient(create_app()):
            pass
