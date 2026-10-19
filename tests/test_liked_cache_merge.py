from __future__ import annotations

from types import SimpleNamespace

from music_library.database import (
    connect,
    initialize,
    merge_tidal_liked_tracks_prefix,
)


USER_ID = "tidal-user"


def _track(track_id: str):
    artist = SimpleNamespace(id=f"artist-{track_id}", name="Artist")
    album = SimpleNamespace(name="Album", release_date=None, image=lambda _size: "")
    return SimpleNamespace(
        id=track_id,
        name=f"Track {track_id}",
        artists=[artist],
        artist=artist,
        album=album,
        version="",
        duration=300,
        bpm=120,
        key="A",
        key_scale="minor",
        isrc="",
        user_date_added=None,
        date_added=None,
    )


def _seed(path, track_ids: list[str]) -> None:
    initialize(path)
    with connect(path) as connection:
        for position, track_id in enumerate(track_ids):
            connection.execute(
                """
                INSERT INTO tracks(
                    provider, provider_track_id, title, artist, refreshed_at
                ) VALUES('tidal', ?, ?, 'Artist', 'now')
                """,
                (track_id, f"Track {track_id}"),
            )
            connection.execute(
                """
                INSERT INTO liked_tracks(
                    provider, provider_user_id, position, provider_track_id, date_added
                ) VALUES('tidal', ?, ?, ?, ?)
                """,
                (USER_ID, position, track_id, f"date-{track_id}"),
            )


def _memberships(path) -> list[tuple[str, str | None]]:
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT provider_track_id, date_added FROM liked_tracks
            WHERE provider='tidal' AND provider_user_id=? ORDER BY position
            """,
            (USER_ID,),
        ).fetchall()
    return [(row["provider_track_id"], row["date_added"]) for row in rows]


def test_prefix_merge_preserves_cached_tail_without_rebuilding_it(tmp_path):
    path = tmp_path / "library.sqlite3"
    _seed(path, ["a", "b", "c", "d"])

    result = merge_tidal_liked_tracks_prefix(
        USER_ID, [_track("new"), _track("b")], "b", path=path
    )

    assert [track_id for track_id, _date in _memberships(path)] == [
        "new", "b", "c", "d"
    ]
    assert dict(_memberships(path))["c"] == "date-c"
    assert result == {"fetched": 2, "added": 1, "cached": 4}


def test_prefix_merge_prepends_unknown_page_when_no_boundary_was_found(tmp_path):
    path = tmp_path / "library.sqlite3"
    _seed(path, ["a", "b"])

    result = merge_tidal_liked_tracks_prefix(
        USER_ID, [_track("new-1"), _track("new-2")], None, path=path
    )

    assert [track_id for track_id, _date in _memberships(path)] == [
        "new-1", "new-2", "a", "b"
    ]
    assert result["cached"] == 4


def test_complete_scan_replaces_the_old_cache(tmp_path):
    path = tmp_path / "library.sqlite3"
    _seed(path, ["a", "b", "c"])

    result = merge_tidal_liked_tracks_prefix(
        USER_ID,
        [_track("b")],
        "b",
        preserve_unscanned_tail=False,
        path=path,
    )

    assert [track_id for track_id, _date in _memberships(path)] == ["b"]
    assert result == {"fetched": 1, "added": 0, "cached": 1}
