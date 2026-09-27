from __future__ import annotations

import probe_musicbrainz as probe


def test_missing_isrc_falls_back_to_conservative_title_artist_search(monkeypatch):
    monkeypatch.setattr(
        probe.musicbrainzngs,
        "get_recordings_by_isrc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("HTTP Error 404: Not Found")),
    )
    monkeypatch.setattr(
        probe.musicbrainzngs,
        "search_recordings",
        lambda **_kwargs: {
            "recording-list": [{
                "id": "recording-id",
                "title": "Hyper Shift",
                "ext:score": "100",
                "artist-credit": [{"artist": {"name": "Mauro Somm"}}],
            }]
        },
    )

    candidates, method, warnings = probe._recording_candidates({
        "id": "1", "title": "Hyper Shift", "artist": "Mauro Somm", "isrc": "GBLV62011292",
    })

    assert method == "title_artist"
    assert candidates[0]["id"] == "recording-id"
    assert warnings == []


def test_title_artist_fallback_rejects_low_confidence_result(monkeypatch):
    monkeypatch.setattr(probe.musicbrainzngs, "get_recordings_by_isrc", lambda *_args, **_kwargs: {"isrc": {"recording-list": []}})
    monkeypatch.setattr(probe.musicbrainzngs, "search_recordings", lambda **_kwargs: {
        "recording-list": [{
            "id": "wrong", "title": "Hyper Shift", "ext:score": "72",
            "artist-credit": [{"artist": {"name": "Someone Else"}}],
        }]
    })

    candidates, method, _warnings = probe._recording_candidates({
        "id": "1", "title": "Hyper Shift", "artist": "Mauro Somm", "isrc": "missing",
    })

    assert candidates == []
    assert method == "title_artist"
