"""Small, bounded HTTP helpers for the future 1001Tracklists importer."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fake_headers import Headers


LOGGER = logging.getLogger("musicsync")
BASE_URL = "https://www.1001tracklists.com"
SEARCH_URL = f"{BASE_URL}/search/result.php"
ALLOWED_HOSTS = {"1001tracklists.com", "www.1001tracklists.com"}
REQUEST_TIMEOUT_SECONDS = 8
MAX_PAGE_BYTES = 2_000_000


def _browser_headers() -> dict[str, str]:
    """Generate the browser request headers used by the original scraper."""
    return Headers().generate()


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


def _soup(
    response: requests.Response,
    content: bytes | None = None,
) -> BeautifulSoup:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TracklistScrapeError(
            f"1001Tracklists returned HTTP {response.status_code}"
        ) from exc
    soup = BeautifulSoup(content if content is not None else response.content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if "Error 403" in title:
        raise TracklistScrapeError("1001Tracklists requested a captcha")
    turnstile = soup.find(
        "script",
        src=lambda value: bool(
            value and "challenges.cloudflare.com/turnstile" in value
        ),
    )
    captcha_field = soup.find("input", attrs={"name": "captcha"})
    if turnstile is not None or captcha_field is not None:
        raise TracklistScrapeError(
            "1001Tracklists requested interactive browser verification"
        )
    return soup


def get_soup(url: str) -> BeautifulSoup:
    """Retrieve one allowlisted 1001Tracklists page."""
    allowed_url = _require_allowed_url(url)
    started = time.perf_counter()
    LOGGER.info("tracklist.http start operation=page timeout_seconds=%d", REQUEST_TIMEOUT_SECONDS)
    try:
        response = requests.get(
            allowed_url,
            headers=_browser_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        LOGGER.warning(
            "tracklist.http failed operation=page error=%s duration_ms=%d",
            type(exc).__name__,
            round((time.perf_counter() - started) * 1000),
        )
        raise
    LOGGER.info(
        "tracklist.http complete operation=page status=%d bytes=%d duration_ms=%d",
        response.status_code,
        len(response.content),
        round((time.perf_counter() - started) * 1000),
    )
    if len(response.content) > MAX_PAGE_BYTES:
        raise TracklistScrapeError("1001Tracklists page exceeded the import size limit")
    return _soup(response)


def search_1001tracklist(video_url: str) -> BeautifulSoup:
    """Search 1001Tracklists for a user-supplied video URL."""
    started = time.perf_counter()
    LOGGER.info("tracklist.http start operation=search timeout_seconds=%d", REQUEST_TIMEOUT_SECONDS)
    try:
        response = requests.post(
            SEARCH_URL,
            headers=_browser_headers(),
            data={"main_search": str(video_url or "").strip(), "search_selection": 9},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        LOGGER.warning(
            "tracklist.http failed operation=search error=%s duration_ms=%d",
            type(exc).__name__,
            round((time.perf_counter() - started) * 1000),
        )
        raise
    LOGGER.info(
        "tracklist.http complete operation=search status=%d bytes=%d duration_ms=%d",
        response.status_code,
        len(response.content),
        round((time.perf_counter() - started) * 1000),
    )
    return _soup(response)


def get_json(url: str) -> Any:
    """Retrieve JSON from an allowlisted 1001Tracklists endpoint."""
    response = requests.get(
        _require_allowed_url(url),
        headers=_browser_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TracklistScrapeError(
            "1001Tracklists returned an invalid JSON response"
        ) from exc
