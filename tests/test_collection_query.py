from __future__ import annotations

import pytest

from music_library.collection_query import (
    collection_relationships,
    collection_stats,
    collection_track_page,
    collection_track_page_with_stats,
)
from music_library.database import connect, initialize


def _seed(database):
    initialize(database)
    tracks = [
        ("one", "Alpha Song", "Artist One", "Club Remix", "Album A", 300, 120, "C", "minor", 2024),
        ("two", "Beta Song", "Artist Two", "", "Album B", 180, 125, "G", "major", 2023),
        ("three", "Gamma Song", "Artist One, Artist Three", "", "Album C", 420, 130, "D", "minor", 2022),
        ("four", "Delta Song", "Artist Four", "", "Album D", 240, 118, "A", "minor", 2021),
        ("five", "Epsilon Song", "Artist Five", "", "Album E", 360, 128, "E", "major", 2020),
    ]
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO tracks(
                provider, provider_track_id, title, artist, remix, album,
                duration_seconds, bpm, musical_key, key_scale, release_year,
                refreshed_at
            ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'now')
            """,
            tracks,
        )
        artists = [
            ("artist-one", "Artist One", "artist one"),
            ("artist-two", "Artist Two", "artist two"),
            ("artist-three", "Artist Three", "artist three"),
            ("artist-four", "Artist Four", "artist four"),
            ("artist-five", "Artist Five", "artist five"),
        ]
        connection.executemany(
            """
            INSERT INTO artists(provider, artist_key, name, normalized_name)
            VALUES('tidal', ?, ?, ?)
            """,
            artists,
        )
        connection.executemany(
            """
            INSERT INTO track_artists(
                provider, provider_track_id, artist_key, position
            ) VALUES('tidal', ?, ?, ?)
            """,
            [
                ("one", "artist-one", 0),
                ("two", "artist-two", 0),
                ("three", "artist-one", 0),
                ("three", "artist-three", 1),
                ("four", "artist-four", 0),
                ("five", "artist-five", 0),
            ],
        )
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', 'user', '2026-10-22T12:00:00')
            """
        )
        connection.executemany(
            """
            INSERT INTO liked_tracks(
                provider, provider_user_id, position, provider_track_id, date_added
            ) VALUES('tidal', 'user', ?, ?, ?)
            """,
            [
                (0, "one", "2026-01-02T12:00:00"),
                (1, "two", None),
                (2, "three", "2026-01-01T12:00:00"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO playlists(
                provider, provider_playlist_id, name, collection_type, indexed_at
            ) VALUES('tidal', ?, ?, ?, 'now')
            """,
            [
                ("playlist", "Playlist", "playlist"),
                ("event", "Event", "event"),
                ("source", "Source", "source"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO playlist_tracks(
                provider, provider_playlist_id, position, provider_track_id, date_added
            ) VALUES('tidal', ?, ?, ?, ?)
            """,
            [
                ("playlist", 0, "two", "2026-02-01"),
                ("playlist", 1, "three", "2026-02-02"),
                ("event", 0, "four", "2026-03-01"),
                ("source", 0, "five", "2026-04-01"),
            ],
        )
        connection.execute(
            """
            INSERT INTO setlists(
                folder_name, tidal_playlist_name, updated_at
            ) VALUES('my-mix', 'My setlist', 'now')
            """
        )
        connection.executemany(
            """
            INSERT INTO setlist_tracks(
                folder_name, position, provider_track_id, mix_position, date_added
            ) VALUES('my-mix', ?, ?, ?, ?)
            """,
            [
                (0, "one", "00:00", "2026-05-01"),
                (1, "four", "05:30", "2026-05-02"),
            ],
        )
        connection.execute(
            """
            INSERT INTO watched_mixes(
                video_id, youtube_url, title, channel_name, added_at
            ) VALUES('video', 'https://youtu.be/video', 'Watched title', 'DJ Channel', 'now')
            """
        )
        connection.executemany(
            """
            INSERT INTO watched_mix_tracks(
                video_id, position, provider_track_id, associated_at
            ) VALUES('video', ?, ?, ?)
            """,
            [
                (0, "one", "2026-06-01"),
                (1, "five", "2026-06-02"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO track_dimension_values(
                provider, provider_track_id, dimension, value, created_at
            ) VALUES('tidal', ?, ?, ?, 'now')
            """,
            [
                ("one", "rating", "5"),
                ("one", "vibe", "Dreamy"),
                ("two", "rating", "2"),
                ("two", "vibe", "Dark"),
                ("three", "rating", "4"),
                ("three", "vibe", "Dreamy"),
                ("three", "movement", "Rolling"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO lastfm_scrobbles(
                username, played_at, artist, title, normalized_artist,
                normalized_title, tidal_track_id, imported_at
            ) VALUES('aruzhu', ?, ?, ?, ?, ?, ?, 'now')
            """,
            [
                (100, "Artist One", "Alpha Song", "artist one", "alpha song", "one"),
                (200, "Artist One", "Alpha Song", "artist one", "alpha song", "one"),
                (300, "Artist One", "Gamma Song", "artist one", "gamma song", "three"),
            ],
        )


def _page(database, kind, collection_id, **kwargs):
    return collection_track_page(
        kind,
        collection_id,
        "Aruzhu",
        offset=kwargs.pop("offset", 0),
        limit=kwargs.pop("limit", 100),
        path=database,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("kind", "collection_id", "expected"),
    [
        ("liked", "liked", ["one", "two", "three"]),
        ("playlist", "playlist", ["two", "three"]),
        ("event", "event", ["four"]),
        ("source", "source", ["five"]),
        ("setlist", "my-mix", ["one", "four"]),
        ("watched_mix", "video", ["one", "five"]),
        ("artist", "artist-one", ["one", "three"]),
        ("search", "library", ["five", "four", "one", "three", "two"]),
    ],
)
def test_collection_page_supports_every_collection_type(
    tmp_path, kind, collection_id, expected,
):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    rows, total = _page(database, kind, collection_id)

    assert total == len(expected)
    assert [row["id"] for row in rows] == expected


def test_collection_page_filters_sorts_and_pages_before_enrichment(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    rows, total = _page(
        database,
        "liked",
        "liked",
        query="song",
        artists=["artist-one"],
        ratings=["4", "5"],
        tags=["vibe:Dreamy"],
        keys=["05A", "07A"],
        bpm_min=121,
        bpm_max=135,
        sort_field="bpm",
        sort_direction="desc",
        limit=1,
    )

    assert total == 1
    assert [row["id"] for row in rows] == ["three"]
    assert rows[0]["play_count"] == 1
    assert rows[0]["last_played"] == 300


def test_missing_sort_values_are_last_in_both_directions(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    ascending, _ = _page(
        database, "liked", "liked", sort_field="date_added", sort_direction="asc",
    )
    descending, _ = _page(
        database, "liked", "liked", sort_field="date_added", sort_direction="desc",
    )
    plays, _ = _page(
        database, "liked", "liked", sort_field="play_count", sort_direction="asc",
    )

    assert [row["id"] for row in ascending] == ["three", "one", "two"]
    assert [row["id"] for row in descending] == ["one", "three", "two"]
    assert [row["id"] for row in plays] == ["three", "one", "two"]


def test_global_collection_membership_filter_and_text_fields(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    event_rows, event_total = _page(
        database, "search", "library", collection_types=["event"],
    )
    artist_rows, artist_total = _page(
        database, "search", "library", query="artist five",
    )

    assert event_total == 1
    assert [row["id"] for row in event_rows] == ["four"]
    assert artist_total == 1
    assert [row["id"] for row in artist_rows] == ["five"]


def test_collection_stats_are_aggregated_from_the_filtered_scope(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    stats = collection_stats(
        "liked", "liked", "Aruzhu", tags=["vibe:Dreamy"], path=database,
    )

    assert stats["top_artists"] == [
        {"id": "artist-one", "name": "Artist One", "count": 2},
        {"id": "artist-three", "name": "Artist Three", "count": 1},
    ]
    assert stats["bpm_min"] == 120
    assert stats["bpm_max"] == 130
    assert stats["vibe"] == "Dreamy"
    assert stats["vibe_count"] == 2


def test_first_page_and_stats_share_one_repository_batch(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    rows, total, stats = collection_track_page_with_stats(
        "liked", "liked", "Aruzhu",
        offset=0, limit=2, sort_field="title", sort_direction="asc",
        path=database,
    )

    assert total == 3
    assert [row["id"] for row in rows] == ["one", "two"]
    assert stats["bpm_min"] == 120
    assert stats["bpm_max"] == 130


def test_relationships_are_loaded_in_one_bounded_result(tmp_path):
    database = tmp_path / "library.sqlite3"
    _seed(database)

    related = collection_relationships(["one", "three"], path=database)

    assert related["one"]["mixes"] == [{"id": "my-mix", "name": "My setlist"}]
    assert related["one"]["djmi"] == [
        {"id": "video", "name": "DJ Channel", "title": "Watched title"}
    ]
    assert related["one"]["dimensions"] == {
        "rating": ["5"], "vibe": ["Dreamy"],
    }
    assert related["three"]["playlists"] == [
        {"id": "playlist", "name": "Playlist", "collection_type": "playlist"}
    ]
    assert [artist["id"] for artist in related["three"]["artists"]] == [
        "artist-one", "artist-three",
    ]
