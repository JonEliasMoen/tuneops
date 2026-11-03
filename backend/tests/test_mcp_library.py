from __future__ import annotations

import uuid

import pytest

from backend.app.services import mcp_library
from backend.music_library.database import connect, initialize


USER_ID = "92f78da4-8ff3-425d-b491-3bea22e39ef3"


def configure_owner(monkeypatch) -> None:
    monkeypatch.setenv("TUNEOPS_LOCAL_USER_ID", USER_ID)


def test_search_tracks_uses_live_tidal_and_returns_concise_rows(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}

    class Artist:
        id = "artist"
        name = "Artist"

    class Album:
        name = "Album"
        release_date = None

        @staticmethod
        def image(_size):
            return "https://example.test/cover.jpg"

    class Track:
        id = "123"
        name = "Track"
        artists = [Artist()]
        artist = artists[0]
        album = Album()
        version = ""
        duration = 200
        bpm = 124
        key = "A"
        key_scale = "minor"
        isrc = "TEST123"

    class Session:
        def search(self, query, *, models, limit, offset):
            captured.update(query=query, models=models, limit=limit, offset=offset)
            return {"tracks": [Track()]}

    monkeypatch.setattr(mcp_library.engine, "tidal_client", lambda interactive=False: Session())
    monkeypatch.setattr(
        mcp_library.engine,
        "_call",
        lambda _provider, _action, function, **details: captured.update(details=details) or function(),
    )

    result = mcp_library.search_tracks(USER_ID, "track", limit=500)

    assert captured["limit"] == 50
    assert captured["offset"] == 0
    assert captured["query"] == "track"
    assert captured["details"] == {"limit": 50, "offset": 0}
    assert result["source"] == "tidal"
    assert result["next_cursor"] is None
    assert result["tracks"][0]["tidal_track_id"] == "123"
    assert result["tracks"][0]["artists"] == ["Artist"]
    assert result["tracks"][0]["bpm"] == 124


def test_search_tracks_requires_a_query_before_contacting_tidal(monkeypatch):
    configure_owner(monkeypatch)
    monkeypatch.setattr(
        mcp_library.engine,
        "tidal_client",
        lambda **_kwargs: pytest.fail("TIDAL should not be contacted"),
    )

    with pytest.raises(ValueError, match="search query"):
        mcp_library.search_tracks(USER_ID, "  ")


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


def test_tidal_source_collection_is_writable(monkeypatch, tmp_path):
    configure_owner(monkeypatch)
    path = tmp_path / "library.sqlite3"
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name, collection_type, indexed_at
            ) VALUES('tidal', 'release-watch', 'releasewatch', 'source', '2026-01-01')
            """
        )

    result = mcp_library.list_collections(USER_ID, kind="source", path=path)

    assert result["collections"][0]["id"] == "release-watch"
    assert result["collections"][0]["writable"] is True


def test_track_memberships_rejects_unbounded_request(monkeypatch):
    configure_owner(monkeypatch)

    with pytest.raises(ValueError, match="between 1 and 50"):
        mcp_library.get_track_memberships(USER_ID, [str(index) for index in range(51)])


def test_add_tracks_to_playlist_reuses_provider_first_action(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mcp_library,
        "mutate_playlist_tracks",
        lambda action, track_ids, playlist_id: captured.update(
            action=action, track_ids=track_ids, playlist_id=playlist_id,
        ) or {"action": action, "changed": 2, "skipped": 0, "message": "Added"},
    )

    result = mcp_library.add_tracks_to_playlist(
        USER_ID, "playlist-1", ["track-1", "track-1", "track-2"],
    )

    assert captured == {
        "action": "add",
        "track_ids": ["track-1", "track-2"],
        "playlist_id": "playlist-1",
    }
    assert result["changed"] == 2


def test_add_tracks_to_playlist_rejects_unbounded_request(monkeypatch):
    configure_owner(monkeypatch)

    with pytest.raises(ValueError, match="between 1 and 50"):
        mcp_library.add_tracks_to_playlist(
            USER_ID, "playlist-1", [str(index) for index in range(51)],
        )
