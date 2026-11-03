from __future__ import annotations

from types import SimpleNamespace

from backend.music_library.database import (
    connect,
    pending_lastfm_track_backfills,
    store_lastfm_track_playcount_snapshots,
    store_tidal_playlist,
)
from backend.music_tools.lastfm import service


def _record(track_id: str = "track-1") -> dict[str, object]:
    return {
        "id": track_id,
        "title": "A Track",
        "artist": "An Artist",
        "remix": "Extended Mix",
        "artists": [{"id": "artist-1", "name": "An Artist"}],
    }


def test_new_canonical_track_is_queued_once_and_snapshot_has_no_month(tmp_path):
    path = tmp_path / "library.sqlite3"
    playlist = SimpleNamespace(id="playlist-1", name="Playlist", last_updated=None)

    store_tidal_playlist(playlist, [_record()], path=path)
    store_tidal_playlist(playlist, [_record()], path=path)

    assert [row["id"] for row in pending_lastfm_track_backfills(path=path)] == [
        "track-1"
    ]
    result = store_lastfm_track_playcount_snapshots(
        "Aruzhu",
        [{"track_id": "track-1", "play_count": 12}],
        checked_track_ids=["track-1"],
        path=path,
    )

    assert result == {"checked": 1, "updated": 1, "plays_added": 12}
    assert pending_lastfm_track_backfills(path=path) == []
    with connect(path) as connection:
        total = connection.execute(
            "SELECT play_count FROM lastfm_track_totals WHERE tidal_track_id='track-1'"
        ).fetchone()[0]
        monthly = connection.execute(
            "SELECT COUNT(*) FROM lastfm_monthly_track_counts"
        ).fetchone()[0]
        imported = connection.execute(
            "SELECT matched_play_count FROM lastfm_import_state WHERE username='aruzhu'"
        ).fetchone()[0]
    assert (total, monthly, imported) == (12, 0, 12)


def test_snapshot_never_downgrades_an_incremental_total(tmp_path):
    path = tmp_path / "library.sqlite3"
    playlist = SimpleNamespace(id="playlist-1", name="Playlist", last_updated=None)
    store_tidal_playlist(playlist, [_record()], path=path)
    store_lastfm_track_playcount_snapshots(
        "Aruzhu",
        [{"track_id": "track-1", "play_count": 12}],
        checked_track_ids=["track-1"],
        path=path,
    )
    result = store_lastfm_track_playcount_snapshots(
        "Aruzhu",
        [{"track_id": "track-1", "play_count": 5}],
        checked_track_ids=[],
        path=path,
    )

    assert result["plays_added"] == 0
    with connect(path) as connection:
        assert connection.execute(
            "SELECT play_count FROM lastfm_track_totals WHERE tidal_track_id='track-1'"
        ).fetchone()[0] == 12


def test_provider_backfill_uses_remix_title_and_completes_zero_play_lookup(monkeypatch):
    captured: list[tuple[str, str, str]] = []
    stored: list[tuple[list[dict[str, object]], list[str]]] = []

    monkeypatch.setattr(
        service,
        "pending_lastfm_track_backfills",
        lambda limit: [_record()],
    )
    monkeypatch.setattr(service, "lastfm_latest_scrobble", lambda _username: 123)
    monkeypatch.setattr(
        service,
        "store_lastfm_track_playcount_snapshots",
        lambda _username, snapshots, *, checked_track_ids: stored.append(
            (snapshots, checked_track_ids)
        ) or {"checked": 1, "updated": 0, "plays_added": 0},
    )

    class FakeTrack:
        def __init__(self, artist, title, _network, username=None):
            captured.append((artist, title, username))

        def get_userplaycount(self):
            return 0

    monkeypatch.setattr(service.pylast, "Track", FakeTrack)
    monkeypatch.setattr(service, "_MusicSyncLastFMNetwork", lambda **_kwargs: object())

    result = service.backfill_new_track_playcounts("Aruzhu", "key", limit=10)

    assert captured == [("An Artist", "A Track (Extended Mix)", "Aruzhu")]
    assert stored == [([{"track_id": "track-1", "play_count": 0}], ["track-1"])]
    assert result == {"queued": 1, "checked": 1, "updated": 0, "plays_added": 0}


def test_provider_backfill_waits_for_full_import_watermark(monkeypatch):
    monkeypatch.setattr(service, "lastfm_latest_scrobble", lambda _username: None)
    monkeypatch.setattr(
        service,
        "pending_lastfm_track_backfills",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("queue must wait")),
    )

    assert service.backfill_new_track_playcounts("Aruzhu", "key") == {
        "queued": 0,
        "checked": 0,
        "updated": 0,
        "plays_added": 0,
    }


def test_lastfm_code_six_track_not_found_is_a_completed_zero_lookup(monkeypatch):
    stored: list[tuple[list[dict[str, object]], list[str]]] = []
    monkeypatch.setattr(service, "lastfm_latest_scrobble", lambda _username: 123)
    monkeypatch.setattr(
        service, "pending_lastfm_track_backfills", lambda limit: [_record()]
    )
    monkeypatch.setattr(
        service,
        "store_lastfm_track_playcount_snapshots",
        lambda _username, snapshots, *, checked_track_ids: stored.append(
            (snapshots, checked_track_ids)
        ) or {"checked": 1, "updated": 0, "plays_added": 0},
    )
    monkeypatch.setattr(service, "_MusicSyncLastFMNetwork", lambda **_kwargs: object())

    class MissingTrack:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_userplaycount(self):
            raise service.pylast.WSError(object(), 6, "Track not found")

    monkeypatch.setattr(service.pylast, "Track", MissingTrack)
    monkeypatch.setattr(
        service,
        "mark_lastfm_track_backfill_error",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a missing track must not remain queued")
        ),
    )

    result = service.backfill_new_track_playcounts("Aruzhu", "key")

    assert stored == [([{"track_id": "track-1", "play_count": 0}], ["track-1"])]
    assert result["checked"] == 1


def test_other_lastfm_code_six_errors_are_not_silently_discarded():
    error = service.pylast.WSError(object(), 6, "Invalid parameters")
    assert service._is_missing_track_error(error) is False
