from __future__ import annotations

from types import SimpleNamespace

from backend.app.api import youtube as youtube_api
from music_tools.youtube_analytics import service


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FailedResponse(Response):
    def raise_for_status(self):
        import requests
        raise requests.HTTPError("403 Forbidden")


def test_authorization_url_requests_read_only_scopes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8081/api/v1/youtube/callback")

    url = service.authorization_url("csrf-state")

    assert "client_id=client-id" in url
    assert "youtube.readonly" in url
    assert "yt-analytics.readonly" in url
    assert "state=csrf-state" in url


def test_query_video_analytics_maps_header_names_to_video_rows(monkeypatch):
    monkeypatch.setattr(service, "access_token", lambda: "access-token")
    monkeypatch.setattr(
        service.requests,
        "get",
        lambda *_args, **_kwargs: Response({
            "columnHeaders": [
                {"name": "video"}, {"name": "views"},
                {"name": "estimatedMinutesWatched"},
            ],
            "rows": [["video-id", 42, 120]],
        }),
    )

    result = service.query_video_analytics(["video-id"])

    assert result == {"video-id": {
        "video": "video-id", "views": 42, "estimatedMinutesWatched": 120,
    }}


def test_query_video_titles_batches_and_caches_titles(monkeypatch):
    monkeypatch.setattr(service, "access_token", lambda: "access-token")
    monkeypatch.setattr(
        service.requests,
        "get",
        lambda *_args, **_kwargs: Response({
            "items": [{"id": "video-id", "snippet": {"title": "Dark Progressive Mix", "publishedAt": "2026-01-05T12:30:00Z"}, "contentDetails": {"duration": "PT1H2M3S"}}],
        }),
    )

    result = service.query_video_titles(["video-id"])

    assert result == {"video-id": "Dark Progressive Mix"}
    assert service.cached_video_title("video-id") == "Dark Progressive Mix"
    assert service.cached_video_upload_date("video-id") == "2026-01-05"
    assert service.cached_video_duration_seconds("video-id") == 3723


def test_query_video_titles_falls_back_to_public_oembed(monkeypatch):
    monkeypatch.setattr(service, "access_token", lambda: "access-token")

    def get(url, **_kwargs):
        if url == service.VIDEOS_URL:
            return FailedResponse({})
        return Response({"title": "Public Mix Title"})

    monkeypatch.setattr(service.requests, "get", get)

    assert service.query_video_titles(["fallback-id"]) == {
        "fallback-id": "Public Mix Title",
    }


def test_analytics_refresh_matches_owned_video_results_to_mix_folders(monkeypatch):
    registry = SimpleNamespace()
    captured = {}

    class ImmediateJobs:
        def submit(self, kind, function):
            result = function(lambda _message: None)
            return SimpleNamespace(
                id="job", kind=kind, state="succeeded", phase="", current=0,
                total=None, message="", result=result, error="", created_at="now",
                started_at=None, finished_at=None,
            )

        @staticmethod
        def snapshot(job):
            return vars(job)

    registry = ImmediateJobs()
    monkeypatch.setattr(youtube_api, "JOBS", registry)
    monkeypatch.setattr(youtube_api.service, "status", lambda: {"connected": True})
    monkeypatch.setattr(
        youtube_api,
        "discover_mixes",
        lambda: [SimpleNamespace(folder_name="darkprog", youtube_url="https://youtu.be/video-id")],
    )
    monkeypatch.setattr(youtube_api, "youtube_video_id", lambda _url: "video-id")
    monkeypatch.setattr(
        youtube_api.service,
        "query_video_analytics",
        lambda ids: {"video-id": {"video": "video-id", "views": 42}} if ids == ["video-id"] else {},
    )
    monkeypatch.setattr(youtube_api.service, "query_video_titles", lambda ids: {ids[0]: "Darkprog"})
    monkeypatch.setattr(
        youtube_api,
        "store_youtube_mix_analytics",
        lambda records: captured.update(records=records) or len(records),
    )
    monkeypatch.setattr(
        youtube_api,
        "store_youtube_video_metadata",
        lambda records: captured.update(metadata=records) or len(records),
    )
    monkeypatch.setattr(youtube_api, "youtube_video_metadata", lambda: {})
    monkeypatch.setattr(
        youtube_api,
        "fetch_youtube_metadata",
        lambda _url: SimpleNamespace(title="Public title", upload_date="2026-01-05"),
    )

    response = youtube_api.refresh_youtube_analytics()

    assert response.state == "succeeded"
    assert response.result == {"requested": 1, "matched": 1, "stored": 1}
    assert captured["records"][0]["folder_name"] == "darkprog"
    assert captured["metadata"][0]["title"] == "Darkprog"
    assert captured["metadata"][0]["upload_date"] == "2026-01-05"


def test_youtube_callback_returns_to_settings(monkeypatch):
    monkeypatch.setattr(youtube_api.service, "exchange_code", lambda _code: None)

    response = youtube_api.youtube_callback(
        code="authorization-code",
        state="expected-state",
        error="",
        stored_state="expected-state",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?youtube=connected"
