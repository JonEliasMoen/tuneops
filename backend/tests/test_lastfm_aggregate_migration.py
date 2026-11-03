from __future__ import annotations

from datetime import datetime

import pytest

from backend.music_library.database import (
    connect,
    finalize_lastfm_aggregate_cutover,
    initialize,
    legacy_lastfm_usernames,
    rebuild_lastfm_aggregates_from_legacy,
    store_lastfm_aggregate_import,
)


def _timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, 0, 0).timestamp())


def _create_legacy_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE lastfm_scrobbles (
            username TEXT NOT NULL,
            played_at INTEGER NOT NULL,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            album TEXT NOT NULL DEFAULT '',
            mbid TEXT NOT NULL DEFAULT '',
            normalized_artist TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            tidal_track_id TEXT,
            match_confidence TEXT NOT NULL DEFAULT '',
            imported_at TEXT NOT NULL,
            PRIMARY KEY (username, played_at, normalized_artist, normalized_title)
        )
        """
    )


def test_legacy_lastfm_history_builds_verified_aggregate_only_state(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    plays = [
        (_timestamp(2025, 12, 1), "one"),
        (_timestamp(2026, 1, 1), "one"),
        (_timestamp(2026, 1, 2), "one"),
        (_timestamp(2026, 1, 3), "two"),
        (_timestamp(2026, 1, 4), None),
    ]
    with connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='lastfm_scrobbles'"
        ).fetchone() is None
        _create_legacy_table(connection)
        connection.executemany(
            """
            INSERT INTO lastfm_scrobbles(
                username, played_at, artist, title, normalized_artist,
                normalized_title, tidal_track_id, imported_at
            ) VALUES('aruzhu', ?, 'Artist', ?, 'artist', ?, ?, 'now')
            """,
            [
                (played_at, track_id or "Unmatched", track_id or "unmatched", track_id)
                for played_at, track_id in plays
            ],
        )

    result = rebuild_lastfm_aggregates_from_legacy("Aruzhu", path=database)

    assert result == {
        "fetched_plays": 5,
        "matched_plays": 4,
        "latest_scrobble_at": _timestamp(2026, 1, 4),
        "tracks": 2,
        "months": 2,
        "track_months": 3,
    }
    with connect(database) as connection:
        totals = connection.execute(
            """
            SELECT tidal_track_id, play_count, last_played
            FROM lastfm_track_totals
            WHERE username='aruzhu' ORDER BY tidal_track_id
            """
        ).fetchall()
        monthly = connection.execute(
            """
            SELECT year, month, tidal_track_id, play_count
            FROM lastfm_monthly_track_counts
            WHERE username='aruzhu' ORDER BY year, month, tidal_track_id
            """
        ).fetchall()
        state = connection.execute(
            "SELECT * FROM lastfm_import_state WHERE username='aruzhu'"
        ).fetchone()
        raw_count = connection.execute(
            "SELECT COUNT(*) FROM lastfm_scrobbles WHERE username='aruzhu'"
        ).fetchone()[0]

    assert [tuple(row) for row in totals] == [
        ("one", 3, _timestamp(2026, 1, 2)),
        ("two", 1, _timestamp(2026, 1, 3)),
    ]
    assert [tuple(row) for row in monthly] == [
        ("2025", "12", "one", 1),
        ("2026", "01", "one", 2),
        ("2026", "01", "two", 1),
    ]
    assert state["latest_scrobble_at"] == _timestamp(2026, 1, 4)
    assert state["matched_play_count"] == 4
    assert state["status"] == "ready"
    assert raw_count == 5


def test_legacy_aggregate_rebuild_is_idempotent(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        _create_legacy_table(connection)
        connection.execute(
            """
            INSERT INTO lastfm_scrobbles(
                username, played_at, artist, title, normalized_artist,
                normalized_title, tidal_track_id, imported_at
            ) VALUES('aruzhu', 1, 'Artist', 'Track', 'artist', 'track',
                     'tidal-one', 'now')
            """
        )

    first = rebuild_lastfm_aggregates_from_legacy("aruzhu", path=database)
    second = rebuild_lastfm_aggregates_from_legacy("ARUZHU", path=database)

    assert second == first
    with connect(database) as connection:
        assert connection.execute(
            "SELECT play_count FROM lastfm_track_totals"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT play_count FROM lastfm_monthly_track_counts"
        ).fetchone()[0] == 1


def test_verified_cutover_drops_legacy_events(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        _create_legacy_table(connection)
        connection.execute(
            """INSERT INTO lastfm_scrobbles(
                   username, played_at, artist, title, normalized_artist,
                   normalized_title, tidal_track_id, imported_at
               ) VALUES('aruzhu', 1, 'Artist', 'Track', 'artist', 'track',
                        'tidal-one', 'now')"""
        )
    assert legacy_lastfm_usernames(database) == ["aruzhu"]
    rebuild_lastfm_aggregates_from_legacy("aruzhu", path=database)

    result = finalize_lastfm_aggregate_cutover(database)

    assert result == {"users": 1, "matched_plays": 1, "raw_rows_removed": 1}
    assert legacy_lastfm_usernames(database) == []
    with connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "lastfm_scrobbles" not in tables
    assert "lastfm_track_totals" in tables


def test_cutover_refuses_mismatched_aggregates(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        _create_legacy_table(connection)
        connection.execute(
            """INSERT INTO lastfm_scrobbles(
                   username, played_at, artist, title, normalized_artist,
                   normalized_title, tidal_track_id, imported_at
               ) VALUES('aruzhu', 1, 'Artist', 'Track', 'artist', 'track',
                        'tidal-one', 'now')"""
        )
    rebuild_lastfm_aggregates_from_legacy("aruzhu", path=database)
    with connect(database) as connection:
        connection.execute(
            "UPDATE lastfm_track_totals SET play_count=99"
        )

    try:
        finalize_lastfm_aggregate_cutover(database)
    except RuntimeError as exc:
        assert "verification failed" in str(exc)
    else:
        raise AssertionError("Mismatched aggregates must block the cutover")

    assert legacy_lastfm_usernames(database) == ["aruzhu"]


def test_incremental_import_updates_only_matched_aggregates_and_watermark(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    first_latest = _timestamp(2026, 1, 2)
    added = store_lastfm_aggregate_import(
        "Aruzhu",
        [
            {"track_id": "one", "played_at": _timestamp(2026, 1, 1)},
            {"track_id": "one", "played_at": first_latest},
        ],
        latest_scrobble_at=first_latest,
        expected_previous_latest=None,
        path=database,
    )
    second_latest = _timestamp(2026, 2, 1)
    added += store_lastfm_aggregate_import(
        "aruzhu",
        [{"track_id": "two", "played_at": second_latest}],
        latest_scrobble_at=second_latest,
        expected_previous_latest=first_latest,
        path=database,
    )

    assert added == 3
    with connect(database) as connection:
        totals = connection.execute(
            """SELECT tidal_track_id, play_count FROM lastfm_track_totals
               ORDER BY tidal_track_id"""
        ).fetchall()
        months = connection.execute(
            """SELECT year, month, tidal_track_id, play_count
               FROM lastfm_monthly_track_counts
               ORDER BY year, month, tidal_track_id"""
        ).fetchall()
        state = connection.execute(
            "SELECT * FROM lastfm_import_state WHERE username='aruzhu'"
        ).fetchone()
    assert [tuple(row) for row in totals] == [("one", 2), ("two", 1)]
    assert [tuple(row) for row in months] == [
        ("2026", "01", "one", 2),
        ("2026", "02", "two", 1),
    ]
    assert state["latest_scrobble_at"] == second_latest
    assert state["matched_play_count"] == 3


def test_incremental_import_rejects_a_stale_watermark_without_writes(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    store_lastfm_aggregate_import(
        "aruzhu",
        [{"track_id": "one", "played_at": 10}],
        latest_scrobble_at=10,
        expected_previous_latest=None,
        path=database,
    )

    with pytest.raises(RuntimeError, match="changed concurrently"):
        store_lastfm_aggregate_import(
            "aruzhu",
            [{"track_id": "one", "played_at": 11}],
            latest_scrobble_at=11,
            expected_previous_latest=None,
            path=database,
        )

    with connect(database) as connection:
        assert connection.execute(
            "SELECT play_count FROM lastfm_track_totals"
        ).fetchone()[0] == 1
