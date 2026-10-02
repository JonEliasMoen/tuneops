from __future__ import annotations

from music_library.database import connect, initialize, setlist_metadata, store_youtube_mix_analytics


def test_setlist_metadata_includes_track_count_and_updated_timestamp(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO setlists(
                   folder_name, youtube_url, tidal_url, tidal_playlist_id,
                   tidal_playlist_name, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            ("darkprog", "https://youtu.be/video", "https://tidal.com/playlist/id", "id", "DJ Set Darkprog", "2026-10-02T12:30:00"),
        )
        connection.executemany(
            """INSERT INTO tracks(provider, provider_track_id, title, refreshed_at)
               VALUES ('tidal', ?, ?, '2026-10-02T12:30:00')""",
            [("one", "Track one"), ("two", "Track two")],
        )
        connection.executemany(
            """INSERT INTO setlist_tracks(folder_name, position, provider_track_id)
               VALUES ('darkprog', ?, ?)""",
            [(0, "one"), (1, "two")],
        )

    result = setlist_metadata(database)["darkprog"]

    assert result["track_count"] == 2
    assert result["updated_at"] == "2026-10-02T12:30:00"
    assert result["tidal_playlist_name"] == "DJ Set Darkprog"


def test_setlist_metadata_includes_independent_cached_youtube_analytics(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO setlists(folder_name, updated_at)
               VALUES ('darkprog', '2026-10-02T12:30:00')"""
        )
    stored = store_youtube_mix_analytics([{
        "folder_name": "darkprog", "video_id": "video-id", "views": 1234,
        "estimatedMinutesWatched": 600, "averageViewDuration": 320,
        "averageViewPercentage": 48.5, "likes": 50, "comments": 3,
        "subscribersGained": 7,
    }], database)

    result = setlist_metadata(database)["darkprog"]

    assert stored == 1
    assert result["youtube_views"] == 1234
    assert result["youtube_watch_minutes"] == 600
    assert result["youtube_average_view_duration"] == 320
    assert result["youtube_average_view_percentage"] == 48.5
    assert result["youtube_subscribers_gained"] == 7
