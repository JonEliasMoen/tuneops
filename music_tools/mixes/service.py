"""Read-only discovery of the user's local DJ mix folders."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from music_library.database import (
    setlist_metadata,
    store_tidal_setlist,
    tidal_track_record,
)


DEFAULT_MIX_ROOT = Path.home() / "Documents" / "djstuff"
MIX_ROOT = Path(os.getenv("MUSICSYNC_MIX_ROOT", DEFAULT_MIX_ROOT)).resolve()
EXCLUDED_FOLDERS = {"vis1tracktimer", "visv1tracktimer"}


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


def discover_mixes() -> list[Mix]:
    """Discover immediate child folders without walking arbitrary paths."""
    if not MIX_ROOT.is_dir():
        return []
    saved_metadata = setlist_metadata()
    mixes: list[Mix] = []
    for folder in sorted(MIX_ROOT.iterdir(), key=lambda item: item.name.casefold()):
        if not folder.is_dir() or _is_excluded(folder.name):
            continue
        positions_path = folder / "positions.txt"
        cover_path = folder / "cover.png"
        audio_path = folder / f"{folder.name}yt.wav"
        try:
            positions = positions_path.read_text(encoding="utf-8-sig") if positions_path.is_file() else ""
        except UnicodeDecodeError:
            positions = positions_path.read_text(encoding="cp1252", errors="replace")
        metadata = saved_metadata.get(folder.name, {})
        mixes.append(
            Mix(
                folder_name=folder.name,
                positions=positions,
                cover_path=cover_path.resolve() if cover_path.is_file() else None,
                audio_path=audio_path.resolve() if audio_path.is_file() else None,
                youtube_url=metadata.get("youtube_url", ""),
                tidal_url=metadata.get("tidal_url", ""),
                tidal_playlist_id=metadata.get("tidal_playlist_id", ""),
                tidal_playlist_name=metadata.get("tidal_playlist_name", ""),
            )
        )
    return mixes


def cover_for(folder_name: str) -> Path | None:
    """Resolve a cover only for a currently discovered mix."""
    return next(
        (mix.cover_path for mix in discover_mixes() if mix.folder_name == folder_name),
        None,
    )


def mix_for(folder_name: str) -> Mix | None:
    """Return one discovered mix by its exact folder name."""
    return next((mix for mix in discover_mixes() if mix.folder_name == folder_name), None)


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
