"""SQLite-only collection queries used by the FastAPI track browser."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import main as engine
from music_library.database import (
    lastfm_track_stats,
    latest_tidal_liked_user_id,
    tidal_artist,
    tidal_artists_for_tracks,
    tidal_dimensions_for_tracks,
    tidal_indexed_playlists,
    tidal_playlists_for_tracks,
    tidal_setlists_for_tracks,
    tidal_watched_mixes_for_tracks,
    watched_mix,
)
from music_tools.liked_tracks.service import (
    fetch_artist_tracks,
    fetch_indexed_playlist_tracks,
    fetch_indexed_setlist_tracks,
    fetch_library_tracks,
    fetch_liked_tracks,
    fetch_watched_mix_tracks,
)
from music_tools.mixes.service import mix_for


COLLECTION_TYPES = {
    "liked", "playlist", "event", "source", "setlist", "watched_mix", "artist", "search"
}
NUMERIC_SORT_FIELDS = {"bpm", "year", "play_count"}


class CollectionNotFound(LookupError):
    pass


def descriptor(kind: str, collection_id: str = "") -> dict[str, str]:
    if kind not in COLLECTION_TYPES:
        raise CollectionNotFound(f"Unknown collection type: {kind}")
    if kind == "liked":
        return {"type": "liked", "id": "liked", "name": "TIDAL liked tracks", "collection_type": ""}
    if kind == "search":
        return {"type": "search", "id": "library", "name": "Global search", "collection_type": ""}
    if kind in {"playlist", "event", "source"}:
        item = next(
            (row for row in tidal_indexed_playlists() if str(row.get("id")) == collection_id),
            None,
        )
        if not item or str(item.get("collection_type") or "playlist") != kind:
            raise CollectionNotFound("Indexed playlist was not found in that section")
        return {
            "type": kind,
            "id": collection_id,
            "name": str(item.get("name") or collection_id),
            "collection_type": kind,
        }
    if kind == "artist":
        item = tidal_artist(collection_id)
        if not item:
            raise CollectionNotFound("Artist was not found")
        return {"type": "artist", "id": collection_id, "name": str(item.get("name") or collection_id), "collection_type": ""}
    if kind == "setlist":
        item = mix_for(collection_id)
        if not item:
            raise CollectionNotFound("Mix was not found")
        return {"type": "setlist", "id": collection_id, "name": item.folder_name, "collection_type": ""}
    item = watched_mix(collection_id)
    if not item:
        raise CollectionNotFound("Watched mix was not found")
    return {"type": "watched_mix", "id": collection_id, "name": str(item.get("title") or collection_id), "collection_type": ""}


def _base_rows(kind: str, collection_id: str) -> list[dict[str, Any]]:
    limit = 1_000_000
    if kind == "liked":
        rows, _ = fetch_liked_tracks(engine, limit=limit)
    elif kind in {"playlist", "event", "source"}:
        rows, _ = fetch_indexed_playlist_tracks(collection_id, limit=limit)
    elif kind == "setlist":
        rows, _ = fetch_indexed_setlist_tracks(collection_id, limit=limit)
    elif kind == "watched_mix":
        rows, _ = fetch_watched_mix_tracks(collection_id, limit=limit)
    elif kind == "artist":
        rows, _ = fetch_artist_tracks(collection_id, limit=limit)
    elif kind == "search":
        rows, _ = fetch_library_tracks(limit=limit)
    else:
        raise CollectionNotFound(f"Unknown collection type: {kind}")
    return [dict(row) for row in rows]


def _attach_related(rows: list[dict[str, Any]], collection: dict[str, str]) -> None:
    track_ids = [str(row.get("id") or "") for row in rows]
    playlists = tidal_playlists_for_tracks(track_ids)
    setlists = tidal_setlists_for_tracks(track_ids)
    watched = tidal_watched_mixes_for_tracks(track_ids)
    artists = tidal_artists_for_tracks(track_ids)
    dimensions = tidal_dimensions_for_tracks(track_ids)
    username = str(engine.load_config().get("settings", {}).get("lastfm_username", "") or "").strip()
    listening = lastfm_track_stats(username, track_ids) if username else {}
    current_type = collection["type"]
    current_id = collection["id"]
    for source_order, row in enumerate(rows):
        track_id = str(row.get("id") or "")
        grouped: dict[str, list[dict[str, str]]] = {"playlist": [], "event": [], "source": []}
        for membership in playlists.get(track_id, []):
            kind = str(membership.get("collection_type") or "playlist")
            if current_type == kind and str(membership.get("id") or "") == current_id:
                continue
            grouped.setdefault(kind, []).append(membership)
        row["playlists"] = grouped["playlist"]
        row["events"] = grouped["event"]
        row["sources"] = grouped["source"]
        row["mixes"] = [
            item for item in setlists.get(track_id, [])
            if not (current_type == "setlist" and str(item.get("id") or "") == current_id)
        ]
        row["djmi"] = [
            item for item in watched.get(track_id, [])
            if not (current_type == "watched_mix" and str(item.get("id") or "") == current_id)
        ]
        row["artists"] = artists.get(track_id, [])
        row["dimensions"] = dimensions.get(track_id, {})
        row["play_count"] = int(listening.get(track_id, {}).get("play_count", 0)) if username else 0
        last_played = listening.get(track_id, {}).get("last_played")
        row["last_played"] = (
            datetime.fromtimestamp(int(last_played)).strftime("%Y-%m-%d %H:%M")
            if last_played else ""
        )
        row["tidal_uri"] = f"tidal://track/{track_id}"
        row["_source_order"] = source_order


def _matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    query = " ".join(str(filters.get("query") or "").casefold().split())
    if query:
        fields = [row.get("title"), row.get("remix")]
        if filters.get("global_text"):
            fields.extend([row.get("artist"), row.get("album")])
        if query not in " ".join(str(value or "") for value in fields).casefold():
            return False
    artist_ids = set(filters.get("artists") or [])
    if artist_ids and not artist_ids.intersection(str(item.get("id")) for item in row.get("artists", [])):
        return False
    keys = set(filters.get("keys") or [])
    if keys and str(row.get("key") or "") not in keys:
        return False
    try:
        bpm = float(row.get("bpm"))
    except (TypeError, ValueError):
        bpm = None
    if filters.get("bpm_min") is not None and (bpm is None or bpm < filters["bpm_min"]):
        return False
    if filters.get("bpm_max") is not None and (bpm is None or bpm > filters["bpm_max"]):
        return False
    dimensions = row.get("dimensions") or {}
    ratings = set(filters.get("ratings") or [])
    if ratings and not ratings.intersection(dimensions.get("rating", [])):
        return False
    tags = set(filters.get("tags") or [])
    row_tags = {
        f"{dimension}:{value}"
        for dimension, values in dimensions.items()
        for value in values
    }
    if tags and not tags.intersection(row_tags):
        return False
    membership_fields = {"playlist": "playlists", "event": "events", "source": "sources", "mix": "mixes", "watched_mix": "djmi"}
    types = set(filters.get("collection_types") or [])
    return not types or any(bool(row.get(membership_fields[item])) for item in types if item in membership_fields)


def _sort_value(row: dict[str, Any], field: str) -> Any:
    if field in NUMERIC_SORT_FIELDS:
        try:
            return float(row.get(field))
        except (TypeError, ValueError):
            return None
    if field == "date_added":
        value = row.get("_date_added_sort")
        if value:
            return float(value)
    if field == "length":
        value = str(row.get("length") or "").strip()
        try:
            parts = [int(part) for part in value.split(":")]
        except ValueError:
            return None
        if len(parts) not in {2, 3} or any(part < 0 for part in parts):
            return None
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds
    if field in {"rating", "energy", "tension", "vibe", "movement", "driver", "function", "structure", "texture", "scale"}:
        values = (row.get("dimensions") or {}).get(field, [])
        return " | ".join(values).casefold() if values else None
    if field in {"playlists", "events", "sources", "mixes", "djmi"}:
        values = row.get(field) or []
        return " | ".join(str(item.get("name") or "") for item in values).casefold() if values else None
    value = row.get(field)
    return str(value).casefold() if value not in (None, "") else None


def _sort(rows: list[dict[str, Any]], field: str, direction: str) -> list[dict[str, Any]]:
    if not field or direction not in {"asc", "desc"}:
        return sorted(rows, key=lambda row: int(row.get("_source_order", 0)))
    present = [row for row in rows if _sort_value(row, field) is not None]
    missing = [row for row in rows if _sort_value(row, field) is None]
    present.sort(key=lambda row: _sort_value(row, field), reverse=direction == "desc")
    return [*present, *missing]


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    artist_counts: Counter[tuple[str, str]] = Counter()
    bpms: list[float] = []
    vibes: Counter[str] = Counter()
    artists: dict[str, str] = {}
    for row in rows:
        for artist in row.get("artists", []):
            pair = (str(artist.get("id") or ""), str(artist.get("name") or ""))
            if all(pair):
                artist_counts[pair] += 1
                artists[pair[0]] = pair[1]
        try:
            bpm = float(row.get("bpm"))
            if bpm > 0:
                bpms.append(bpm)
        except (TypeError, ValueError):
            pass
        vibes.update((row.get("dimensions") or {}).get("vibe", []))
    top_vibe = vibes.most_common(1)
    return {
        "top_artists": [
            {"id": key, "name": name, "count": count}
            for (key, name), count in artist_counts.most_common(3)
        ],
        "artist_options": [
            {"label": name, "value": key}
            for key, name in sorted(artists.items(), key=lambda item: item[1].casefold())
        ],
        "bpm_min": min(bpms) if bpms else None,
        "bpm_max": max(bpms) if bpms else None,
        "vibe": top_vibe[0][0] if top_vibe else "",
        "vibe_count": top_vibe[0][1] if top_vibe else 0,
    }


def collection_page(
    kind: str,
    collection_id: str,
    *,
    offset: int,
    limit: int,
    sort_field: str = "",
    sort_direction: str = "",
    query: str = "",
    artists: list[str] | None = None,
    keys: list[str] | None = None,
    ratings: list[str] | None = None,
    tags: list[str] | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    collection_types: list[str] | None = None,
) -> dict[str, Any]:
    collection = descriptor(kind, collection_id)
    rows = _base_rows(kind, collection_id)
    _attach_related(rows, collection)
    filters = {
        "query": query,
        "global_text": kind == "search",
        "artists": artists or [],
        "keys": keys or [],
        "ratings": ratings or [],
        "tags": tags or [],
        "bpm_min": bpm_min,
        "bpm_max": bpm_max,
        "collection_types": collection_types or [],
    }
    rows = [row for row in rows if _matches(row, filters)]
    stats = _stats(rows)
    rows = _sort(rows, sort_field, sort_direction)
    total = len(rows)
    items = rows[offset : offset + limit]
    return {
        "collection": collection,
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "stats": stats,
    }


def liked_cache_available() -> bool:
    return latest_tidal_liked_user_id() is not None
