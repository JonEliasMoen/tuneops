from __future__ import annotations

from music_library.database import (
    connect,
    initialize,
    replace_tidal_tracks_dimension,
    set_tidal_tracks_dimension_value,
)


def _seed(database):
    initialize(database)
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO tracks(provider, provider_track_id, title, refreshed_at)
            VALUES('tidal', ?, ?, 'now')
            """,
            [("one", "One"), ("two", "Two"), ("three", "Three")],
        )
        connection.executemany(
            """
            INSERT INTO track_dimension_values(
                provider, provider_track_id, dimension, value, created_at
            ) VALUES('tidal', ?, ?, ?, ?)
            """,
            [
                ("one", "rating", "2", "2026-01-01"),
                ("one", "vibe", "Dark", "2026-01-01"),
                ("two", "rating", "3", "2026-01-01"),
                ("three", "driver", "Groove", "2026-01-01"),
                ("three", "driver", "Bass", "2026-01-02"),
            ],
        )


def test_replace_dimension_updates_many_tracks_and_preserves_other_dimensions(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    result = replace_tidal_tracks_dimension(
        ["one", "two", "two"], "rating", ["5"], database,
    )

    assert result["one"] == {"rating": ["5"], "vibe": ["Dark"]}
    assert result["two"] == {"rating": ["5"]}


def test_toggle_dimension_enforces_single_value_for_entire_selection(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    enabled = set_tidal_tracks_dimension_value(
        ["one", "two"], "rating", "4", True, database,
    )
    disabled = set_tidal_tracks_dimension_value(
        ["one", "two"], "rating", "4", False, database,
    )

    assert enabled["one"]["rating"] == ["4"]
    assert enabled["two"]["rating"] == ["4"]
    assert "rating" not in disabled["one"]
    assert "rating" not in disabled["two"]
    assert disabled["one"]["vibe"] == ["Dark"]


def test_toggle_dimension_evicts_oldest_value_at_cardinality_limit(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    result = set_tidal_tracks_dimension_value(
        ["three"], "driver", "Melody", True, database,
    )

    assert result["three"]["driver"] == ["Bass", "Melody"]
