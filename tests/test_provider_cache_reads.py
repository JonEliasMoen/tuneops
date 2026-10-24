from __future__ import annotations

from datetime import datetime, timezone

from music_library.database import (
    cached_tidal_liked_tracks,
    cached_tidal_playlist,
    connect,
    initialize,
)


def _track(connection, track_id: str, title: str) -> None:
    connection.execute(
        """
        INSERT INTO tracks(provider, provider_track_id, title, refreshed_at)
        VALUES('tidal', ?, ?, ?)
        """,
        (track_id, title, datetime.now(timezone.utc).isoformat()),
    )


def test_cached_playlist_is_one_read_and_preserves_provider_order(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name,
                source_last_updated, indexed_at
            ) VALUES('tidal', 'playlist', 'Playlist', 'version-1', 'now')
            """
        )
        connection.execute(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name,
                source_last_updated, indexed_at
            ) VALUES('tidal', 'empty', 'Empty', 'version-1', 'now')
            """
        )
        _track(connection, "one", "One")
        _track(connection, "two", "Two")
        connection.executemany(
            """
            INSERT INTO playlist_tracks(
                provider, provider_playlist_id, position, provider_track_id
            ) VALUES('tidal', 'playlist', ?, ?)
            """,
            [(0, "two"), (1, "one")],
        )

    rows = cached_tidal_playlist("playlist", "version-1", database)

    assert [row["id"] for row in rows or []] == ["two", "one"]
    assert cached_tidal_playlist("playlist", "stale", database) is None
    assert cached_tidal_playlist("empty", "version-1", database) == []


def test_cached_liked_page_distinguishes_empty_page_from_stale_cache(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    now = datetime.now(timezone.utc).isoformat()
    with connect(database) as connection:
        _track(connection, "one", "One")
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', 'user', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO liked_tracks(
                provider, provider_user_id, position, provider_track_id
            ) VALUES('tidal', 'user', 0, 'one')
            """
        )

    assert [row["id"] for row in cached_tidal_liked_tracks(
        "user", limit=10, max_age_seconds=300, path=database,
    ) or []] == ["one"]
    assert cached_tidal_liked_tracks(
        "user", limit=10, offset=10, max_age_seconds=300, path=database,
    ) == []
    with connect(database) as connection:
        connection.execute(
            """
            UPDATE liked_track_snapshots SET cached_at='2000-01-01T00:00:00+00:00'
            WHERE provider='tidal' AND provider_user_id='user'
            """
        )
    assert cached_tidal_liked_tracks(
        "user", limit=10, max_age_seconds=300, path=database,
    ) is None
