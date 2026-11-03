from __future__ import annotations

from backend.music_library.database import (
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


def test_clear_orphans_removes_local_metadata_and_lastfm_aggregates(tmp_path):
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
            INSERT INTO lastfm_track_totals(
                username, tidal_track_id, play_count, last_played
            ) VALUES('user', 'orphan', 3, 1)
            """
        )
        connection.execute(
            """INSERT INTO lastfm_monthly_track_counts(
                   username, year, month, tidal_track_id, play_count, last_played
               ) VALUES('user', '2026', '01', 'orphan', 3, 1)"""
        )
        connection.execute(
            """INSERT INTO lastfm_import_state(
                   username, latest_scrobble_at, matched_play_count,
                   last_imported_at, status
               ) VALUES('user', 1, 3, 'now', 'ready')"""
        )

    result = clear_orphaned_tidal_tracks(path=database)

    assert result == {"deleted_tracks": 1, "cleared_lastfm_matches": 3}
    with connect(database) as connection:
        assert connection.execute("SELECT provider_track_id FROM tracks").fetchall()[0][0] == "liked"
        assert connection.execute("SELECT COUNT(*) FROM lastfm_track_totals").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM lastfm_monthly_track_counts").fetchone()[0] == 0
        assert connection.execute(
            "SELECT matched_play_count FROM lastfm_import_state"
        ).fetchone()[0] == 0
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
