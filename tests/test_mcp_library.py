from __future__ import annotations

import uuid

import pytest

from backend.app.services import mcp_library
from music_library.database import connect, initialize


USER_ID = "92f78da4-8ff3-425d-b491-3bea22e39ef3"


def configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("TUNEOPS_LOCAL_USER_ID", USER_ID)


def test_search_tracks_is_bounded_and_returns_concise_rows(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}

    def page(*args, **kwargs):
        captured.update(kwargs)
        return {
            "items": [{
                "id": "123",
                "title": "Track",
                "artist": "Artist",
                "artists": [{"id": "artist", "name": "Artist"}],
                "dimensions": {"rating": ["5"], "vibe": ["Dreamy"]},
                "playlists": [{"id": "playlist", "name": "Flying"}],
            }],
            "total": 70,
            "has_more": True,
        }

    monkeypatch.setattr(mcp_library, "collection_page", page)

    result = mcp_library.search_tracks(USER_ID, "track", limit=500)

    assert captured["limit"] == 50
    assert result["next_cursor"] == "1"
    assert result["tracks"][0]["tidal_track_id"] == "123"
    assert result["tracks"][0]["rating"] == ["5"]
    assert result["tracks"][0]["memberships"]["playlists"][0]["name"] == "Flying"


def test_library_rejects_a_different_internal_user(monkeypatch):
    configure_owner(monkeypatch)

    with pytest.raises(mcp_library.McpLibraryAccessError, match="no provisioned"):
        mcp_library.search_tracks(str(uuid.uuid4()), "track")


def test_list_collections_filters_and_counts_existing_tables(monkeypatch, tmp_path):
    configure_owner(monkeypatch)
    path = tmp_path / "library.sqlite3"
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name, collection_type, indexed_at
            ) VALUES('tidal', 'p1', 'Flying', 'playlist', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO tracks(provider, provider_track_id, title, artist, refreshed_at)
            VALUES('tidal', 't1', 'Track', 'Artist', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO playlist_tracks(provider, provider_playlist_id, provider_track_id, position)
            VALUES('tidal', 'p1', 't1', 0)
            """
        )

    result = mcp_library.list_collections(
        USER_ID, kind="playlist", query="fly", path=path
    )

    assert result["total"] == 1
    assert result["collections"] == [{
        "id": "p1",
        "name": "Flying",
        "type": "playlist",
        "track_count": 1,
        "writable": True,
        "path": "/playlists/p1",
    }]


def test_track_memberships_rejects_unbounded_request(monkeypatch):
    configure_owner(monkeypatch)

    with pytest.raises(ValueError, match="between 1 and 50"):
        mcp_library.get_track_memberships(USER_ID, [str(index) for index in range(51)])
