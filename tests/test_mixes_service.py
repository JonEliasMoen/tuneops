from types import SimpleNamespace

from music_tools.mixes import service


def _metadata(**overrides):
    return {
        "youtube_url": "https://youtu.be/abc123",
        "tidal_url": "https://tidal.com/playlist/playlist-id",
        "tidal_playlist_id": "playlist-id",
        "tidal_playlist_name": "djset darkprog",
        "updated_at": "2026-10-24T12:00:00+00:00",
        "track_count": 12,
        **overrides,
    }


def test_discover_mixes_uses_database_rows_without_local_folders(monkeypatch):
    monkeypatch.setattr(
        service,
        "setlist_metadata",
        lambda: {"darkprog": _metadata(), "flying": _metadata(track_count=8)},
    )

    mixes = service.discover_mixes()

    assert [mix.folder_name for mix in mixes] == ["darkprog", "flying"]
    assert [mix.track_count for mix in mixes] == [12, 8]


def test_mix_for_is_database_only(monkeypatch):
    monkeypatch.setattr(
        service,
        "setlist_metadata_for",
        lambda name: _metadata() if name == "darkprog" else {},
    )

    assert service.mix_for("darkprog").tidal_playlist_id == "playlist-id"
    assert service.mix_for("missing") is None
    assert service.mix_for("") is None


def test_tidal_mix_name_requires_an_exact_djset_prefix():
    assert service.tidal_mix_name("djset darkprog") == "darkprog"
    assert service.tidal_mix_name("  DJSET   My Set  ") == "My Set"
    assert service.tidal_mix_name("warmup djset darkprog") is None
    assert service.tidal_mix_name("djset") is None


def test_tidal_discovery_imports_new_sets_and_never_refetches_linked_sets(monkeypatch):
    imported: list[tuple[str, str, str, int]] = []

    class Playlist:
        def __init__(self, playlist_id, name, tracks):
            self.id = playlist_id
            self.name = name
            self._tracks = tracks
            self.track_calls = 0

        def tracks(self):
            self.track_calls += 1
            return self._tracks

    linked = Playlist("linked-id", "djset flying", [{"id": "should-not-load"}])
    fresh = Playlist("new-id", "DJSET darkprog", [{"id": "one"}, {"id": "two"}])
    ignored = Playlist("other-id", "Listening ideas", [{"id": "ignored"}])
    session = SimpleNamespace(user=SimpleNamespace(playlists=lambda: [linked, fresh, ignored]))
    engine = SimpleNamespace(
        tidal_client=lambda interactive=False: session,
        _call=lambda _provider, _action, function, **_details: function(),
    )
    monkeypatch.setattr(
        service,
        "discover_mixes",
        lambda: [
            service.Mix("flying", "", "", "linked-id", "djset flying"),
            service.Mix("DarkProg", "", "", "", ""),
        ],
    )
    monkeypatch.setattr(service, "tidal_track_record", lambda track: track)
    monkeypatch.setattr(
        service,
        "store_tidal_setlist",
        lambda name, url, playlist, records, positions: imported.append(
            (name, url, playlist.id, len(records))
        ),
    )

    result = service.discover_tidal_mixes(engine)

    assert imported == [("DarkProg", "https://tidal.com/playlist/new-id", "new-id", 2)]
    assert linked.track_calls == 0
    assert fresh.track_calls == 1
    assert result["scanned"] == 3
    assert result["candidates"] == 2
    assert result["imported"] == 1
    assert [row["status"] for row in result["results"]] == ["already_imported", "imported"]
