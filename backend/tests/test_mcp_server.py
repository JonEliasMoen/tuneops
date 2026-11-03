from __future__ import annotations

import asyncio

from mcp import Client

from backend.app.mcp.config import McpSettings
from backend.app.mcp.server import create_mcp_server


def test_profile_tool_contract_is_read_only():
    settings = McpSettings(
        issuer_url="https://auth.example.com",
        resource_url="https://tuneops.example/mcp/",
        audience="https://api.example.com/tuneops",
        jwks_url="https://auth.example.com/.well-known/jwks.json",
    )
    server = create_mcp_server(settings)

    async def inspect_tools():
        async with Client(server) as client:
            return await client.list_tools()

    tools = asyncio.run(inspect_tools())
    profile = next(
        tool for tool in tools.tools if tool.name == "get_tuneops_profile"
    )

    assert profile.annotations.read_only_hint is True
    assert profile.annotations.destructive_hint is False
    assert profile.annotations.open_world_hint is False
    assert profile.meta["securitySchemes"][0]["scopes"] == ["profile:read"]
    assert {tool.name for tool in tools.tools} == {
        "get_tuneops_profile",
        "search_tracks",
        "get_track",
        "list_collections",
        "get_collection_tracks",
        "get_track_memberships",
        "list_my_mixes",
        "get_my_mix",
        "add_tracks_to_playlist",
        "remove_tracks_from_collection",
        "move_tracks_between_playlists",
    }
    write_names = {
        "add_tracks_to_playlist",
        "remove_tracks_from_collection",
        "move_tracks_between_playlists",
    }
    library_tools = [
        tool for tool in tools.tools
        if tool.name not in {"get_tuneops_profile", *write_names}
    ]
    assert all(tool.annotations.read_only_hint is True for tool in library_tools)
    assert all(
        tool.meta["securitySchemes"][0]["scopes"] == ["library:read"]
        for tool in library_tools
    )
    add_tool = next(tool for tool in tools.tools if tool.name == "add_tracks_to_playlist")
    search_tool = next(tool for tool in tools.tools if tool.name == "search_tracks")
    assert search_tool.annotations.open_world_hint is True
    assert add_tool.annotations.read_only_hint is False
    assert add_tool.annotations.destructive_hint is False
    assert add_tool.annotations.idempotent_hint is True
    assert add_tool.annotations.open_world_hint is True
    assert add_tool.meta["securitySchemes"][0]["scopes"] == ["playlists:write"]
    destructive_tools = [tool for tool in tools.tools if tool.name in write_names - {"add_tracks_to_playlist"}]
    assert all(tool.annotations.read_only_hint is False for tool in destructive_tools)
    assert all(tool.annotations.destructive_hint is True for tool in destructive_tools)
    assert all(tool.annotations.idempotent_hint is True for tool in destructive_tools)
    assert all(
        tool.meta["securitySchemes"][0]["scopes"] == ["playlists:write"]
        for tool in destructive_tools
    )


def test_google_tools_do_not_request_tuneops_scopes_from_google():
    settings = McpSettings(
        issuer_url="https://accounts.google.com",
        resource_url="https://tuneops.example/mcp/",
        audience="chatgpt.apps.googleusercontent.com",
        jwks_url="https://www.googleapis.com/oauth2/v3/certs",
        auth_provider="google",
        oauth_client_id="chatgpt.apps.googleusercontent.com",
    )
    server = create_mcp_server(settings)

    async def inspect_tools():
        async with Client(server) as client:
            return await client.list_tools()

    tools = asyncio.run(inspect_tools())

    assert all(
        tool.meta["securitySchemes"][0]["scopes"] == [] for tool in tools.tools
    )
