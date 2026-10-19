from __future__ import annotations

from music_library.database import connect, initialize, tidal_artist_overview_page


def _seed(database):
    initialize(database)
    with connect(database) as connection:
        connection.executemany(
            """INSERT INTO tracks(provider, provider_track_id, title, refreshed_at)
               VALUES ('tidal', ?, ?, 'now')""",
            [("one", "One"), ("two", "Two"), ("outside", "Outside")],
        )
        connection.executemany(
            """INSERT INTO artists(provider, artist_key, name, normalized_name)
               VALUES ('tidal', ?, ?, ?)""",
            [("alpha", "Alpha", "alpha"), ("beta", "Beta", "beta"), ("outside", "Outside", "outside")],
        )
        connection.executemany(
            """INSERT INTO track_artists(provider, provider_track_id, artist_key, position)
               VALUES ('tidal', ?, ?, ?)""",
            [("one", "alpha", 0), ("two", "alpha", 0), ("two", "beta", 1), ("outside", "outside", 0)],
        )
        connection.execute(
            "INSERT INTO liked_tracks(provider, provider_user_id, position, provider_track_id) VALUES ('tidal', 'user', 0, 'one')"
        )
        connection.execute(
            "INSERT INTO playlists(provider, provider_playlist_id, name, collection_type, indexed_at) VALUES ('tidal', 'event', 'Event', 'event', 'now')"
        )
        connection.execute(
            "INSERT INTO playlist_tracks(provider, provider_playlist_id, position, provider_track_id) VALUES ('tidal', 'event', 0, 'one')"
        )
        connection.execute("INSERT INTO setlists(folder_name, updated_at) VALUES ('mix', 'now')")
        connection.execute(
            "INSERT INTO setlist_tracks(folder_name, position, provider_track_id) VALUES ('mix', 0, 'two')"
        )
        connection.executemany(
            """INSERT INTO lastfm_scrobbles(
                   username, played_at, artist, title, normalized_artist,
                   normalized_title, tidal_track_id, imported_at
               ) VALUES ('aruzhu', ?, ?, ?, ?, ?, ?, 'now')""",
            [
                (1, "Alpha", "One", "alpha", "one", "one"),
                (2, "Alpha", "One", "alpha", "one", "one"),
                (3, "Alpha, Beta", "Two", "alpha beta", "two", "two"),
                (4, "Outside", "Outside", "outside", "outside", "outside"),
            ],
        )


def test_artist_overview_matches_artist_detail_membership_scope_and_scrobbles(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    rows, total = tidal_artist_overview_page("Aruzhu", path=database)

    assert total == 2
    assert rows == [
        {"id": "alpha", "name": "Alpha", "indexed_tracks": 2, "lastfm_plays": 3},
        {"id": "beta", "name": "Beta", "indexed_tracks": 1, "lastfm_plays": 1},
    ]


def test_artist_overview_search_sort_and_paging_are_sqlite_backed(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    rows, total = tidal_artist_overview_page(
        "Aruzhu", query="a", sort_field="indexed_tracks",
        sort_direction="desc", limit=1, offset=0, path=database,
    )

    assert total == 2
    assert [row["id"] for row in rows] == ["alpha"]
