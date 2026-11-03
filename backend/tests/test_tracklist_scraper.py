from __future__ import annotations

import pytest

from backend.music_tools.tracklist import Tracklist
from backend.music_tools.tracklist import scraper
from backend.music_tools.tracklist.service import fetch_staging_tracklist


class Response:
    def __init__(
        self,
        text: str = "",
        payload=None,
        status_code: int = 200,
        headers=None,
    ):
        self.text = text
        self.content = text.encode("utf-8")
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise scraper.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def test_tracklist_package_import_has_no_network_side_effects():
    tracklist = Tracklist(
        "https://www.1001tracklists.com/tracklist/example/test.html",
        fetch=False,
    )

    assert tracklist.tracklist_id == "example"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.1001tracklists.com/tracklist/example/test.html",
        "https://1001tracklists.com.example.test/tracklist/example/test.html",
        "https://example.test/?next=https://www.1001tracklists.com/",
    ],
)
def test_scraper_rejects_non_allowlisted_urls(url):
    with pytest.raises(ValueError):
        scraper.get_soup(url)


def test_scraper_identifies_turnstile_challenge(monkeypatch):
    challenge = """
      <html><head><title>1001Tracklists</title>
      <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
      </head><body><input name="captcha" value="1"></body></html>
    """
    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *_args, **_kwargs: Response(challenge, status_code=206),
    )

    with pytest.raises(
        scraper.TracklistScrapeError,
        match="interactive browser verification",
    ):
        scraper.get_soup(
            "https://www.1001tracklists.com/tracklist/example/test.html"
        )


def test_scraper_uses_timeout_and_desktop_browser_headers(monkeypatch):
    captured = {}
    generated_headers = {
        "User-Agent": "Mozilla/5.0 test browser",
        "Referer": "https://google.com",
    }

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response("<html><head><title>Mix</title></head></html>")

    monkeypatch.setattr(scraper.requests, "get", get)
    monkeypatch.setattr(scraper, "_browser_headers", lambda: generated_headers)

    soup = scraper.get_soup(
        "https://www.1001tracklists.com/tracklist/example/test.html"
    )

    assert soup.title.string == "Mix"
    assert captured["timeout"] == scraper.REQUEST_TIMEOUT_SECONDS
    assert captured["headers"] == generated_headers


def test_partial_tracklist_page_without_metadata_still_loads_tracks(monkeypatch):
    partial_html = """
      <div class="tlpItem">
        <span class="trackValue">Artist - Track title</span>
        <div class="cue">01:23</div>
      </div>
    """
    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *_args, **_kwargs: Response(partial_html, status_code=206),
    )

    tracklist = Tracklist(
        "https://www.1001tracklists.com/tracklist/example/test.html"
    )

    assert tracklist.title == ""
    assert tracklist.DJs == []
    assert len(tracklist.tracks) == 1
    assert tracklist.tracks[0].full_title == "Artist - Track title"
    assert tracklist.tracks[0].cue == "01:23"


def test_incomplete_metadata_pane_does_not_block_tracks(monkeypatch):
    partial_html = """
      <div id="csLeft">Partial metadata without track counts</div>
      <div class="tlpItem">
        <span class="trackValue">Artist - Track title</span>
        <div class="cue">04:56</div>
      </div>
    """
    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *_args, **_kwargs: Response(partial_html, status_code=206),
    )

    tracklist = Tracklist(
        "https://www.1001tracklists.com/tracklist/example/test.html"
    )

    assert [track.full_title for track in tracklist.tracks] == [
        "Artist - Track title"
    ]
    assert tracklist.num_tracks == 0


def test_search_result_is_normalized_to_1001tracklists(monkeypatch):
    monkeypatch.setattr(
        scraper.requests,
        "post",
        lambda *_args, **_kwargs: Response(
            '<a href="/tracklist/result-id/example.html">Result</a>'
        ),
    )

    tracklist = Tracklist("https://youtu.be/video-id", fetch=False)

    assert tracklist.url == (
        "https://www.1001tracklists.com/tracklist/result-id/example.html"
    )
    assert tracklist.tracklist_id == "result-id"


def test_scraped_track_names_and_cues_become_staging_rows(caplog):
    class ScrapedTracklist:
        url = "https://www.1001tracklists.com/tracklist/result-id/example.html"
        tracks = [
            type("Track", (), {"cue": "01:23", "full_title": "Artist - Track"})(),
            type("Track", (), {"cue": "1:02:03", "full_title": "Other - ID"})(),
        ]

    with caplog.at_level("INFO", logger="musicsync"):
        result = fetch_staging_tracklist(
            "https://youtu.be/video-id",
            tracklist_factory=lambda _url: ScrapedTracklist(),
        )

    assert result["tracks_found"] == 2
    assert result["searchable"] == 1
    assert result["rows"][0] == {
        "row_id": 1000,
        "raw_line": "01:23 Artist - Track",
        "timestamp": "01:23",
        "artist": "Artist",
        "title": "Track",
        "status": "unsearched",
        "matches": [],
        "selected_id": "",
    }
    assert result["rows"][1]["timestamp"] == "1:02:03"
    assert result["rows"][1]["status"] == "unresolved"
    assert "tracklist.import start" in caplog.text
    assert "staging_rows=2 searchable=1 cues=2" in caplog.text
