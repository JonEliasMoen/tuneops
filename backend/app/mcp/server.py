"""TuneOps MCP server definition; mounting is enabled after IdP configuration."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from backend.app.services.mcp_profile import profile_for_user
from backend.app.services.mcp_library import (
    get_collection_tracks as read_collection_tracks,
    get_track as read_track,
    get_track_memberships as read_track_memberships,
    list_collections as read_collections,
    search_tracks as search_library_tracks,
)

from .auth import TuneOpsTokenVerifier, tuneops_user_id
from .config import LIBRARY_READ, PROFILE_READ, McpSettings


def _current_user_id(required_scope: str) -> str:
    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("Authentication is required")
    if required_scope not in access_token.scopes:
        raise PermissionError(f"The {required_scope} scope is required")
    user_id = tuneops_user_id(access_token)
    if not user_id:
        raise PermissionError("The authenticated identity is not linked to TuneOps")
    return user_id


def create_mcp_server(settings: McpSettings) -> MCPServer:
    server = MCPServer(
        "TuneOps",
        description="Search and safely manage the connected TuneOps music library.",
        token_verifier=TuneOpsTokenVerifier(settings),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.issuer_url),
            resource_server_url=AnyHttpUrl(settings.resource_url),
            required_scopes=[],
            validate_token_resource=True,
        ),
    )

    @server.tool(
        name="get_tuneops_profile",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta={
            "securitySchemes": [{"type": "oauth2", "scopes": [PROFILE_READ]}],
            "openai/profile": True,
        },
        structured_output=True,
    )
    def get_tuneops_profile() -> dict[str, object]:
        """Return the connected TuneOps account and safe provider statuses."""
        return profile_for_user(_current_user_id(PROFILE_READ))

    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    read_security = {
        "securitySchemes": [{"type": "oauth2", "scopes": [LIBRARY_READ]}]
    }

    @server.tool(
        name="search_tracks",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def search_tracks(
        query: str,
        limit: int = 20,
        cursor: str | None = None,
        bpm_min: float | None = None,
        bpm_max: float | None = None,
    ) -> dict[str, object]:
        """Search indexed TuneOps tracks by title, remix, artist or album."""
        return search_library_tracks(
            _current_user_id(LIBRARY_READ),
            query,
            limit=limit,
            cursor=cursor,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
        )

    @server.tool(
        name="get_track",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def get_track(tidal_track_id: str) -> dict[str, object]:
        """Inspect one exact indexed TIDAL track and its TuneOps metadata."""
        result = read_track(_current_user_id(LIBRARY_READ), tidal_track_id)
        if result is None:
            raise ValueError("Track was not found")
        return result

    @server.tool(
        name="list_collections",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def list_collections(
        kind: str = "",
        query: str = "",
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """List indexed TuneOps collections, optionally filtered by type/name."""
        return read_collections(
            _current_user_id(LIBRARY_READ),
            kind=kind,
            query=query,
            limit=limit,
            cursor=cursor,
        )

    @server.tool(
        name="get_collection_tracks",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def get_collection_tracks(
        kind: str,
        collection_id: str,
        limit: int = 20,
        cursor: str | None = None,
        sort_field: str = "",
        sort_direction: str = "",
    ) -> dict[str, object]:
        """Return a bounded track page from one exact TuneOps collection."""
        return read_collection_tracks(
            _current_user_id(LIBRARY_READ),
            kind,
            collection_id,
            limit=limit,
            cursor=cursor,
            sort_field=sort_field,
            sort_direction=sort_direction,
        )

    @server.tool(
        name="get_track_memberships",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def get_track_memberships(tidal_track_ids: list[str]) -> dict[str, object]:
        """Show which TuneOps collections contain up to 50 exact tracks."""
        return read_track_memberships(
            _current_user_id(LIBRARY_READ), tidal_track_ids
        )

    return server


def create_mcp_http_app(server: MCPServer, settings: McpSettings):
    parsed = urlparse(settings.resource_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed_hosts = [
        parsed.netloc,
        f"{parsed.hostname}:*",
        "localhost:*",
        "127.0.0.1:*",
    ]
    vercel_host = os.getenv("VERCEL_URL", "").strip()
    if vercel_host:
        allowed_hosts.append(vercel_host)
    transport_security = TransportSecuritySettings(
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=[origin],
    )
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
