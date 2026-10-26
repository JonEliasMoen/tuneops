"""Environment-backed MCP resource-server configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


PROFILE_READ = "profile:read"
LIBRARY_READ = "library:read"
PLAYLISTS_WRITE = "playlists:write"
SUPPORTED_SCOPES = (PROFILE_READ, LIBRARY_READ, PLAYLISTS_WRITE)


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


def load_settings() -> McpSettings:
    issuer = _https_url(
        "TUNEOPS_MCP_ISSUER_URL", os.getenv("TUNEOPS_MCP_ISSUER_URL", "")
    )
    explicit_resource = os.getenv("TUNEOPS_MCP_RESOURCE_URL", "").strip()
    if explicit_resource:
        resource = _https_url("TUNEOPS_MCP_RESOURCE_URL", explicit_resource).rstrip("/") + "/"
    else:
        public_url = _https_url(
            "TUNEOPS_PUBLIC_URL", os.getenv("TUNEOPS_PUBLIC_URL", "")
        ).rstrip("/")
        resource = f"{public_url}/mcp/"
    audience = os.getenv("TUNEOPS_MCP_AUDIENCE", "").strip() or resource
    explicit_jwks = os.getenv("TUNEOPS_MCP_JWKS_URL", "").strip()
    jwks_url = (
        _https_url("TUNEOPS_MCP_JWKS_URL", explicit_jwks)
        if explicit_jwks
        else f"{issuer.rstrip('/')}/.well-known/jwks.json"
    )
    return McpSettings(
        issuer_url=issuer,
        resource_url=resource,
        audience=audience,
        jwks_url=jwks_url,
    )


def configured() -> bool:
    try:
        load_settings()
    except McpConfigurationError:
        return False
    return True
