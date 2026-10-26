from __future__ import annotations

import pytest

from backend.app.mcp.config import McpConfigurationError, load_settings


def test_mcp_resource_defaults_to_public_url(monkeypatch):
    monkeypatch.delenv("GOOGLE_MCP_CLIENT_ID", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_AUTH_PROVIDER", raising=False)
    monkeypatch.setenv("TUNEOPS_MCP_ISSUER_URL", "https://auth.example.com/")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example/")
    monkeypatch.delenv("TUNEOPS_MCP_RESOURCE_URL", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_AUDIENCE", raising=False)

    settings = load_settings()

    # OAuth issuer matching is exact; a provider's canonical trailing slash
    # must not be silently removed.
    assert settings.issuer_url == "https://auth.example.com/"
    assert settings.resource_url == "https://tuneops.example/mcp/"
    assert settings.audience == settings.resource_url
    assert settings.jwks_url == "https://auth.example.com/.well-known/jwks.json"


def test_explicit_resource_and_audience_are_preserved(monkeypatch):
    monkeypatch.delenv("GOOGLE_MCP_CLIENT_ID", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_AUTH_PROVIDER", raising=False)
    monkeypatch.setenv("TUNEOPS_MCP_ISSUER_URL", "https://auth.example.com")
    monkeypatch.setenv("TUNEOPS_MCP_RESOURCE_URL", "https://mcp.example.com/tuneops/")
    monkeypatch.setenv("TUNEOPS_MCP_AUDIENCE", "https://api.example.com/tuneops")
    monkeypatch.setenv("TUNEOPS_MCP_JWKS_URL", "https://keys.example.com/jwks.json")

    settings = load_settings()

    assert settings.resource_url == "https://mcp.example.com/tuneops/"
    assert settings.audience == "https://api.example.com/tuneops"
    assert settings.jwks_url == "https://keys.example.com/jwks.json"


def test_mcp_urls_must_be_https(monkeypatch):
    monkeypatch.delenv("GOOGLE_MCP_CLIENT_ID", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_AUTH_PROVIDER", raising=False)
    monkeypatch.setenv("TUNEOPS_MCP_ISSUER_URL", "http://auth.example.com")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")

    with pytest.raises(McpConfigurationError, match="HTTPS"):
        load_settings()


def test_google_mcp_uses_google_oidc_and_client_audience(monkeypatch):
    monkeypatch.setenv("TUNEOPS_MCP_AUTH_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_MCP_CLIENT_ID", "chatgpt.apps.googleusercontent.com")
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")
    monkeypatch.delenv("TUNEOPS_MCP_ISSUER_URL", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_RESOURCE_URL", raising=False)
    monkeypatch.delenv("TUNEOPS_MCP_JWKS_URL", raising=False)

    settings = load_settings()

    assert settings.auth_provider == "google"
    assert settings.issuer_url == "https://accounts.google.com"
    assert settings.resource_url == "https://tuneops.example/mcp/"
    assert settings.audience == "chatgpt.apps.googleusercontent.com"
    assert settings.oauth_client_id == "chatgpt.apps.googleusercontent.com"
    assert settings.advertised_scopes == ("openid", "email", "profile")
    assert settings.jwks_url == "https://www.googleapis.com/oauth2/v3/certs"


def test_google_mcp_requires_a_dedicated_client_id(monkeypatch):
    monkeypatch.setenv("TUNEOPS_MCP_AUTH_PROVIDER", "google")
    monkeypatch.delenv("GOOGLE_MCP_CLIENT_ID", raising=False)
    monkeypatch.setenv("TUNEOPS_PUBLIC_URL", "https://tuneops.example")

    with pytest.raises(McpConfigurationError, match="GOOGLE_MCP_CLIENT_ID"):
        load_settings()
