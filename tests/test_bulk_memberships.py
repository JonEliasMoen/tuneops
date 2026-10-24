from __future__ import annotations

from music_library.database import (
    add_tidal_liked_memberships,
    apply_tidal_playlist_membership_changes,
    connect,
    initialize,
    tidal_indexed_playlist,
    tidal_liked_membership_ids,
    tidal_tracks_by_ids,
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
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', 'user', 'old')
            """
        )
        connection.execute(
            """
            INSERT INTO liked_tracks(
                provider, provider_user_id, position, provider_track_id
            ) VALUES('tidal', 'user', 0, 'three')
            """
        )
        connection.executemany(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name, collection_type, indexed_at
            ) VALUES('tidal', ?, ?, 'playlist', 'old')
            """,
            [("source", "Source"), ("destination", "Destination")],
        )
        connection.executemany(
            """
            INSERT INTO playlist_tracks(
                provider, provider_playlist_id, position, provider_track_id
            ) VALUES('tidal', 'source', ?, ?)
            """,
            [(0, "one"), (1, "two")],
        )
        connection.execute(
            """
            INSERT INTO playlist_tracks(
                provider, provider_playlist_id, position, provider_track_id
            ) VALUES('tidal', 'destination', 0, 'three')
            """
        )


def test_selected_track_and_liked_membership_queries_are_bounded(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    tracks = tidal_tracks_by_ids(["two", "missing"], database)
    liked = tidal_liked_membership_ids("user", ["one", "three"], database)

    assert list(tracks) == ["two"]
    assert liked == {"three"}


def test_bulk_likes_prepend_once_and_keep_stable_positions(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    added = add_tidal_liked_memberships("user", ["one", "two", "one"], database)

    with connect(database) as connection:
        rows = connection.execute(
            """
            SELECT position, provider_track_id FROM liked_tracks
            WHERE provider='tidal' AND provider_user_id='user'
            ORDER BY position
            """
        ).fetchall()
    assert added == 2
    assert [(row["position"], row["provider_track_id"]) for row in rows] == [
        (0, "one"), (1, "two"), (2, "three"),
    ]


def test_playlist_membership_changes_are_applied_atomically_in_bulk(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    apply_tidal_playlist_membership_changes(
        "move", "destination", ["one", "two"], "source", database,
    )
    apply_tidal_playlist_membership_changes(
        "remove", "destination", ["one"], path=database,
    )

    with connect(database) as connection:
        source = connection.execute(
            "SELECT provider_track_id FROM playlist_tracks WHERE provider_playlist_id='source'"
        ).fetchall()
        destination = connection.execute(
            """
            SELECT position, provider_track_id FROM playlist_tracks
            WHERE provider_playlist_id='destination' ORDER BY position
            """
        ).fetchall()
    assert source == []
    assert [(row["position"], row["provider_track_id"]) for row in destination] == [
        (0, "three"), (2, "two"),
    ]
    assert tidal_indexed_playlist("destination", database)["name"] == "Destination"
