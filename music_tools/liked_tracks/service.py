"""TIDAL data retrieval and presentation mapping for liked tracks."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from music_library.database import (
    cached_tidal_liked_tracks,
    store_tidal_liked_tracks,
    tidal_playlist_tracks_page,
    tidal_setlist_tracks_page,
)


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _artists(track: Any) -> str:
    artists = getattr(track, "artists", None) or []
    names = [_text(getattr(artist, "name", "")) for artist in artists]
    names = [name for name in names if name]
    if names:
        return ", ".join(names)
    return _text(getattr(getattr(track, "artist", None), "name", ""))


def _year(track: Any) -> str:
    album = getattr(track, "album", None)
    value = (
        getattr(album, "release_date", None)
        or getattr(track, "tidal_release_date", None)
        or getattr(track, "stream_start_date", None)
    )
    if isinstance(value, (date, datetime)):
        return str(value.year)
    text = _text(value)
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _date_added(track: Any) -> str:
    value = getattr(track, "user_date_added", None) or getattr(track, "date_added", None)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone()
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    return text[:16].replace("T", " ") if text else ""


def _duration(seconds: Any) -> str:
    try:
        total = max(0, round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    minutes, remaining = divmod(total, 60)
    return f"{minutes}:{remaining:02d}"


def _key(track: Any) -> str:
    raw_key = _text(getattr(track, "key", ""))
    raw_scale = _text(getattr(track, "key_scale", ""))
    if not raw_key:
        return ""

    # Convert TIDAL's conventional pitch + scale into DJ-friendly Camelot keys.
    normalized = (
        raw_key.upper()
        .replace("♯", "#").replace("♭", "B")
        .replace("-FLAT", "B").replace("_FLAT", "B").replace(" FLAT", "B")
        .replace("-SHARP", "#").replace("_SHARP", "#").replace(" SHARP", "#")
        .replace(" ", "")
    )
    scale = raw_scale.upper()
    is_minor = "MINOR" in scale or normalized.endswith(("MIN", "MINOR"))
    is_major = "MAJOR" in scale or normalized.endswith(("MAJ", "MAJOR"))
    if not is_minor and not is_major:
        return ""
    normalized = normalized.removesuffix("MINOR").removesuffix("MIN")
    normalized = normalized.removesuffix("MAJOR").removesuffix("MAJ")
    minor = {
        "G#": "01A", "AB": "01A", "D#": "02A", "EB": "02A",
        "A#": "03A", "BB": "03A", "F": "04A", "C": "05A",
        "G": "06A", "D": "07A", "A": "08A", "E": "09A",
        "B": "10A", "F#": "11A", "GB": "11A", "C#": "12A", "DB": "12A",
    }
    major = {
        "B": "01B", "F#": "02B", "GB": "02B", "C#": "03B", "DB": "03B",
        "G#": "04B", "AB": "04B", "D#": "05B", "EB": "05B",
        "A#": "06B", "BB": "06B", "F": "07B", "C": "08B",
        "G": "09B", "D": "10B", "A": "11B", "E": "12B",
    }
    return (minor if is_minor else major).get(normalized, "")


def track_row(track: Any) -> dict[str, str]:
    """Convert a tidalapi Track into stable, JSON-friendly table fields."""
    album = getattr(track, "album", None)
    bpm = getattr(track, "bpm", None)
    try:
        bpm_text = f"{float(bpm):g}" if bpm not in (None, "") else ""
    except (TypeError, ValueError):
        bpm_text = _text(bpm)
    try:
        album_art_url = album.image(320) if album else ""
    except (AttributeError, TypeError, ValueError):
        album_art_url = ""
    return {
        "id": _text(getattr(track, "id", "")),
        "title": _text(getattr(track, "name", "") or getattr(track, "full_name", "")),
        "artist": _artists(track),
        "remix": _text(getattr(track, "version", "")),
        "album": _text(getattr(album, "name", "")),
        "album_art_url": album_art_url,
        "length": _duration(getattr(track, "duration", None)),
        "bpm": bpm_text,
        "key": _key(track),
        "year": _year(track),
        "date_added": _date_added(track),
    }


def _cached_track_row(record: dict[str, Any]) -> dict[str, str]:
    """Map a SQLite provider record into the same shape as a live track."""
    bpm = record.get("bpm")
    try:
        bpm_text = f"{float(bpm):g}" if bpm not in (None, "") else ""
    except (TypeError, ValueError):
        bpm_text = _text(bpm)

    added = _text(record.get("date_added"))
    if added:
        try:
            parsed_added = datetime.fromisoformat(added.replace("Z", "+00:00"))
            if parsed_added.tzinfo is not None:
                parsed_added = parsed_added.astimezone()
            added = parsed_added.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            added = added[:16].replace("T", " ")
    return {
        "id": _text(record.get("id")),
        "title": _text(record.get("title")),
        "artist": _text(record.get("artist")),
        "remix": _text(record.get("remix")),
        "album": _text(record.get("album")),
        "album_art_url": _text(record.get("album_art_url")),
        "length": _duration(record.get("duration_seconds")),
        "bpm": bpm_text,
        "key": _key(
            SimpleNamespace(
                key=record.get("musical_key", ""),
                key_scale=record.get("key_scale", ""),
            )
        ),
        "year": _text(record.get("year")),
        "date_added": added,
        "mix_position": _text(record.get("mix_position")),
    }


def fetch_liked_tracks(
    engine: Any,
    limit: int = 30,
    offset: int = 0,
    force_refresh: bool = False,
    cache_seconds: int = 300,
) -> tuple[list[dict[str, str]], bool]:
    """Load one liked-track page and report whether another may exist."""
    from tidalapi.user import ItemOrder, OrderDirection

    session = engine.tidal_client(interactive=False)
    user_id = str(session.user.id)
    if not force_refresh:
        cached = cached_tidal_liked_tracks(
            user_id,
            limit=limit,
            max_age_seconds=cache_seconds,
            offset=offset,
        )
        if cached:
            engine.LOGGER.info(
                "tidal.liked_tracks cache_hit user_id=%s offset=%d tracks=%d",
                user_id,
                offset,
                len(cached),
            )
            # A partial older snapshot may contain fewer than the new page size;
            # let the scroll sentinel probe TIDAL for the following page.
            return [_cached_track_row(record) for record in cached], bool(cached)
    engine.LOGGER.info(
        "tidal.liked_tracks cache_miss user_id=%s force=%s offset=%d",
        user_id,
        force_refresh,
        offset,
    )
    tracks = engine._call(
        "tidal",
        "favorite_tracks",
        lambda: session.user.favorites.tracks(
            limit=limit,
            offset=offset,
            order=ItemOrder.Date,
            order_direction=OrderDirection.Descending,
        ),
        limit=limit,
        offset=offset,
        order="date_descending",
    )
    store_tidal_liked_tracks(user_id, tracks, offset=offset)
    return [track_row(track) for track in tracks], len(tracks) == limit


def fetch_indexed_playlist_tracks(
    playlist_id: str, limit: int = 30, offset: int = 0
) -> tuple[list[dict[str, str]], bool]:
    """Read one playlist page entirely from the local SQLite index."""
    records = tidal_playlist_tracks_page(playlist_id, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_indexed_setlist_tracks(
    folder_name: str, limit: int = 30, offset: int = 0
) -> tuple[list[dict[str, str]], bool]:
    """Read one setlist page entirely from its dedicated SQLite membership."""
    records = tidal_setlist_tracks_page(folder_name, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit
