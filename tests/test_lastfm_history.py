from __future__ import annotations

from datetime import datetime

from music_library.database import connect, initialize, lastfm_history_navigation


def _timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, 0, 0).timestamp())


def test_history_navigation_returns_years_and_months_from_one_query(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    records = [
        (_timestamp(2026, 1, 1), "a"),
        (_timestamp(2026, 1, 2), "a"),
        (_timestamp(2026, 1, 3), "b"),
        (_timestamp(2026, 2, 1), "c"),
        (_timestamp(2025, 12, 1), "d"),
        (_timestamp(2025, 12, 2), "e"),
    ]
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO lastfm_scrobbles(
                username, played_at, artist, title, normalized_artist,
                normalized_title, tidal_track_id, imported_at
            ) VALUES('aruzhu', ?, 'Artist', ?, 'artist', ?, ?, 'now')
            """,
            [(played_at, track_id, track_id, track_id) for played_at, track_id in records],
        )

    result = lastfm_history_navigation("Aruzhu", minimum_tracks=2, path=database)

    assert result == {
        "years": [
            {"year": "2026", "track_count": 3, "play_count": 4},
            {"year": "2025", "track_count": 2, "play_count": 2},
        ],
        "months": [
            {"year": "2026", "track_count": 2, "play_count": 3, "month": "01"},
            {"year": "2025", "track_count": 2, "play_count": 2, "month": "12"},
        ],
    }


def test_history_navigation_skips_database_for_missing_username(tmp_path):
    database = tmp_path / "does-not-exist.sqlite3"

    assert lastfm_history_navigation("", path=database) == {
        "years": [], "months": [],
    }
    assert not database.exists()
