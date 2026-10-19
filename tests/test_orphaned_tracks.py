from __future__ import annotations

from music_library.database import (
    clear_orphaned_tidal_tracks,
    connect,
    delete_orphaned_tidal_track,
    initialize,
    orphaned_tidal_tracks,
)


def _track(connection, track_id: str, title: str) -> None:
    connection.execute(
        """
        INSERT INTO tracks(provider, provider_track_id, title, artist, album, refreshed_at)
        VALUES('tidal', ?, ?, 'Test Artist', 'Test Album', '2026-10-18T00:00:00+00:00')
        """,
        (track_id, title),
    )


def test_orphans_exclude_every_supported_library_membership(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        for track_id in ("orphan", "liked", "playlist", "setlist", "watched"):
            _track(connection, track_id, track_id.title())
        connection.execute("INSERT INTO liked_tracks VALUES('tidal', 'user', 0, 'liked', NULL)")
        connection.execute("INSERT INTO playlists VALUES('tidal', 'playlist-id', 'Playlist', 'playlist', NULL, 'now')")
        connection.execute("INSERT INTO playlist_tracks VALUES('tidal', 'playlist-id', 0, 'playlist', NULL)")
        connection.execute("INSERT INTO setlists(folder_name, updated_at) VALUES('mix', 'now')")
        connection.execute("INSERT INTO setlist_tracks VALUES('mix', 0, 'tidal', 'setlist', '', NULL)")
        connection.execute("INSERT INTO watched_mixes(video_id, youtube_url, added_at) VALUES('video', 'https://youtu.be/video', 'now')")
        connection.execute("INSERT INTO watched_mix_tracks VALUES('video', 0, 'tidal', 'watched', 'now')")

    result = orphaned_tidal_tracks(path=database)

    assert result["total"] == 1
    assert [track["id"] for track in result["items"]] == ["orphan"]


def test_clear_orphans_removes_local_metadata_and_resets_lastfm_match(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        _track(connection, "orphan", "Orphan")
        _track(connection, "liked", "Liked")
        connection.execute("INSERT INTO liked_tracks VALUES('tidal', 'user', 0, 'liked', NULL)")
        connection.execute(
            "INSERT INTO track_user_metadata VALUES('tidal', 'orphan', 5, '', 'now')"
        )
        connection.execute(
            "INSERT INTO track_dimension_values VALUES('tidal', 'orphan', 'vibe', 'Dark', 'now')"
        )
        connection.execute(
            """
            INSERT INTO lastfm_scrobbles(
                username, played_at, artist, title, normalized_artist,
                normalized_title, tidal_track_id, match_confidence, imported_at
            ) VALUES('user', 1, 'Test Artist', 'Orphan', 'test artist',
                     'orphan', 'orphan', 'exact', 'now')
            """
        )

    result = clear_orphaned_tidal_tracks(path=database)

    assert result == {"deleted_tracks": 1, "cleared_lastfm_matches": 1}
    with connect(database) as connection:
        assert connection.execute("SELECT provider_track_id FROM tracks").fetchall()[0][0] == "liked"
        scrobble = connection.execute(
            "SELECT tidal_track_id, match_confidence FROM lastfm_scrobbles"
        ).fetchone()
        assert scrobble["tidal_track_id"] is None
        assert scrobble["match_confidence"] == ""
        assert connection.execute("SELECT COUNT(*) FROM track_user_metadata").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM track_dimension_values").fetchone()[0] == 0


def test_delete_one_orphan_refuses_a_track_with_membership(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        _track(connection, "orphan", "Orphan")
        _track(connection, "liked", "Liked")
        connection.execute("INSERT INTO liked_tracks VALUES('tidal', 'user', 0, 'liked', NULL)")

    assert delete_orphaned_tidal_track("orphan", path=database)["deleted_tracks"] == 1
    assert delete_orphaned_tidal_track("liked", path=database)["deleted_tracks"] == 0
    with connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tracks WHERE provider_track_id='liked'"
        ).fetchone()[0] == 1
