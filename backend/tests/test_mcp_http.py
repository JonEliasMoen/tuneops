from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def configure_mcp(monkeypatch) -> None:
    monkeypatch.setenv("TUNEOPS_MCP_ISSUER_URL", "https://auth.example.com/")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")


def test_mcp_transport_requires_bearer_and_publishes_metadata(monkeypatch):
    configure_mcp(monkeypatch)
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "false")

    with TestClient(create_app(), base_url="https://tuneops.example") as client:
        exact_mount = client.post("/mcp", follow_redirects=False)
        unauthorized = client.get("/mcp/")
        metadata = client.get("/.well-known/oauth-protected-resource/mcp/")

    assert exact_mount.status_code == 401
    assert "location" not in exact_mount.headers
    assert "resource_metadata=" in exact_mount.headers["www-authenticate"]
    assert unauthorized.status_code == 401
    assert "resource_metadata=" in unauthorized.headers["www-authenticate"]
    assert metadata.status_code == 200
    assert metadata.json() == {
        "resource": "https://tuneops.example/mcp/",
        "authorization_servers": ["https://auth.example.com/"],
        "scopes_supported": ["profile:read", "library:read", "playlists:write"],
        "bearer_methods_supported": ["header"],
    }


def test_mcp_routes_bypass_cookie_login_only_when_configured(monkeypatch):
    configure_mcp(monkeypatch)
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "true")

    with TestClient(create_app(), base_url="https://tuneops.example") as client:
        assert client.get("/mcp/").status_code == 401
        assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        assert client.get("/api/v1/info").status_code == 401


def test_google_mcp_metadata_advertises_only_google_scopes(monkeypatch):
    monkeypatch.setenv("TUNEOPS_MCP_AUTH_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_MCP_CLIENT_ID", "chatgpt.apps.googleusercontent.com")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "false")
    monkeypatch.delenv("TUNEOPS_MCP_ISSUER_URL", raising=False)

    with TestClient(create_app(), base_url="https://tuneops.example") as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp/")

    assert metadata.status_code == 200
    assert metadata.json()["authorization_servers"] == [
        "https://accounts.google.com"
    ]
    assert metadata.json()["scopes_supported"] == ["openid", "email", "profile"]


def test_tuneops_oauth_publishes_authorization_server_metadata(monkeypatch):
    monkeypatch.setenv("TUNEOPS_MCP_AUTH_PROVIDER", "tuneops")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")
    monkeypatch.setenv("TUNEOPS_MCP_CLIENT_ID", "chatgpt-client")
    monkeypatch.setenv("TUNEOPS_MCP_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TUNEOPS_AUTH_REQUIRED", "false")
    monkeypatch.delenv("TUNEOPS_MCP_ISSUER_URL", raising=False)

    with TestClient(create_app(), base_url="https://tuneops.example") as client:
        protected = client.get("/.well-known/oauth-protected-resource/mcp/")
        authorization = client.get("/mcp/.well-known/oauth-authorization-server")
        standard_authorization = client.get(
            "/.well-known/oauth-authorization-server/mcp"
        )

    assert protected.status_code == 200
    assert protected.json()["authorization_servers"] == [
        "https://tuneops.example/mcp/"
    ]
    assert authorization.status_code == 200
    assert authorization.json()["authorization_endpoint"] == (
        "https://tuneops.example/mcp/authorize"
    )
    assert authorization.json()["token_endpoint"] == "https://tuneops.example/mcp/token"
    assert authorization.json()["scopes_supported"] == [
        "profile:read", "library:read", "playlists:write"
    ]
    assert "registration_endpoint" not in authorization.json()
    assert standard_authorization.status_code == 200
    assert standard_authorization.json() == authorization.json()
