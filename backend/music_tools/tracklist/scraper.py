"""Small, bounded HTTP helpers for the future 1001Tracklists importer."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.1001tracklists.com"
SEARCH_URL = f"{BASE_URL}/search/result.php"
ALLOWED_HOSTS = {"1001tracklists.com", "www.1001tracklists.com"}
REQUEST_TIMEOUT_SECONDS = 15
HEADERS = {
    "User-Agent": (
        "TuneOps/0.1 (+https://tuneops.vercel.app; "
        "personal tracklist import)"
    )
}


class TracklistScrapeError(RuntimeError):
    """Raised when 1001Tracklists cannot provide a usable response."""


def is_1001tracklists_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_HOSTS


def _require_allowed_url(url: str) -> str:
    cleaned = str(url or "").strip()
    if not is_1001tracklists_url(cleaned):
        raise ValueError("Only HTTPS URLs on 1001tracklists.com are allowed")
    return cleaned


def _soup(response: requests.Response) -> BeautifulSoup:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TracklistScrapeError(
            f"1001Tracklists returned HTTP {response.status_code}"
        ) from exc
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if "Error 403" in title:
        raise TracklistScrapeError("1001Tracklists requested a captcha")
    return soup


def get_soup(url: str) -> BeautifulSoup:
    """Retrieve one allowlisted 1001Tracklists page."""
    response = requests.get(
        _require_allowed_url(url),
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return _soup(response)


def search_1001tracklist(video_url: str) -> BeautifulSoup:
    """Search 1001Tracklists for a user-supplied video URL."""
    response = requests.post(
        SEARCH_URL,
        headers=HEADERS,
        data={"main_search": str(video_url or "").strip(), "search_selection": 9},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return _soup(response)


def get_json(url: str) -> Any:
    """Retrieve JSON from an allowlisted 1001Tracklists endpoint."""
    response = requests.get(
        _require_allowed_url(url),
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TracklistScrapeError(
            "1001Tracklists returned an invalid JSON response"
        ) from exc
