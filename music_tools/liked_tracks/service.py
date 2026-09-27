"""TIDAL data retrieval and presentation mapping for liked tracks."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from music_library.database import (
    latest_tidal_liked_user_id,
    tidal_artist_tracks_page,
    tidal_artists_for_tracks,
    tidal_dimensions_for_tracks,
    tidal_library_tracks_page,
    tidal_liked_tracks_page,
    tidal_playlist_tracks_page,
    tidal_setlist_tracks_page,
    tidal_watched_mix_tracks_page,
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
    artists = getattr(track, "artists", None) or []
    return {
        "id": _text(getattr(track, "id", "")),
        "title": _text(getattr(track, "name", "") or getattr(track, "full_name", "")),
        "artist": _artists(track),
        "artists": [
            {"id": _text(getattr(artist, "name", "")).casefold(), "name": _text(getattr(artist, "name", ""))}
            for artist in artists
            if _text(getattr(artist, "name", ""))
        ],
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
    added_sort = 0.0
    if added:
        try:
            parsed_added = datetime.fromisoformat(added.replace("Z", "+00:00"))
            added_sort = parsed_added.timestamp()
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
        "_date_added_sort": added_sort,
        "mix_position": _text(record.get("mix_position")),
    }


def cached_track_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map cached provider records for non-playlist library collections."""
    return [{**_cached_track_row(record), **{key: record[key] for key in ("play_count", "last_played") if key in record}} for record in records]


def _date_sorted_page(
    rows: list[dict[str, Any]],
    sort: dict[str, str] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Sort the complete local collection by date before taking a page."""
    if (sort or {}).get("field") == "date_added" and (sort or {}).get(
        "direction"
    ) in {"asc", "desc"}:
        present = [row for row in rows if row.get("date_added")]
        missing = [row for row in rows if not row.get("date_added")]
        present.sort(
            key=lambda row: row.get("_date_added_sort", row.get("date_added") or ""),
            reverse=(sort or {}).get("direction") == "desc",
        )
        rows = [*present, *missing]
    page = rows[offset : offset + limit]
    return page, offset + limit < len(rows)


def fetch_liked_tracks(
    engine: Any,
    limit: int = 30,
    offset: int = 0,
    force_refresh: bool = False,
    cache_seconds: int = 300,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Load one liked-track page exclusively from the local SQLite library."""
    user_id = latest_tidal_liked_user_id()
    if not user_id:
        engine.LOGGER.info("tidal.liked_tracks local_cache_empty no_user_snapshot=true")
        return [], False
    if filters:
        records = tidal_liked_tracks_page(user_id, limit=1_000_000)
        return _filter_records(records, filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_liked_tracks_page(user_id, limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_liked_tracks_page(user_id, limit=limit, offset=offset)
    engine.LOGGER.info(
        "tidal.liked_tracks local_page user_id=%s refresh=%s offset=%d tracks=%d",
        user_id,
        force_refresh,
        offset,
        len(records),
    )
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_indexed_playlist_tracks(
    playlist_id: str, limit: int = 30, offset: int = 0,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Read one playlist page entirely from the local SQLite index."""
    if filters:
        records = tidal_playlist_tracks_page(playlist_id, limit=1_000_000)
        return _filter_records(records, filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_playlist_tracks_page(playlist_id, limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_playlist_tracks_page(playlist_id, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_indexed_setlist_tracks(
    folder_name: str, limit: int = 30, offset: int = 0,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Read one setlist page entirely from its dedicated SQLite membership."""
    if filters:
        records = tidal_setlist_tracks_page(folder_name, limit=1_000_000)
        return _filter_records(records, filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_setlist_tracks_page(folder_name, limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_setlist_tracks_page(folder_name, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_watched_mix_tracks(
    video_id: str, limit: int = 30, offset: int = 0,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Read one watched-mix track page from local associations."""
    if filters:
        records = tidal_watched_mix_tracks_page(video_id, limit=1_000_000)
        return _filter_records(records, filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_watched_mix_tracks_page(video_id, limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_watched_mix_tracks_page(video_id, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_artist_tracks(
    artist_key: str, limit: int = 30, offset: int = 0,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Read all locally indexed tracks credited to one artist."""
    if filters:
        records = tidal_artist_tracks_page(artist_key, limit=1_000_000)
        return _filter_records(records, filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_artist_tracks_page(artist_key, limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_artist_tracks_page(artist_key, limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def fetch_library_tracks(
    limit: int = 30,
    offset: int = 0,
    filters: dict[str, Any] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Search the deduplicated local library across every requested source."""
    if filters:
        records = tidal_library_tracks_page(limit=1_000_000)
        global_filters = {**filters, "global_text": True}
        return _filter_records(records, global_filters, limit, offset, sort)
    if (sort or {}).get("field") == "date_added":
        records = tidal_library_tracks_page(limit=1_000_000)
        rows = [_cached_track_row(record) for record in records]
        return _date_sorted_page(rows, sort, limit, offset)
    records = tidal_library_tracks_page(limit=limit, offset=offset)
    return [_cached_track_row(record) for record in records], len(records) == limit


def _filter_records(
    records: list[dict[str, Any]],
    filters: dict[str, Any],
    limit: int,
    offset: int,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Apply faceted filters to a complete local collection before pagination."""
    rows = [_cached_track_row(record) for record in records]
    track_ids = [row["id"] for row in rows]
    artist_map = tidal_artists_for_tracks(track_ids)
    dimensions = tidal_dimensions_for_tracks(track_ids)
    title_query = " ".join(str(filters.get("title") or "").casefold().split())
    wanted_artists = set(filters.get("artists") or [])
    wanted_keys = set(filters.get("keys") or [])
    wanted_ratings = set(filters.get("ratings") or [])
    wanted_energy = set(filters.get("energy") or [])
    wanted_tags = set(filters.get("tags") or [])
    try:
        bpm_min = float(filters["bpm_min"]) if filters.get("bpm_min") not in (None, "") else None
        bpm_max = float(filters["bpm_max"]) if filters.get("bpm_max") not in (None, "") else None
    except (TypeError, ValueError):
        bpm_min = bpm_max = None

    matched = []
    for row in rows:
        row_artists = artist_map.get(row["id"], [])
        row_dimensions = dimensions.get(row["id"], {})
        row["artists"] = row_artists
        row["dimensions"] = row_dimensions
        searchable_fields = [row.get("title"), row.get("remix")]
        if filters.get("global_text"):
            searchable_fields.extend((row.get("artist"), row.get("album")))
        searchable_title = " ".join(
            str(value or "") for value in searchable_fields
        ).casefold()
        if title_query and title_query not in searchable_title:
            continue
        if wanted_artists and not wanted_artists.intersection(
            artist["id"] for artist in row_artists
        ):
            continue
        if wanted_keys and row.get("key") not in wanted_keys:
            continue
        try:
            bpm = float(row.get("bpm"))
        except (TypeError, ValueError):
            bpm = None
        if bpm_min is not None and (bpm is None or bpm < bpm_min):
            continue
        if bpm_max is not None and (bpm is None or bpm > bpm_max):
            continue
        if wanted_ratings and not wanted_ratings.intersection(row_dimensions.get("rating", [])):
            continue
        if wanted_energy and not wanted_energy.intersection(row_dimensions.get("energy", [])):
            continue
        all_tags = {
            f"{dimension}:{value}"
            for dimension, values in row_dimensions.items()
            if dimension not in {"rating", "energy"}
            for value in values
        }
        if wanted_tags and not wanted_tags.intersection(all_tags):
            continue
        matched.append(row)
    return _date_sorted_page(matched, sort, limit, offset)


def collection_artist_summary(
    engine: Any, collection: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """Return top artists, filter options, BPM range, and the most common vibe."""
    kind = str(collection.get("type") or "liked")
    collection_id = str(collection.get("id") or "")
    if kind == "playlist":
        records = tidal_playlist_tracks_page(collection_id, limit=1_000_000)
    elif kind == "setlist":
        records = tidal_setlist_tracks_page(collection_id, limit=1_000_000)
    elif kind == "watched_mix":
        records = tidal_watched_mix_tracks_page(collection_id, limit=1_000_000)
    elif kind == "artist":
        records = tidal_artist_tracks_page(collection_id, limit=1_000_000)
    elif kind == "search":
        records = tidal_library_tracks_page(limit=1_000_000)
    else:
        user_id = latest_tidal_liked_user_id()
        records = tidal_liked_tracks_page(user_id, limit=1_000_000) if user_id else []
    artists = tidal_artists_for_tracks([str(record.get("id") or "") for record in records])
    counts: Counter[tuple[str, str]] = Counter()
    names: dict[str, str] = {}
    for track_artists in artists.values():
        for artist in track_artists:
            key = str(artist["id"])
            name = str(artist["name"])
            counts[(key, name)] += 1
            names[key] = name
    top = [
        {"id": key, "name": name, "count": count}
        for (key, name), count in counts.most_common(3)
    ]
    options = [
        {"label": name, "value": key}
        for key, name in sorted(names.items(), key=lambda item: item[1].casefold())
    ]
    bpms = []
    for record in records:
        try:
            bpm = float(record.get("bpm"))
        except (TypeError, ValueError):
            continue
        if bpm > 0:
            bpms.append(bpm)
    dimensions = tidal_dimensions_for_tracks(
        [str(record.get("id") or "") for record in records]
    )
    vibes = Counter(
        value
        for track_dimensions in dimensions.values()
        for value in track_dimensions.get("vibe", [])
    )
    stats = {
        "bpm_min": min(bpms) if bpms else None,
        "bpm_max": max(bpms) if bpms else None,
        "vibe": vibes.most_common(1)[0][0] if vibes else "",
        "vibe_count": vibes.most_common(1)[0][1] if vibes else 0,
    }
    return top, options, stats
