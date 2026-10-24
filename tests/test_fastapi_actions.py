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
        self.user = type("User", (), {"id": "user-1", "favorites": type("Favorites", (), {"added": [], "add_track": lambda self, track_id: self.added.append(track_id)})()})()

    def playlist(self, playlist_id):
        return self.playlists[playlist_id]


def _setup(monkeypatch, memberships, playlists):
    indexed = [
        {"id": playlist_id, "name": playlist_id, "collection_type": "playlist"}
        for playlist_id in playlists
    ]
    monkeypatch.setattr(
        actions,
        "tidal_indexed_playlist",
        lambda playlist_id: next((item for item in indexed if item["id"] == playlist_id), None),
    )
    monkeypatch.setattr(actions, "tidal_playlists_for_tracks", lambda ids: {track_id: memberships.get(track_id, []) for track_id in ids})
    monkeypatch.setattr(actions.engine, "tidal_client", lambda interactive=False: FakeSession(playlists))
    monkeypatch.setattr(actions.engine, "_call", lambda _provider, _action, callback, **_context: callback())


def test_add_skips_existing_membership_and_updates_cache_after_provider(monkeypatch):
    destination = FakePlaylist("destination")
    _setup(monkeypatch, {"one": [{"id": "destination"}], "two": []}, {"destination": destination})
    cached: list[tuple[str, str]] = []
    monkeypatch.setattr(
        actions,
        "apply_tidal_playlist_membership_changes",
        lambda _action, playlist_id, track_ids, _source=None: cached.extend(
            (playlist_id, track_id) for track_id in track_ids
        ),
    )

    result = actions.mutate_playlist_tracks("add", ["one", "two"], "destination")

    assert destination.added == ["two"]
    assert cached == [("destination", "two")]
    assert result["changed"] == 1
    assert result["skipped"] == 1


def test_move_rolls_back_destination_when_source_remove_fails(monkeypatch):
    destination = FakePlaylist("destination")
    source = FakePlaylist("source", fail_remove=True)
    _setup(monkeypatch, {"track": [{"id": "source"}]}, {"destination": destination, "source": source})
    monkeypatch.setattr(actions, "apply_tidal_playlist_membership_changes", lambda *_: pytest.fail("cache must not update"))

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
    monkeypatch.setattr(
        actions,
        "apply_tidal_playlist_membership_changes",
        lambda _action, playlist_id, track_ids, _source=None: cached.extend(
            (playlist_id, track_id) for track_id in track_ids
        ),
    )
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


def test_like_tracks_skips_cached_likes_and_mirrors_provider_success(monkeypatch):
    session = FakeSession({})
    monkeypatch.setattr(actions.engine, "tidal_client", lambda interactive=False: session)
    monkeypatch.setattr(actions.engine, "_call", lambda _provider, _action, callback, **_context: callback())
    monkeypatch.setattr(actions, "tidal_liked_membership_ids", lambda user_id, ids: {"already"})
    monkeypatch.setattr(actions, "tidal_tracks_by_ids", lambda ids: {track_id: {"id": track_id} for track_id in ids})
    cached = []
    monkeypatch.setattr(actions, "add_tidal_liked_memberships", lambda user_id, ids: cached.extend((user_id, track_id) for track_id in ids))

    result = actions.like_tidal_tracks(["already", "new", "new"])

    assert session.user.favorites.added == ["new"]
    assert cached == [("user-1", "new")]
    assert result == {"changed": 1, "skipped": 1, "failed": 0, "message": "Liked 1 track in TIDAL. 1 already liked."}
