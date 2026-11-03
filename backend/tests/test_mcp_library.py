from __future__ import annotations

import uuid

import pytest

from backend.app.services import mcp_library
from backend.music_tools.mixes.service import Mix
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


def test_liked_collection_is_bounded_and_defaults_to_newest_first(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mcp_library,
        "descriptor",
        lambda kind, collection_id: {
            "type": kind, "id": collection_id, "name": "TIDAL liked tracks",
        },
    )
    monkeypatch.setattr(
        mcp_library,
        "collection_page",
        lambda kind, collection_id, **kwargs: captured.update(
            kind=kind, collection_id=collection_id, **kwargs,
        ) or {"items": [{"id": "track-1", "title": "Newest"}], "total": 5308, "has_more": True},
    )

    result = mcp_library.get_collection_tracks(
        USER_ID, "liked", "liked", limit=500
    )

    assert captured["limit"] == 50
    assert captured["offset"] == 0
    assert captured["sort_field"] == "date_added"
    assert captured["sort_direction"] == "desc"
    assert result["ordering"] == "newest_liked_first"
    assert result["next_cursor"] == "1"


def test_list_my_mixes_is_bounded_and_uses_cached_metadata(monkeypatch):
    configure_owner(monkeypatch)
    mixes = [
        Mix(
            folder_name=f"mix-{index:02d}",
            youtube_url="https://youtu.be/abc123XYZ00",
            tidal_url="https://tidal.com/playlist/p1",
            tidal_playlist_id="p1",
            tidal_playlist_name="djset test",
            track_count=index,
            youtube_views=100 + index,
        )
        for index in range(60)
    ]
    monkeypatch.setattr(mcp_library, "discover_mixes", lambda: list(reversed(mixes)))
    monkeypatch.setattr(
        mcp_library,
        "youtube_video_metadata",
        lambda: {"abc123XYZ00": {"title": "Cached title", "upload_date": "2026-01-01"}},
    )

    result = mcp_library.list_my_mixes(USER_ID, limit=500, cursor="5")

    assert len(result["mixes"]) == 50
    assert result["mixes"][0]["mix_id"] == "mix-05"
    assert result["mixes"][0]["youtube_title"] == "Cached title"
    assert result["mixes"][0]["analytics"]["views"] == 105
    assert result["total"] == 60
    assert result["next_cursor"] == "55"


def test_get_my_mix_returns_bounded_track_page_without_provider_calls(monkeypatch):
    configure_owner(monkeypatch)
    mix = Mix(
        folder_name="drivingtechno",
        youtube_url="",
        tidal_url="",
        tidal_playlist_id="",
        tidal_playlist_name="",
        track_count=12,
    )
    captured = {}
    monkeypatch.setattr(
        mcp_library, "mix_for", lambda mix_id: mix if mix_id == "drivingtechno" else None,
    )
    monkeypatch.setattr(mcp_library, "youtube_video_metadata", lambda: {})
    monkeypatch.setattr(
        mcp_library,
        "get_collection_tracks",
        lambda user_id, kind, collection_id, **kwargs: captured.update(
            user_id=user_id, kind=kind, collection_id=collection_id, **kwargs,
        ) or {
            "tracks": [{"tidal_track_id": "track-1", "bpm": 128, "key": "06A"}],
            "total": 12,
            "next_cursor": "1",
        },
    )

    result = mcp_library.get_my_mix(
        USER_ID, "drivingtechno", limit=1, cursor="0"
    )

    assert captured == {
        "user_id": USER_ID,
        "kind": "setlist",
        "collection_id": "drivingtechno",
        "limit": 1,
        "cursor": "0",
    }
    assert result["mix"]["mix_id"] == "drivingtechno"
    assert result["tracks"][0]["bpm"] == 128
    assert result["track_total"] == 12


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


def test_remove_tracks_reuses_provider_first_action(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mcp_library,
        "mutate_playlist_tracks",
        lambda action, track_ids, playlist_id, **kwargs: captured.update(
            action=action, track_ids=track_ids, playlist_id=playlist_id, **kwargs,
        ) or {"action": action, "changed": 2},
    )

    result = mcp_library.remove_tracks_from_collection(
        USER_ID, "source-1", ["track-1", "track-1", "track-2"]
    )

    assert captured == {
        "action": "remove",
        "track_ids": ["track-1", "track-2"],
        "playlist_id": "source-1",
    }
    assert result["changed"] == 2


def test_move_tracks_reuses_provider_first_action_with_source(monkeypatch):
    configure_owner(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mcp_library,
        "mutate_playlist_tracks",
        lambda action, track_ids, playlist_id, **kwargs: captured.update(
            action=action, track_ids=track_ids, playlist_id=playlist_id, **kwargs,
        ) or {"action": action, "changed": 1},
    )

    result = mcp_library.move_tracks_between_playlists(
        USER_ID, "source-1", "destination-1", ["track-1"]
    )

    assert captured == {
        "action": "move",
        "track_ids": ["track-1"],
        "playlist_id": "destination-1",
        "source_playlist_id": "source-1",
    }
    assert result["changed"] == 1


@pytest.mark.parametrize(
    "function,args",
    [
        (mcp_library.remove_tracks_from_collection, ("playlist-1",)),
        (mcp_library.move_tracks_between_playlists, ("source-1", "destination-1")),
    ],
)
def test_destructive_playlist_actions_reject_unbounded_requests(
    monkeypatch, function, args,
):
    configure_owner(monkeypatch)
    with pytest.raises(ValueError, match="between 1 and 50"):
        function(USER_ID, *args, [str(index) for index in range(51)])
