"""Database-backed My Mix metadata and TIDAL setlist import."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from music_library.database import (
    setlist_metadata,
    setlist_metadata_for,
    store_tidal_setlist,
    tidal_track_record,
)


LOGGER = logging.getLogger("musicsync")


@dataclass(frozen=True)
class Mix:
    folder_name: str
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
            headers={"User-Agent": "Mozilla/5.0 (TuneOps My Mixes)"},
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


def _mix_from(folder_name: str, metadata: dict[str, Any]) -> Mix:
    saved_youtube_url = str(metadata.get("youtube_url", "") or "")
    analytics_current = bool(
        youtube_video_id(saved_youtube_url)
        and youtube_video_id(saved_youtube_url) == metadata.get("youtube_video_id")
    )
    return Mix(
        folder_name=folder_name,
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
    """Return every persisted My Mix without consulting the local filesystem."""
    return [
        _mix_from(folder_name, metadata)
        for folder_name, metadata in setlist_metadata().items()
    ]


def tidal_mix_name(playlist_name: str) -> str | None:
    """Return the internal My Mix name for an exact ``djset <name>`` title."""
    match = re.fullmatch(r"\s*djset\s+(.+?)\s*", str(playlist_name or ""), re.IGNORECASE)
    if match is None:
        return None
    name = " ".join(match.group(1).split())
    return name or None


def discover_tidal_mixes(
    engine: Any,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Import previously unseen owned TIDAL ``djset`` playlists exactly once.

    Existing TIDAL mappings are deliberately immutable here. A manual import on
    the individual mix remains the explicit way to replace an existing mapping.
    """
    report = progress or (lambda _message: None)
    existing = discover_mixes()
    existing_by_name = {mix.folder_name.casefold(): mix for mix in existing}
    linked_playlist_ids = {
        mix.tidal_playlist_id for mix in existing if mix.tidal_playlist_id
    }

    report("Loading your TIDAL playlists")
    session = engine.tidal_client(interactive=False)
    playlists = list(
        engine._call(
            "tidal",
            "discover_mix_playlists",
            session.user.playlists,
        )
    )
    candidates: list[tuple[str, Any]] = []
    for playlist in playlists:
        internal_name = tidal_mix_name(getattr(playlist, "name", ""))
        playlist_id = str(getattr(playlist, "id", "") or "")
        if internal_name and playlist_id:
            candidates.append((internal_name, playlist))

    name_counts = Counter(name.casefold() for name, _playlist in candidates)
    duplicate_names = {name for name, count in name_counts.items() if count > 1}
    results: list[dict[str, Any]] = []
    imported = 0
    for index, (discovered_name, playlist) in enumerate(candidates, start=1):
        playlist_id = str(playlist.id)
        playlist_name = str(getattr(playlist, "name", "") or "")
        existing_mix = existing_by_name.get(discovered_name.casefold())
        internal_name = existing_mix.folder_name if existing_mix else discovered_name
        base = {
            "internal_name": internal_name,
            "playlist_id": playlist_id,
            "playlist_name": playlist_name,
        }
        if playlist_id in linked_playlist_ids:
            results.append({**base, "status": "already_imported"})
            continue
        if discovered_name.casefold() in duplicate_names:
            results.append({**base, "status": "ambiguous"})
            continue
        if existing_mix and existing_mix.tidal_playlist_id:
            results.append({**base, "status": "name_conflict"})
            continue

        report(f"Importing {playlist_name}: {index}/{len(candidates)}")
        try:
            items = engine._call(
                "tidal",
                "discover_mix_tracks",
                playlist.tracks,
                playlist_id=playlist_id,
                setlist=internal_name,
            )
            records = [tidal_track_record(track) for track in items]
            if not records:
                results.append({**base, "status": "empty"})
                continue
            tidal_url = f"https://tidal.com/playlist/{playlist_id}"
            store_tidal_setlist(internal_name, tidal_url, playlist, records, [])
        except Exception:
            LOGGER.exception(
                "mix.discovery_import_failed playlist_id=%s setlist=%s",
                playlist_id,
                internal_name,
            )
            results.append({**base, "status": "failed"})
            continue
        imported += 1
        linked_playlist_ids.add(playlist_id)
        existing_by_name[internal_name.casefold()] = _mix_from(
            internal_name,
            {
                "tidal_url": tidal_url,
                "tidal_playlist_id": playlist_id,
                "tidal_playlist_name": playlist_name,
                "track_count": len(records),
            },
        )
        results.append({**base, "status": "imported", "tracks": len(records)})

    return {
        "scanned": len(playlists),
        "candidates": len(candidates),
        "imported": imported,
        "results": results,
    }


def mix_for(folder_name: str) -> Mix | None:
    """Return one persisted My Mix without consulting the local filesystem."""
    name = str(folder_name or "").strip()
    if not name:
        return None
    metadata = setlist_metadata_for(name)
    return _mix_from(name, metadata) if metadata else None


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
        [],
    )
    return playlist, records
