"""TuneOps MCP server definition; mounting is enabled after IdP configuration."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from backend.app.services.mcp_profile import profile_for_user
from backend.app.services.mcp_library import (
    add_tracks_to_playlist as add_library_tracks_to_playlist,
    get_collection_tracks as read_collection_tracks,
    get_my_mix as read_my_mix,
    get_track as read_track,
    get_track_memberships as read_track_memberships,
    list_collections as read_collections,
    list_my_mixes as read_my_mixes,
    move_tracks_between_playlists as move_library_tracks_between_playlists,
    remove_tracks_from_collection as remove_library_tracks_from_collection,
    search_tracks as search_library_tracks,
)

from .auth import token_verifier_for, tuneops_user_id
from .config import LIBRARY_READ, PLAYLISTS_WRITE, PROFILE_READ, McpSettings
from .oauth_provider import TuneOpsOAuthProvider


def _current_user_id(required_scope: str | None = None) -> str:
    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("Authentication is required")
    if required_scope and required_scope not in access_token.scopes:
        raise PermissionError(f"The {required_scope} scope is required")
    user_id = tuneops_user_id(access_token)
    if not user_id:
        raise PermissionError("The authenticated identity is not linked to TuneOps")
    return user_id


def create_mcp_server(settings: McpSettings) -> MCPServer:
    profile_scope = None if settings.auth_provider == "google" else PROFILE_READ
    library_scope = None if settings.auth_provider == "google" else LIBRARY_READ
    playlists_scope = None if settings.auth_provider == "google" else PLAYLISTS_WRITE
    oauth_provider = (
        TuneOpsOAuthProvider(settings) if settings.auth_provider == "tuneops" else None
    )
    server = MCPServer(
        "TuneOps",
        description="Search and safely manage the connected TuneOps music library.",
        token_verifier=None if oauth_provider else token_verifier_for(settings),
        auth_server_provider=oauth_provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.issuer_url),
            resource_server_url=AnyHttpUrl(settings.resource_url),
            client_registration_options=(
                ClientRegistrationOptions(
                    enabled=False,
                    valid_scopes=list(settings.advertised_scopes),
                    default_scopes=["openid", "email", "profile", PROFILE_READ, LIBRARY_READ],
                )
                if oauth_provider is not None
                else None
            ),
            required_scopes=[],
            validate_token_resource=True,
        ),
    )

    if oauth_provider is not None:
        @server.custom_route(
            "/oauth/google/callback", methods=["GET"], include_in_schema=False
        )
        async def google_oauth_callback(request):
            return await oauth_provider.google_callback(request)

        @server.custom_route(
            "/.well-known/openid-configuration", methods=["GET"],
            include_in_schema=False,
        )
        async def openid_configuration(request):
            return await oauth_provider.openid_configuration(request)

        @server.custom_route(
            "/userinfo", methods=["GET", "POST"], include_in_schema=False
        )
        async def userinfo(request):
            return await oauth_provider.userinfo(request)

    @server.tool(
        name="get_tuneops_profile",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta={
            "securitySchemes": [
                {"type": "oauth2", "scopes": [profile_scope] if profile_scope else []}
            ],
            "openai/profile": True,
        },
        structured_output=True,
    )
    def get_tuneops_profile() -> dict[str, object]:
        """Return the connected TuneOps account and safe provider statuses."""
        return profile_for_user(_current_user_id(profile_scope))

    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    read_security = {
        "securitySchemes": [
            {"type": "oauth2", "scopes": [library_scope] if library_scope else []}
        ]
    }

    @server.tool(
        name="search_tracks",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
        """Search the live TIDAL catalog by track, remix, artist or album text."""
        return search_library_tracks(
            _current_user_id(library_scope),
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
        result = read_track(_current_user_id(library_scope), tidal_track_id)
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
            _current_user_id(library_scope),
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
        """Return a bounded track page; Liked defaults to newest likes first."""
        return read_collection_tracks(
            _current_user_id(library_scope),
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
            _current_user_id(library_scope), tidal_track_ids
        )

    @server.tool(
        name="list_my_mixes",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def list_my_mixes(
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """List a bounded page of My Mixes and their cached analytics."""
        return read_my_mixes(
            _current_user_id(library_scope), limit=limit, cursor=cursor
        )

    @server.tool(
        name="get_my_mix",
        annotations=read_annotations,
        meta=read_security,
        structured_output=True,
    )
    def get_my_mix(
        mix_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """Read one My Mix plus a bounded ordered page of its cached tracks."""
        result = read_my_mix(
            _current_user_id(library_scope),
            mix_id,
            limit=limit,
            cursor=cursor,
        )
        if result is None:
            raise ValueError("My Mix was not found")
        return result

    @server.tool(
        name="add_tracks_to_playlist",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        meta={
            "securitySchemes": [
                {
                    "type": "oauth2",
                    "scopes": [playlists_scope] if playlists_scope else [],
                }
            ],
        },
        structured_output=True,
    )
    def add_tracks_to_playlist(
        playlist_id: str,
        tidal_track_ids: list[str],
    ) -> dict[str, object]:
        """Add tracks to an indexed TIDAL Playlist, Event, or Source, then mirror TuneOps."""
        return add_library_tracks_to_playlist(
            _current_user_id(playlists_scope),
            playlist_id,
            tidal_track_ids,
        )

    @server.tool(
        name="remove_tracks_from_collection",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
        meta={
            "securitySchemes": [
                {
                    "type": "oauth2",
                    "scopes": [playlists_scope] if playlists_scope else [],
                }
            ],
        },
        structured_output=True,
    )
    def remove_tracks_from_collection(
        playlist_id: str,
        tidal_track_ids: list[str],
    ) -> dict[str, object]:
        """Remove tracks from a TIDAL-backed Playlist, Event, or Source."""
        return remove_library_tracks_from_collection(
            _current_user_id(playlists_scope), playlist_id, tidal_track_ids
        )

    @server.tool(
        name="move_tracks_between_playlists",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        ),
        meta={
            "securitySchemes": [
                {
                    "type": "oauth2",
                    "scopes": [playlists_scope] if playlists_scope else [],
                }
            ],
        },
        structured_output=True,
    )
    def move_tracks_between_playlists(
        source_playlist_id: str,
        destination_playlist_id: str,
        tidal_track_ids: list[str],
    ) -> dict[str, object]:
        """Move tracks between indexed TIDAL playlists with rollback on failure."""
        return move_library_tracks_between_playlists(
            _current_user_id(playlists_scope),
            source_playlist_id,
            destination_playlist_id,
            tidal_track_ids,
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
