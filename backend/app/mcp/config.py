"""Environment-backed MCP resource-server configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_SCOPES = ("openid", "email", "profile")

# These are TuneOps authorization capabilities, not scopes understood by
# Google's authorization server. Keep them server-side when Google is the MCP
# identity provider.
PROFILE_READ = "profile:read"
LIBRARY_READ = "library:read"
PLAYLISTS_WRITE = "playlists:write"


class McpConfigurationError(RuntimeError):
    pass


def _https_url(name: str, value: str) -> str:
    normalized = str(value or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise McpConfigurationError(f"{name} must be an absolute HTTPS URL")
    return normalized


@dataclass(frozen=True)
class McpSettings:
    issuer_url: str
    resource_url: str
    audience: str
    jwks_url: str
    auth_provider: str = "jwt"
    oauth_client_id: str = ""

    @property
    def advertised_scopes(self) -> tuple[str, ...]:
        return GOOGLE_SCOPES if self.auth_provider == "google" else (
            PROFILE_READ,
            LIBRARY_READ,
            PLAYLISTS_WRITE,
        )


def load_settings() -> McpSettings:
    google_client_id = os.getenv("GOOGLE_MCP_CLIENT_ID", "").strip()
    configured_provider = os.getenv("TUNEOPS_MCP_AUTH_PROVIDER", "").strip().lower()
    auth_provider = configured_provider or ("google" if google_client_id else "jwt")
    if auth_provider not in {"google", "jwt"}:
        raise McpConfigurationError(
            "TUNEOPS_MCP_AUTH_PROVIDER must be either google or jwt"
        )
    if auth_provider == "google" and not google_client_id:
        raise McpConfigurationError(
            "GOOGLE_MCP_CLIENT_ID is required for Google MCP authentication"
        )

    issuer_value = os.getenv("TUNEOPS_MCP_ISSUER_URL", "").strip()
    if auth_provider == "google" and not issuer_value:
        issuer_value = GOOGLE_ISSUER
    issuer = _https_url("TUNEOPS_MCP_ISSUER_URL", issuer_value)
    explicit_resource = os.getenv("TUNEOPS_MCP_RESOURCE_URL", "").strip()
    if explicit_resource:
        resource = _https_url("TUNEOPS_MCP_RESOURCE_URL", explicit_resource).rstrip("/") + "/"
    else:
        public_url = _https_url(
            "TUNEOPS_PUBLIC_URL", os.getenv("TUNEOPS_PUBLIC_URL", "")
        ).rstrip("/")
        resource = f"{public_url}/mcp/"
    audience = (
        google_client_id
        if auth_provider == "google"
        else os.getenv("TUNEOPS_MCP_AUDIENCE", "").strip() or resource
    )
    explicit_jwks = os.getenv("TUNEOPS_MCP_JWKS_URL", "").strip()
    jwks_url = (
        _https_url("TUNEOPS_MCP_JWKS_URL", explicit_jwks)
        if explicit_jwks
        else (
            "https://www.googleapis.com/oauth2/v3/certs"
            if auth_provider == "google"
            else f"{issuer.rstrip('/')}/.well-known/jwks.json"
        )
    )
    return McpSettings(
        issuer_url=issuer,
        resource_url=resource,
        audience=audience,
        jwks_url=jwks_url,
        auth_provider=auth_provider,
        oauth_client_id=google_client_id,
    )


def configured() -> bool:
    try:
        load_settings()
    except McpConfigurationError:
        return False
    return True
