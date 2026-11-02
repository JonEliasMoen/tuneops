from __future__ import annotations

from datetime import datetime

from music_library.database import (
    connect,
    initialize,
    lastfm_all_time_top_tracks,
    lastfm_history_navigation,
    lastfm_month_top_tracks,
    lastfm_year_top_tracks,
)


def _timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, 0, 0).timestamp())


def test_history_navigation_returns_years_and_months_from_one_query(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO lastfm_monthly_track_counts(
                username, year, month, tidal_track_id, play_count, last_played
            ) VALUES('aruzhu', ?, ?, ?, ?, ?)
            """,
            [
                ("2026", "01", "a", 2, _timestamp(2026, 1, 2)),
                ("2026", "01", "b", 1, _timestamp(2026, 1, 3)),
                ("2026", "02", "c", 1, _timestamp(2026, 2, 1)),
                ("2025", "12", "d", 1, _timestamp(2025, 12, 1)),
                ("2025", "12", "e", 1, _timestamp(2025, 12, 2)),
            ],
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


def test_aggregate_history_serves_navigation_and_top_track_results(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    plays = [
        (_timestamp(2026, 1, 1), "a"),
        (_timestamp(2026, 1, 2), "a"),
        (_timestamp(2026, 1, 3), "b"),
        (_timestamp(2026, 2, 1), "a"),
    ]
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO tracks(
                provider, provider_track_id, title, artist, refreshed_at
            ) VALUES('tidal', ?, ?, 'Artist', 'now')
            """,
            [(track_id, track_id.upper()) for track_id in {track for _, track in plays}],
        )
        connection.executemany(
            """INSERT INTO lastfm_track_totals(
                   username, tidal_track_id, play_count, last_played
               ) VALUES('aruzhu', ?, ?, ?)""",
            [
                ("a", 3, _timestamp(2026, 2, 1)),
                ("b", 1, _timestamp(2026, 1, 3)),
            ],
        )
        connection.executemany(
            """INSERT INTO lastfm_monthly_track_counts(
                   username, year, month, tidal_track_id, play_count, last_played
               ) VALUES('aruzhu', ?, ?, ?, ?, ?)""",
            [
                ("2026", "01", "a", 2, _timestamp(2026, 1, 2)),
                ("2026", "01", "b", 1, _timestamp(2026, 1, 3)),
                ("2026", "02", "a", 1, _timestamp(2026, 2, 1)),
            ],
        )

    navigation = lastfm_history_navigation("Aruzhu", minimum_tracks=1, path=database)

    assert len(navigation["months"]) == 2
    assert lastfm_month_top_tracks("Aruzhu", 2026, 1, path=database)[0]["play_count"] == 2
    assert lastfm_year_top_tracks("Aruzhu", 2026, path=database)[0]["play_count"] == 3
    assert lastfm_all_time_top_tracks("Aruzhu", path=database)[0]["play_count"] == 3
    with connect(database) as connection:
        cached = connection.execute(
            """
            SELECT year, month, tidal_track_id, play_count
            FROM lastfm_monthly_track_counts
            WHERE username='aruzhu' ORDER BY year, month, tidal_track_id
            """
        ).fetchall()
    assert [tuple(row) for row in cached] == [
        ("2026", "01", "a", 2),
        ("2026", "01", "b", 1),
        ("2026", "02", "a", 1),
    ]
