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
    oauth_client_secret: str = ""

    @property
    def advertised_scopes(self) -> tuple[str, ...]:
        if self.auth_provider == "google":
            return GOOGLE_SCOPES
        internal = (PROFILE_READ, LIBRARY_READ, PLAYLISTS_WRITE)
        return GOOGLE_SCOPES + internal if self.auth_provider == "tuneops" else internal


def load_settings() -> McpSettings:
    google_client_id = os.getenv("GOOGLE_MCP_CLIENT_ID", "").strip()
    configured_provider = os.getenv("TUNEOPS_MCP_AUTH_PROVIDER", "").strip().lower()
    auth_provider = configured_provider or ("google" if google_client_id else "jwt")
    if auth_provider not in {"google", "jwt", "tuneops"}:
        raise McpConfigurationError(
            "TUNEOPS_MCP_AUTH_PROVIDER must be google, jwt, or tuneops"
        )
    if auth_provider == "google" and not google_client_id:
        raise McpConfigurationError(
            "GOOGLE_MCP_CLIENT_ID is required for Google MCP authentication"
        )

    issuer_value = os.getenv("TUNEOPS_MCP_ISSUER_URL", "").strip()
    if auth_provider == "google" and not issuer_value:
        issuer_value = GOOGLE_ISSUER
    if auth_provider == "tuneops" and not issuer_value:
        public_url = _https_url(
            "TUNEOPS_PUBLIC_URL", os.getenv("TUNEOPS_PUBLIC_URL", "")
        ).rstrip("/")
        issuer_value = f"{public_url}/mcp/"
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
    oauth_client_id = (
        (os.getenv("TUNEOPS_MCP_CLIENT_ID") or google_client_id).strip()
        if auth_provider == "tuneops"
        else google_client_id
    )
    oauth_client_secret = (
        os.getenv("TUNEOPS_MCP_CLIENT_SECRET")
        or os.getenv("GOOGLE_MCP_CLIENT_SECRET")
        or ""
    ).strip()
    if auth_provider == "tuneops" and (not oauth_client_id or not oauth_client_secret):
        raise McpConfigurationError(
            "TUNEOPS_MCP_CLIENT_ID and TUNEOPS_MCP_CLIENT_SECRET are required"
        )
    return McpSettings(
        issuer_url=issuer,
        resource_url=resource,
        audience=audience,
        jwks_url=jwks_url,
        auth_provider=auth_provider,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
    )


def configured() -> bool:
    try:
        load_settings()
    except McpConfigurationError:
        return False
    return True
