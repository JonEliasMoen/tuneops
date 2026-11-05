from __future__ import annotations

from backend.app.api import charts
from backend.app.schemas import BeatportChartReference
from backend.music_tools.beatport.beatport import BeatportClient
from backend.music_library.database import connect, initialize, tidal_tracks_by_isrcs


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")

    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "refresh-anon-token" in url:
            return Response({"access_token": "anon", "expires_in": 600})
        if url.endswith("genres/"):
            return Response({"results": [
                {"id": 12, "name": "Progressive House", "slug": "progressive-house"},
                {"id": 13, "name": "Drum & Bass", "slug": "drum-and-bass"},
            ]})
        if url.endswith("search/"):
            return Response({
                "labels": [{"id": 42, "name": "Colorize", "slug": "colorize"}],
                "artists": [{"id": 84, "name": "Nora En Pure", "slug": "nora-en-pure"}],
            })
        if url.endswith("tracks/"):
            return Response({"count": 30, "page": "2/2", "per_page": 25, "next": None, "results": [{
                "id": 11, "name": "Recent Track", "publish_date": "2026-11-05",
                "artists": [{"name": "Artist"}], "genre": {"name": "Progressive House"},
                "release": {"label": {"name": "Colorize"}},
            }]})
        return Response({"count": 100, "page": kwargs.get("params", {}).get("page", "1"),
                         "per_page": 10, "next": "page-2", "results": [{
            "id": 9, "name": "Track", "mix_name": "Extended Mix", "bpm": 124,
            "artists": [{"name": "Artist"}], "key": {"camelot_number": 8, "camelot_letter": "A"},
            "release": {"label": {"id": 42, "name": "Colorize"}}, "genre": {"name": "Progressive House"},
            "isrc": "GB-TEST", "new_release_date": "2026-11-01",
        }]})


class PersistentCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, ttl_seconds):
        assert ttl_seconds > 0
        self.values[key] = value


def test_type_driven_client_reuses_token_and_cached_response():
    session = Session()
    beatport = BeatportClient(session=session, cache_seconds=300)

    first = beatport.search("labels", "Colorize")
    second = beatport.search("labels", "Colorize")

    assert first == second == [{"id": "42", "name": "Colorize", "type": "labels", "slug": "colorize"}]
    assert len(session.calls) == 2  # one token request and one catalogue request
    assert session.calls[1][1]["params"] == {"q": "Colorize", "type": "labels"}


def test_new_client_reuses_persistent_provider_response_without_http():
    persistent = PersistentCache()
    first_session = Session()
    first = BeatportClient(
        session=first_session,
        cache_seconds=300,
        persistent_cache=persistent,
    )
    expected = first.search("labels", "Colorize")
    assert len(first_session.calls) == 2

    second_session = Session()
    second = BeatportClient(
        session=second_session,
        cache_seconds=300,
        persistent_cache=persistent,
    )

    assert second.search("labels", "Colorize") == expected
    assert second_session.calls == []


def test_genre_search_uses_bounded_cached_catalogue():
    session = Session()
    beatport = BeatportClient(session=session, cache_seconds=300)

    rows = beatport.search("genres", "progressive")

    assert rows == [{"id": "12", "name": "Progressive House", "type": "genres", "slug": "progressive-house"}]
    assert session.calls[1][1]["params"] == {"page": "1", "per_page": "100"}


def test_artist_search_uses_public_search_endpoint():
    session = Session()
    beatport = BeatportClient(session=session, cache_seconds=300)

    rows = beatport.search("artists", "Nora En Pure")

    assert rows == [{"id": "84", "name": "Nora En Pure", "type": "artists", "slug": "nora-en-pure"}]
    assert session.calls[1][1]["params"] == {"q": "Nora En Pure", "type": "artists"}


def test_track_chart_normalizes_camelot_and_metadata():
    beatport = BeatportClient(session=Session())

    result = beatport.top_tracks("labels", "42", page=2, chart_size=100)
    rows = result["items"]

    assert rows[0]["key"] == "08A"
    assert rows[0]["label"] == "Colorize"
    assert rows[0]["label_id"] == "42"
    assert rows[0]["artists"] == "Artist"
    assert result["total"] == 100
    assert result["has_more"] is True
    assert result["page"] == 2


def test_global_top_chart_uses_tracks_top_path():
    session = Session()
    beatport = BeatportClient(session=session)

    result = beatport.top_tracks("tracks", "top", page=3, chart_size=100)

    assert result["items"][0]["title"] == "Track"
    assert session.calls[1][0].endswith("/tracks/top/100")
    assert session.calls[1][1]["params"] == {"page": "3"}


def test_explicit_tidal_isrc_lookup_returns_temporary_play_target(monkeypatch):
    class Artist:
        id = "artist-1"
        name = "Artist"

    class Track:
        id = "tidal-123"
        name = "Found Track"
        version = ""
        artists = [Artist()]
        artist = Artist()
        album = None
        duration = 180
        bpm = 124
        key = "A"
        key_scale = "MINOR"
        isrc = "GBABC1234567"

    class Tidal:
        def get_tracks_by_isrc(self, isrc):
            assert isrc == "GBABC1234567"
            return [Track()]

    monkeypatch.setattr(charts.engine, "tidal_client", lambda interactive=False: Tidal())

    result = charts.search_tidal_by_isrc("gb-abc-12-34567")

    assert result == {
        "isrc": "GBABC1234567",
        "track": {
            "id": "tidal-123",
            "title": "Found Track",
            "artist": "Artist",
            "tidal_uri": "tidal://track/tidal-123",
        },
    }


def test_recent_tracks_uses_singular_provider_filter_and_pagination():
    session = Session()
    beatport = BeatportClient(session=session)

    result = beatport.recent_tracks("genres", "15", page=2, per_page=25)

    assert result["items"][0]["title"] == "Recent Track"
    assert result["items"][0]["release_date"] == "2026-11-05"
    assert result["has_more"] is False
    assert result["page"] == 2
    assert session.calls[1][1]["params"] == {
        "order_by": "-publish_date", "genre_id": "15", "page": "2", "per_page": "25",
    }


def test_following_chart_uses_existing_settings_document(monkeypatch):
    config = {"settings": {"dark_mode": True}, "quick_views": [], "mix_quick_views": []}
    saved = []
    monkeypatch.setattr(charts.engine, "load_runtime_settings", lambda: config["settings"])
    monkeypatch.setattr(charts.engine, "load_settings_config", lambda: config)
    monkeypatch.setattr(charts.engine, "save_settings_config", lambda value: saved.append(value))
    monkeypatch.setattr(charts, "invalidate_navigation_snapshot", lambda: None)

    result = charts.follow_chart(BeatportChartReference(type="genres", id="12", name="Progressive House"))

    assert result["items"] == [{"type": "genres", "id": "12", "name": "Progressive House"}]
    assert config["settings"]["dark_mode"] is True
    assert saved[0] is config


def test_chart_detail_attaches_local_tidal_match_by_isrc(monkeypatch):
    monkeypatch.setattr(charts, "_followed", lambda: [
        {"type": "genres", "id": "15", "name": "Progressive House"},
    ])
    monkeypatch.setattr(charts.client, "top_tracks", lambda *_args, **_kwargs: {
        "items": [{"id": "beatport-1", "title": "Track", "isrc": "GB-ABC-12-34567"}],
        "has_more": False, "total": 1, "page": 1, "per_page": 10,
    })
    monkeypatch.setattr(charts, "matched_tidal_tracks_by_isrc", lambda values: {
        "GBABC1234567": {"id": "tidal-1", "title": "Track", "tidal_uri": "tidal://track/tidal-1"},
    })

    result = charts.chart_detail("genres", "15", mode="top", offset=0, limit=25)

    assert result["items"][0]["tidal_track"]["id"] == "tidal-1"


def test_top_chart_exposes_bounded_second_page(monkeypatch):
    monkeypatch.setattr(charts, "_followed", lambda: [])
    calls = []
    def top_tracks(*_args, page, chart_size, **_kwargs):
        calls.append((page, chart_size))
        start = (page - 1) * 10 + 1
        return {
            "items": [{"id": str(position), "position": position, "isrc": ""}
                      for position in range(start, start + 10)],
            "has_more": page < 10, "total": 100, "page": page, "per_page": 10,
        }
    monkeypatch.setattr(charts.client, "top_tracks", top_tracks)
    monkeypatch.setattr(charts, "matched_tidal_tracks_by_isrc", lambda _values: {})

    result = charts.chart_detail("genres", "15", mode="top", offset=20, limit=10)

    assert [item["position"] for item in result["items"]] == list(range(21, 31))
    assert result["has_more"] is True
    assert result["total"] == 100
    assert result["limit"] == 10
    assert calls == [(3, 100)]


def test_global_top_chart_uses_fixed_tracks_reference(monkeypatch):
    monkeypatch.setattr(charts, "_followed", lambda: [
        {"type": "tracks", "id": "top", "name": "Top Beatport"},
    ])
    calls = []
    monkeypatch.setattr(charts.client, "top_tracks", lambda kind, identifier, **kwargs: (
        calls.append((kind, identifier, kwargs)) or {
            "items": [{"id": "1", "position": 1, "isrc": ""}],
            "has_more": True, "total": 100, "page": 1, "per_page": 10,
        }
    ))
    monkeypatch.setattr(charts, "matched_tidal_tracks_by_isrc", lambda _values: {})

    result = charts.chart_detail("tracks", "top", mode="top", offset=0, limit=10)

    assert result["chart"]["name"] == "Top Beatport"
    assert result["has_more"] is True
    assert calls == [("tracks", "top", {"page": 1, "chart_size": 100})]


def test_cached_tidal_tracks_match_normalized_isrc_and_choose_stable_id(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    with connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO tracks(provider, provider_track_id, title, isrc, refreshed_at)
            VALUES('tidal', ?, ?, ?, '2026-11-05T00:00:00Z')
            """,
            [("20", "Later", "GBABC1234567"), ("10", "Preferred", "GB-ABC-12-34567")],
        )

    result = tidal_tracks_by_isrcs(["gbabc1234567"], database)

    assert result["GBABC1234567"]["id"] == "10"
