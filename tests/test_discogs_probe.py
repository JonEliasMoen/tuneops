from __future__ import annotations

import probe_discogs as probe


TRACK = {
    "id": "1", "title": "Resonance", "artist": "Tatana",
    "remix": "Matan Caspi Remix", "album": "FGVIII", "year": 2019,
}


def test_release_score_uses_tracklist_artist_and_remix():
    release = {
        "title": "FGVIII", "year": 2019,
        "artists": [{"name": "Tatana"}],
        "tracklist": [{"title": "Resonance (Matan Caspi Remix)"}],
    }

    score, item = probe.score_release(TRACK, release)

    assert score == 100
    assert item["title"] == "Resonance (Matan Caspi Remix)"


def test_probe_returns_release_metadata_for_confident_match():
    class Client:
        def search(self, _track):
            return [{"id": 42}]

        def release(self, _release_id):
            return {
                "id": 42, "title": "FGVIII", "year": 2019,
                "artists": [{"name": "Tatana"}],
                "labels": [{"name": "Frisky Records"}],
                "genres": ["Electronic"], "styles": ["Progressive House"],
                "tracklist": [{"title": "Resonance (Matan Caspi Remix)"}],
            }

    result = probe.probe_track(Client(), TRACK)

    assert result["matched"] is True
    assert result["labels"] == ["Frisky Records"]
    assert result["styles"] == ["Progressive House"]


def test_probe_rejects_unrelated_tracklist():
    class Client:
        def search(self, _track):
            return [{"id": 99}]

        def release(self, _release_id):
            return {
                "id": 99, "title": "Other", "artists": [{"name": "Other"}],
                "tracklist": [{"title": "Different Song"}],
            }

    result = probe.probe_track(Client(), TRACK)

    assert result["matched"] is False
    assert result["best_score"] == 0
