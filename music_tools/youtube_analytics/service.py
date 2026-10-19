"""Backend-only Google OAuth and targeted YouTube Analytics queries."""

from __future__ import annotations

import json
import csv
import io
import os
import re
import secrets
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = ROOT / ".youtube_oauth.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REPORTING_URL = "https://youtubereporting.googleapis.com/v1"
REACH_REPORT_TYPE = "channel_reach_basic_a1"
_VIDEO_TITLES: dict[str, str] = {}
_VIDEO_UPLOAD_DATES: dict[str, str] = {}
_VIDEO_DURATIONS: dict[str, int] = {}
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)


class YouTubeAuthError(RuntimeError):
    pass


def configured() -> bool:
    return bool(
        os.getenv("GOOGLE_CLIENT_ID", "").strip()
        and os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        and os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    )


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(state: str) -> str:
    if not configured():
        raise YouTubeAuthError("Configure Google OAuth credentials in .env first.")
    return f"{AUTH_URL}?{urlencode({
        'client_id': os.environ['GOOGLE_CLIENT_ID'].strip(),
        'redirect_uri': os.environ['GOOGLE_REDIRECT_URI'].strip(),
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'consent',
        'state': state,
    })}"


def _read_token() -> dict[str, Any]:
    try:
        value = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_token(token: dict[str, Any]) -> None:
    temporary = TOKEN_PATH.with_suffix(TOKEN_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(token, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TOKEN_PATH)


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(TOKEN_URL, data=data, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise YouTubeAuthError("Google could not complete OAuth authorization.") from exc
    if not payload.get("access_token"):
        raise YouTubeAuthError("Google did not return an access token.")
    return payload


def exchange_code(code: str) -> dict[str, Any]:
    payload = _token_request({
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "code": str(code or "").strip(),
        "grant_type": "authorization_code",
        "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI", "").strip(),
    })
    payload["expires_at"] = time.time() + float(payload.get("expires_in") or 3600)
    _write_token(payload)
    return payload


def access_token() -> str:
    token = _read_token()
    if token.get("access_token") and float(token.get("expires_at") or 0) > time.time() + 60:
        return str(token["access_token"])
    refresh_token = str(token.get("refresh_token") or "").strip()
    if not refresh_token:
        raise YouTubeAuthError("Connect YouTube Analytics first.")
    refreshed = _token_request({
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    refreshed["refresh_token"] = refresh_token
    refreshed["expires_at"] = time.time() + float(refreshed.get("expires_in") or 3600)
    _write_token(refreshed)
    return str(refreshed["access_token"])


def status() -> dict[str, Any]:
    token = _read_token()
    return {
        "configured": configured(),
        "connected": bool(token.get("refresh_token") or token.get("access_token")),
        "expires_at": float(token.get("expires_at") or 0) or None,
    }


def query_video_analytics(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return lifetime channel-owner analytics keyed by requested video ID."""
    unique_ids = list(dict.fromkeys(str(item).strip() for item in video_ids if str(item).strip()))
    if not unique_ids:
        return {}
    headers = {"Authorization": f"Bearer {access_token()}"}
    metrics = (
        "views,estimatedMinutesWatched,averageViewDuration,"
        "averageViewPercentage,likes,comments,subscribersGained"
    )
    results: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(unique_ids), 500):
        batch = unique_ids[offset:offset + 500]
        try:
            response = requests.get(
                ANALYTICS_URL,
                headers=headers,
                params={
                    "ids": "channel==MINE",
                    "startDate": "2005-02-14",
                    "endDate": date.today().isoformat(),
                    "metrics": metrics,
                    "dimensions": "video",
                    "filters": f"video=={','.join(batch)}",
                    "maxResults": 500,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError("YouTube Analytics could not be retrieved.") from exc
        names = [str(item.get("name") or "") for item in payload.get("columnHeaders") or []]
        for values in payload.get("rows") or []:
            record = dict(zip(names, values))
            video_id = str(record.get("video") or "")
            if video_id:
                results[video_id] = record
    return results


def _reporting_collection(path: str, key: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Read every page from one YouTube Reporting API collection."""
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(f"{REPORTING_URL}/{path}", headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items.extend(item for item in payload.get(key) or [] if isinstance(item, dict))
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            return items


def sync_video_reach_reports(
    video_ids: list[str], imported_report_ids: set[str],
) -> dict[str, Any]:
    """Create/import asynchronous thumbnail reach reports for selected videos."""
    selected = {str(item).strip() for item in video_ids if str(item).strip()}
    if not selected:
        return {"records": [], "report_ids": [], "job_created": False}
    headers = {"Authorization": f"Bearer {access_token()}"}
    try:
        jobs = _reporting_collection("jobs", "jobs", headers)
        job = next(
            (item for item in jobs if item.get("reportTypeId") == REACH_REPORT_TYPE),
            None,
        )
        if job is None:
            response = requests.post(
                f"{REPORTING_URL}/jobs",
                headers={**headers, "Content-Type": "application/json"},
                json={"reportTypeId": REACH_REPORT_TYPE, "name": "MusicSync cover reach"},
                timeout=30,
            )
            response.raise_for_status()
            return {"records": [], "report_ids": [], "job_created": True}
        job_id = str(job.get("id") or "")
        reports = _reporting_collection(f"jobs/{job_id}/reports", "reports", headers)
        pending = [
            item for item in reports
            if str(item.get("id") or "") not in imported_report_ids
            and str(item.get("downloadUrl") or "")
        ]
        records: list[dict[str, Any]] = []
        imported: list[str] = []
        for report in pending:
            response = requests.get(str(report["downloadUrl"]), headers=headers, timeout=60)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
            for row in reader:
                # Cache the whole owner report. Otherwise marking this report
                # imported would prevent a My Mix added later from receiving
                # its historical reach rows.
                if str(row.get("video_id") or ""):
                    records.append(dict(row))
            imported.append(str(report["id"]))
        return {"records": records, "report_ids": imported, "job_created": False}
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 403:
            raise RuntimeError(
                "YouTube Reporting API returned 403. Enable YouTube Reporting API "
                "in the Google Cloud project that owns this OAuth client, then retry."
            ) from exc
        raise RuntimeError("YouTube cover reach reports could not be retrieved.") from exc
    except (requests.RequestException, ValueError, csv.Error) as exc:
        raise RuntimeError("YouTube cover reach reports could not be retrieved.") from exc


def query_video_titles(video_ids: list[str]) -> dict[str, str]:
    """Fetch video titles in batches and retain them for overview responses."""
    unique_ids = list(dict.fromkeys(str(item).strip() for item in video_ids if str(item).strip()))
    if not unique_ids:
        return {}
    headers = {"Authorization": f"Bearer {access_token()}"}
    titles: dict[str, str] = {}
    for offset in range(0, len(unique_ids), 50):
        batch = unique_ids[offset:offset + 50]
        try:
            response = requests.get(
                VIDEOS_URL,
                headers=headers,
                params={"part": "snippet,contentDetails", "id": ",".join(batch)},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            # YouTube Analytics and YouTube Data are enabled separately in
            # Google Cloud. Public oEmbed still gives us titles when the Data
            # API is unavailable or has not been enabled for this project.
            for video_id in batch:
                try:
                    response = requests.get(
                        "https://www.youtube.com/oembed",
                        params={
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "format": "json",
                        },
                        timeout=10,
                    )
                    response.raise_for_status()
                    title = str(response.json().get("title") or "").strip()
                    if title:
                        titles[video_id] = title
                except (requests.RequestException, ValueError):
                    continue
            continue
        for item in payload.get("items") or []:
            video_id = str(item.get("id") or "")
            snippet = item.get("snippet") or {}
            title = str(snippet.get("title") or "").strip()
            if video_id and title:
                titles[video_id] = title
            published_at = str(snippet.get("publishedAt") or "").strip()
            if video_id and published_at:
                _VIDEO_UPLOAD_DATES[video_id] = published_at[:10]
            duration = str((item.get("contentDetails") or {}).get("duration") or "")
            duration_match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
            if video_id and duration_match:
                hours, minutes, seconds = (int(value or 0) for value in duration_match.groups())
                _VIDEO_DURATIONS[video_id] = hours * 3600 + minutes * 60 + seconds
    _VIDEO_TITLES.update(titles)
    return titles


def cached_video_title(video_id: str | None) -> str:
    return _VIDEO_TITLES.get(str(video_id or ""), "")


def cached_video_upload_date(video_id: str | None) -> str:
    return _VIDEO_UPLOAD_DATES.get(str(video_id or ""), "")


def cached_video_duration_seconds(video_id: str | None) -> int | None:
    return _VIDEO_DURATIONS.get(str(video_id or ""))
