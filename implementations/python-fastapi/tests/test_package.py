from fastapi import Depends, Request
from fastapi.testclient import TestClient

from feature_auth import Settings, create_app, current_user

ORIGIN = "http://127.0.0.1:5173"
CREDENTIALS = {"email": "demo@example.com", "password": "correct-horse-battery-staple"}


def test_dependency_and_direct_request_access():
    app = create_app(settings=Settings(True, **CREDENTIALS, secure_cookie=False))

    @app.get("/protected")
    def protected(user: dict = Depends(current_user)):  # noqa: B008
        return user

    @app.get("/direct")
    def direct(request: Request):
        return current_user(request)

    with TestClient(app) as client:
        assert client.get("/protected").json()["error"]["code"] == "UNAUTHENTICATED"
        client.post("/auth/login", json=CREDENTIALS, headers={"Origin": ORIGIN})
        for path in ("/protected", "/direct"):
            assert client.get(path).json() == {"id": "demo-user", "email": CREDENTIALS["email"]}


def test_duplicate_csrf_header_is_rejected():
    app = create_app(settings=Settings(True, **CREDENTIALS, secure_cookie=False))
    with TestClient(app) as client:
        csrf = client.post("/auth/login", json=CREDENTIALS, headers={"Origin": ORIGIN}).json()[
            "csrfToken"
        ]
        response = client.post(
            "/auth/logout",
            headers=[("Origin", ORIGIN), ("X-CSRF-Token", csrf), ("X-CSRF-Token", csrf)],
        )
        assert response.status_code == 403
        assert client.get("/auth/me").status_code == 200
