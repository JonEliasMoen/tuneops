from __future__ import annotations

import pytest

from backend.app.services import actions


class FakePlaylist:
    def __init__(self, playlist_id: str, *, fail_remove: bool = False):
        self.id = playlist_id
        self.name = playlist_id
        self.fail_remove = fail_remove
        self.added: list[str] = []
        self.removed: list[str] = []

    def add(self, track_ids, allow_duplicates=False):
        self.added.extend(track_ids)
        return list(track_ids)

    def remove_by_id(self, track_id):
        if self.fail_remove:
            raise RuntimeError("remove failed")
        self.removed.append(track_id)
        return True


class FakeSession:
    def __init__(self, playlists):
        self.playlists = playlists

    def playlist(self, playlist_id):
        return self.playlists[playlist_id]


def _setup(monkeypatch, memberships, playlists):
    indexed = [
        {"id": playlist_id, "name": playlist_id, "collection_type": "playlist"}
        for playlist_id in playlists
    ]
    monkeypatch.setattr(actions, "tidal_indexed_playlists", lambda: indexed)
    monkeypatch.setattr(actions, "tidal_playlists_for_tracks", lambda ids: {track_id: memberships.get(track_id, []) for track_id in ids})
    monkeypatch.setattr(actions.engine, "tidal_client", lambda interactive=False: FakeSession(playlists))
    monkeypatch.setattr(actions.engine, "_call", lambda _provider, _action, callback, **_context: callback())


def test_add_skips_existing_membership_and_updates_cache_after_provider(monkeypatch):
    destination = FakePlaylist("destination")
    _setup(monkeypatch, {"one": [{"id": "destination"}], "two": []}, {"destination": destination})
    cached: list[tuple[str, str]] = []
    monkeypatch.setattr(actions, "add_tidal_playlist_membership", lambda playlist_id, track_id: cached.append((playlist_id, track_id)))

    result = actions.mutate_playlist_tracks("add", ["one", "two"], "destination")

    assert destination.added == ["two"]
    assert cached == [("destination", "two")]
    assert result["changed"] == 1
    assert result["skipped"] == 1


def test_move_rolls_back_destination_when_source_remove_fails(monkeypatch):
    destination = FakePlaylist("destination")
    source = FakePlaylist("source", fail_remove=True)
    _setup(monkeypatch, {"track": [{"id": "source"}]}, {"destination": destination, "source": source})
    monkeypatch.setattr(actions, "add_tidal_playlist_membership", lambda *_: pytest.fail("cache must not update"))
    monkeypatch.setattr(actions, "remove_tidal_playlist_membership", lambda *_: pytest.fail("cache must not update"))

    result = actions.mutate_playlist_tracks("move", ["track"], "destination", "source")

    assert destination.added == ["track"]
    assert destination.removed == ["track"]
    assert result["changed"] == 0
    assert result["failed"] == 1
    assert "successful changes were kept" in result["message"]


def test_bulk_action_reports_partial_failures_and_keeps_successful_cache_updates(monkeypatch):
    destination = FakePlaylist("destination")
    _setup(monkeypatch, {"one": [], "two": []}, {"destination": destination})
    cached: list[tuple[str, str]] = []
    monkeypatch.setattr(actions, "add_tidal_playlist_membership", lambda playlist_id, track_id: cached.append((playlist_id, track_id)))
    original_add = destination.add

    def add(track_ids, allow_duplicates=False):
        if track_ids == ["two"]:
            raise RuntimeError("temporary provider failure")
        return original_add(track_ids, allow_duplicates)

    destination.add = add
    result = actions.mutate_playlist_tracks("add", ["one", "two"], "destination")

    assert destination.added == ["one"]
    assert cached == [("destination", "one")]
    assert result["changed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 0
