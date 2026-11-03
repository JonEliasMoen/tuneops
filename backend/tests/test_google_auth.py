from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.app import auth
from backend.app.main import create_app


def configure(monkeypatch) -> None:
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "true")
    monkeypatch.setenv("TUNEOPS_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("TUNEOPS_ALLOWED_EMAILS", "jon@example.com")
    monkeypatch.setenv("GOOGLE_SIGNIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_SIGNIN_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TUNEOPS_LOCAL_USER_ID", "92f78da4-8ff3-425d-b491-3bea22e39ef3")
    monkeypatch.setenv(
        "GOOGLE_SIGNIN_REDIRECT_URI",
        "https://tuneops.example/api/v1/auth/google/callback",
    )


def test_signed_session_round_trip_and_tampering(monkeypatch):
    configure(monkeypatch)
    value = auth.sign({"sub": "google-user", "email": "jon@example.com", "iat": 1_900_000_000})

    assert auth.unsign(value)["sub"] == "google-user"
    assert auth.unsign(value + "tampered") is None


def test_login_redirect_uses_oidc_pkce_and_sets_transaction_cookie(monkeypatch):
    configure(monkeypatch)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/auth/google/login?return_to=/liked-tracks", follow_redirects=False
    )

    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert auth.OAUTH_COOKIE in response.cookies


def test_private_routes_require_a_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/v1/info")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert client.get("/api/v1/health").status_code == 401


def test_signed_session_allows_private_routes(monkeypatch):
    configure(monkeypatch)
    client = TestClient(create_app())
    client.cookies.set(
        auth.SESSION_COOKIE,
        auth.sign({
            "sub": "google-user",
            "email": "jon@example.com",
            "name": "Jon",
            "iat": int(time.time()),
        }),
    )

    response = client.get("/api/v1/info")

    assert response.status_code == 200


def test_legacy_session_resolves_stable_internal_user(monkeypatch):
    configure(monkeypatch)
    client = TestClient(create_app())
    client.cookies.set(
        auth.SESSION_COOKIE,
        auth.sign({
            "sub": "google-user",
            "email": "jon@example.com",
            "iat": int(time.time()),
        }),
    )

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json()["user"]["user_id"] == "92f78da4-8ff3-425d-b491-3bea22e39ef3"


def test_google_callback_creates_session(monkeypatch):
    configure(monkeypatch)
    client = TestClient(create_app())
    login = client.get(
        "/api/v1/auth/google/login?return_to=/liked-tracks",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    transaction = auth.unsign(client.cookies.get(auth.OAUTH_COOKIE))
    assert transaction is not None

    class TokenResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id_token": "verified-by-the-test-double"}

    monkeypatch.setattr(auth.requests, "post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr(
        auth.id_token,
        "verify_oauth2_token",
        lambda *args, **kwargs: {
            "sub": "google-user",
            "email": "jon@example.com",
            "email_verified": True,
            "name": "Jon",
            "nonce": transaction["nonce"],
        },
    )
    monkeypatch.setattr(auth, "bootstrap_google_identity", lambda claims: "tuneops-user")

    callback = client.get(
        f"/api/v1/auth/google/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/liked-tracks"
    assert auth.SESSION_COOKIE in callback.cookies
    assert client.get("/api/v1/info").status_code == 200
    session = auth.unsign(callback.cookies.get(auth.SESSION_COOKIE))
    assert session is not None
    assert session["user_id"] == "tuneops-user"
