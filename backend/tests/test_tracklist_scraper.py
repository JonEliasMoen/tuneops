from __future__ import annotations

import pytest

from backend.music_tools.tracklist import Tracklist
from backend.music_tools.tracklist import scraper


class Response:
    def __init__(self, text: str = "", payload=None, status_code: int = 200):
        self.text = text
        self._payload = payload
        self.status_code = status_code

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


def test_scraper_uses_timeout_and_identifiable_user_agent(monkeypatch):
    captured = {}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response("<html><head><title>Mix</title></head></html>")

    monkeypatch.setattr(scraper.requests, "get", get)

    soup = scraper.get_soup(
        "https://www.1001tracklists.com/tracklist/example/test.html"
    )

    assert soup.title.string == "Mix"
    assert captured["timeout"] == scraper.REQUEST_TIMEOUT_SECONDS
    assert captured["headers"]["User-Agent"].startswith("TuneOps/")


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
