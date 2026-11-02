from __future__ import annotations

from music_tools.mixes.service import Mix

from backend.app.services import mix_export


def test_one_shot_mix_export_uses_transient_mapping(monkeypatch):
    spotify = object()
    tidal = object()
    captured: dict[str, object] = {}
    messages: list[str] = []
    mix = Mix(
        folder_name="darkprog",
        youtube_url="",
        tidal_url="https://tidal.com/playlist/tidal-id",
        tidal_playlist_id="tidal-id",
        tidal_playlist_name="djset darkprog",
    )
    monkeypatch.setattr(mix_export.engine, "spotify_client", lambda: spotify)
    monkeypatch.setattr(
        mix_export.engine, "tidal_client", lambda interactive=False: tidal,
    )
    monkeypatch.setattr(
        mix_export.engine,
        "load_runtime_settings",
        lambda: {"spotify_search_delay_seconds": 0},
    )

    def sync(actual_spotify, actual_tidal, mapping, settings):
        captured.update(
            spotify=actual_spotify,
            tidal=actual_tidal,
            mapping=mapping,
            settings=settings,
        )
        mapping["spotify"] = "created-id"
        return mix_export.engine.SyncResult(
            source="TIDAL source", target="Spotify target", added=9, unmatched=2,
        )

    monkeypatch.setattr(mix_export.engine, "sync_tidal_to_spotify", sync)
    monkeypatch.setattr(
        mix_export.engine,
        "save_sync_mappings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("one-shot export must not save mappings")
        ),
    )

    result = mix_export.export_mix_to_spotify(mix, progress=messages.append)

    assert captured["spotify"] is spotify
    assert captured["tidal"] is tidal
    assert captured["mapping"]["tidal"] == "tidal-id"
    assert captured["mapping"]["spotify"] == "created-id"
    assert result["spotify_playlist_url"] == "https://open.spotify.com/playlist/created-id"
    assert result["added"] == 9
    assert result["unmatched"] == 2
    assert messages[-1] == "Spotify export complete: 9 added, 2 unmatched"
