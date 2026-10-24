"""Read-only discovery of the user's local DJ mix folders."""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from music_library.database import (
    setlist_metadata,
    setlist_metadata_for,
    store_tidal_setlist,
    tidal_track_record,
)


DEFAULT_MIX_ROOT = Path.home() / "Documents" / "djstuff"
MIX_ROOT = Path(os.getenv("MUSICSYNC_MIX_ROOT", DEFAULT_MIX_ROOT)).resolve()
EXCLUDED_FOLDERS = {"vis1tracktimer", "visv1tracktimer"}
MIX_SNAPSHOT_SECONDS = 30.0


@dataclass(frozen=True)
class _MixFiles:
    folder_name: str
    positions: str
    cover_path: Path | None
    audio_path: Path | None


_snapshot_lock = threading.Lock()
_snapshot_at = 0.0
_snapshot_files: tuple[_MixFiles, ...] = ()


@dataclass(frozen=True)
class Mix:
    folder_name: str
    positions: str
    cover_path: Path | None
    audio_path: Path | None
    youtube_url: str
    tidal_url: str
    tidal_playlist_id: str
    tidal_playlist_name: str
    updated_at: str = ""
    track_count: int = 0
    youtube_views: int | None = None
    youtube_thumbnail_impressions: int | None = None
    youtube_thumbnail_ctr: float | None = None
    youtube_watch_minutes: float | None = None
    youtube_average_view_duration: float | None = None
    youtube_average_view_percentage: float | None = None
    youtube_likes: int | None = None
    youtube_comments: int | None = None
    youtube_subscribers_gained: int | None = None
    youtube_analytics_fetched_at: str = ""


@dataclass(frozen=True)
class YouTubeMetadata:
    title: str = ""
    channel_name: str = ""
    view_count: int | None = None
    upload_date: str = ""
    error: str = ""


def youtube_video_id(url: str) -> str | None:
    """Extract a safe video ID without making a request to a user supplied host."""
    value = str(url or "").strip()
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").casefold()
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in {"embed", "live", "shorts"}:
                video_id = parts[1]
    return video_id if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id) else None


def youtube_thumbnail_url(url: str) -> str:
    """Return YouTube's broadly available thumbnail URL for a validated video."""
    video_id = youtube_video_id(url)
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""


def fetch_youtube_metadata(url: str) -> YouTubeMetadata:
    """Fetch current public metadata without persisting the response."""
    video_id = youtube_video_id(url)
    if not video_id:
        return YouTubeMetadata(error="Enter a valid YouTube video URL.") if url else YouTubeMetadata()
    try:
        response = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0 (MusicSync local mix explorer)"},
            timeout=8,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return YouTubeMetadata(error=f"Could not fetch YouTube metadata: {exc}")

    page = response.text
    title_match = re.search(
        r'<meta\s+(?:name|property)=["\'](?:title|og:title)["\']\s+content=["\']([^"\']+)',
        page,
        flags=re.IGNORECASE,
    )
    if title_match is None:
        title_match = re.search(r"<title>(.*?)</title>", page, flags=re.IGNORECASE | re.DOTALL)
    title = unescape(title_match.group(1)).strip() if title_match else ""
    if title.endswith(" - YouTube"):
        title = title[: -len(" - YouTube")].rstrip()
    channel_match = re.search(
        r'["\'](?:ownerChannelName|author)["\']\s*:\s*["\']([^"\']+)',
        page,
    )
    if channel_match is None:
        channel_match = re.search(
            r'<link\s+itemprop=["\']name["\']\s+content=["\']([^"\']+)',
            page,
            flags=re.IGNORECASE,
        )
    channel_name = unescape(channel_match.group(1)).strip() if channel_match else ""
    views_match = re.search(r'["\']viewCount["\']\s*:\s*["\']?(\d+)', page)
    views = int(views_match.group(1)) if views_match else None
    date_match = re.search(
        r'["\'](?:publishDate|uploadDate)["\']\s*:\s*["\'](\d{4}-\d{2}-\d{2})',
        page,
    )
    if date_match is None:
        date_match = re.search(
            r'<meta\s+itemprop=["\']uploadDate["\']\s+content=["\'](\d{4}-\d{2}-\d{2})',
            page,
            flags=re.IGNORECASE,
        )
    upload_date = date_match.group(1) if date_match else ""
    error = (
        ""
        if title or views is not None or upload_date
        else "YouTube metadata was not available."
    )
    return YouTubeMetadata(
        title=title,
        channel_name=channel_name,
        view_count=views,
        upload_date=upload_date,
        error=error,
    )


def _is_excluded(name: str) -> bool:
    return name.casefold() in EXCLUDED_FOLDERS


def _read_positions(folder: Path) -> str:
    positions_path = folder / "positions.txt"
    if not positions_path.is_file():
        return ""
    try:
        return positions_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return positions_path.read_text(encoding="cp1252", errors="replace")


def _safe_mix_folder(folder_name: str) -> Path | None:
    """Resolve one immediate mix child without allowing path traversal."""
    name = str(folder_name or "")
    if not name or _is_excluded(name) or Path(name).name != name:
        return None
    candidate = (MIX_ROOT / name).resolve()
    if candidate.parent != MIX_ROOT or not candidate.is_dir():
        return None
    return candidate


def _files_for(folder: Path) -> _MixFiles:
    cover_path = folder / "cover.png"
    audio_path = folder / f"{folder.name}yt.wav"
    return _MixFiles(
        folder_name=folder.name,
        positions=_read_positions(folder),
        cover_path=cover_path.resolve() if cover_path.is_file() else None,
        audio_path=audio_path.resolve() if audio_path.is_file() else None,
    )


def invalidate_mix_snapshot() -> None:
    """Discard the short-lived local folder snapshot after a relevant change."""
    global _snapshot_at, _snapshot_files
    with _snapshot_lock:
        _snapshot_at = 0.0
        _snapshot_files = ()


def _mix_files_snapshot() -> tuple[_MixFiles, ...]:
    global _snapshot_at, _snapshot_files
    now = time.monotonic()
    with _snapshot_lock:
        if _snapshot_at and now - _snapshot_at < MIX_SNAPSHOT_SECONDS:
            return _snapshot_files
    if not MIX_ROOT.is_dir():
        files: tuple[_MixFiles, ...] = ()
    else:
        files = tuple(
            _files_for(folder)
            for folder in sorted(MIX_ROOT.iterdir(), key=lambda item: item.name.casefold())
            if folder.is_dir() and not _is_excluded(folder.name)
        )
    with _snapshot_lock:
        _snapshot_files = files
        _snapshot_at = now
    return files


def _mix_from(files: _MixFiles, metadata: dict[str, Any]) -> Mix:
    saved_youtube_url = str(metadata.get("youtube_url", "") or "")
    analytics_current = bool(
        youtube_video_id(saved_youtube_url)
        and youtube_video_id(saved_youtube_url) == metadata.get("youtube_video_id")
    )
    return Mix(
        folder_name=files.folder_name,
        positions=files.positions,
        cover_path=files.cover_path,
        audio_path=files.audio_path,
        youtube_url=saved_youtube_url,
        tidal_url=str(metadata.get("tidal_url", "") or ""),
        tidal_playlist_id=str(metadata.get("tidal_playlist_id", "") or ""),
        tidal_playlist_name=str(metadata.get("tidal_playlist_name", "") or ""),
        updated_at=str(metadata.get("updated_at", "") or ""),
        track_count=int(metadata.get("track_count", 0) or 0),
        youtube_views=metadata.get("youtube_views") if analytics_current else None,
        youtube_thumbnail_impressions=metadata.get("youtube_thumbnail_impressions") if analytics_current else None,
        youtube_thumbnail_ctr=metadata.get("youtube_thumbnail_ctr") if analytics_current else None,
        youtube_watch_minutes=metadata.get("youtube_watch_minutes") if analytics_current else None,
        youtube_average_view_duration=metadata.get("youtube_average_view_duration") if analytics_current else None,
        youtube_average_view_percentage=metadata.get("youtube_average_view_percentage") if analytics_current else None,
        youtube_likes=metadata.get("youtube_likes") if analytics_current else None,
        youtube_comments=metadata.get("youtube_comments") if analytics_current else None,
        youtube_subscribers_gained=metadata.get("youtube_subscribers_gained") if analytics_current else None,
        youtube_analytics_fetched_at=str(metadata.get("youtube_analytics_fetched_at", "") or "") if analytics_current else "",
    )


def discover_mixes() -> list[Mix]:
    """Discover immediate child folders without walking arbitrary paths."""
    saved_metadata = setlist_metadata()
    return [
        _mix_from(files, saved_metadata.get(files.folder_name, {}))
        for files in _mix_files_snapshot()
    ]


def cover_for(folder_name: str) -> Path | None:
    """Resolve one mix cover directly without scanning every folder."""
    folder = _safe_mix_folder(folder_name)
    if folder is None:
        return None
    cover = folder / "cover.png"
    return cover.resolve() if cover.is_file() else None


def mix_for(folder_name: str) -> Mix | None:
    """Return one exact mix without loading metadata or files for all mixes."""
    folder = _safe_mix_folder(folder_name)
    if folder is None:
        return None
    return _mix_from(_files_for(folder), setlist_metadata_for(folder.name))


def track_positions(positions_text: str) -> list[str]:
    """Return display timestamps in the same order as positions.txt."""
    positions: list[str] = []
    for line in str(positions_text or "").splitlines():
        match = re.match(r"^\s*\[([^\]]+)\]", line)
        if match:
            positions.append(match.group(1).strip())
    return positions


def import_tidal_setlist(engine, mix: Mix, tidal_url: str) -> tuple[Any, list[dict[str, Any]]]:
    """Fetch a TIDAL playlist as an import source and store only setlist membership."""
    playlist_id = engine._id(tidal_url)
    if not playlist_id:
        raise ValueError("TIDAL playlist URL or ID is empty")
    session = engine.tidal_client(interactive=False)
    playlist = engine._call(
        "tidal",
        "get_setlist_source",
        lambda: session.playlist(playlist_id),
        playlist_id=playlist_id,
        setlist=mix.folder_name,
    )
    items = engine._call(
        "tidal",
        "setlist_source_tracks",
        playlist.tracks,
        playlist_id=playlist_id,
        setlist=mix.folder_name,
    )
    records = [tidal_track_record(track) for track in items]
    if not records:
        raise RuntimeError(
            f"TIDAL returned zero tracks for {getattr(playlist, 'name', playlist_id)!r}"
        )
    store_tidal_setlist(
        mix.folder_name,
        tidal_url,
        playlist,
        records,
        track_positions(mix.positions),
    )
    return playlist, records
