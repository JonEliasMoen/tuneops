from types import SimpleNamespace

from backend.music_tools import tidal_matching


def test_find_tidal_matches_normalizes_and_ranks_title_and_artist(monkeypatch):
    tracks = [
        {"id": "partial", "title": "Solar Stone (Extended Mix)", "artist": "Solarstone"},
        {"id": "exact", "title": "Solar Stone", "artist": "Solarstone"},
        {"id": "other", "title": "Solar Stone", "artist": "Other Artist"},
    ]
    calls = []

    class Session:
        def search(self, query, models, limit):
            calls.append((query, models, limit))
            return {"tracks": tracks}

    class Engine:
        @staticmethod
        def _call(provider, action, function, **details):
            assert (provider, action) == ("tidal", "track_search")
            assert details == {"query": "Solarstone Sólar-Stone", "limit": 5}
            return function()

    monkeypatch.setattr(tidal_matching, "tidal_track_record", lambda track: dict(track))
    monkeypatch.setitem(
        __import__("sys").modules,
        "tidalapi",
        SimpleNamespace(Track=object()),
    )

    result = tidal_matching.find_tidal_matches(
        Engine(), Session(), {"artist": "Solarstone", "title": "Sólar-Stone"}
    )

    assert [item["id"] for item in result] == ["exact", "partial", "other"]
    assert [item["score"] for item in result] == [10, 7, 6]
    assert result[0]["label"] == "Solarstone — Solar Stone"
    assert calls == [("Solarstone Sólar-Stone", [__import__("sys").modules["tidalapi"].Track], 5)]
