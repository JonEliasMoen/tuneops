"""Bounded read-only library adapters for MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import main as engine
from music_library.collection_query import collection_relationships
from music_library.connection import execute_batch
from music_library.credentials import current_user_id
from music_library.database import (
    DATABASE_PATH,
    connect_readonly,
    lastfm_track_stats,
    tidal_track_by_id,
)

from .library import collection_page, descriptor


READABLE_COLLECTION_TYPES = frozenset(
    {"liked", "playlist", "event", "source", "setlist", "watched_mix"}
)


class McpLibraryAccessError(RuntimeError):
    pass


def _require_library_owner(user_id: str) -> None:
    # The current library tables predate multi-user ownership. Until that
    # migration exists, only the stable owner of this deployment may read them.
    if str(user_id) != current_user_id():
        raise McpLibraryAccessError("This TuneOps user has no provisioned library")


def _bounded_limit(limit: int) -> int:
    return max(1, min(50, int(limit)))


def _offset(cursor: str | None) -> int:
    if cursor in (None, ""):
        return 0
    try:
        value = int(cursor)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cursor is invalid") from exc
    if value < 0:
        raise ValueError("Cursor is invalid")
    return value


def _collection_path(kind: str, collection_id: str) -> str:
    prefix = {
        "liked": "liked-tracks",
        "playlist": "playlists",
        "event": "events",
        "source": "sources",
        "setlist": "mixes",
        "watched_mix": "watched-mixes",
    }[kind]
    return f"/{prefix}" if kind == "liked" else f"/{prefix}/{quote(collection_id, safe='')}"


def _track_summary(row: dict[str, Any]) -> dict[str, Any]:
    relationships = {
        kind: [
            {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
            for item in row.get(field, [])
        ]
        for kind, field in (
            ("playlists", "playlists"),
            ("events", "events"),
            ("sources", "sources"),
            ("my_mixes", "mixes"),
            ("watched_mixes", "djmi"),
        )
        if row.get(field)
    }
    artists = [str(item.get("name") or "") for item in row.get("artists", [])]
    return {
        "tidal_track_id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "remix": str(row.get("remix") or ""),
        "artists": artists or [str(row.get("artist") or "")],
        "album": str(row.get("album") or ""),
        "year": row.get("year"),
        "bpm": row.get("bpm"),
        "key": str(row.get("key") or row.get("musical_key") or ""),
        "rating": (row.get("dimensions") or {}).get("rating", []),
        "tags": {
            key: list(values)
            for key, values in (row.get("dimensions") or {}).items()
            if key != "rating"
        },
        "lastfm_plays": row.get("play_count"),
        "memberships": relationships,
        "tidal_uri": f"tidal://track/{row.get('id')}",
    }


def search_tracks(
    user_id: str,
    query: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
) -> dict[str, Any]:
    _require_library_owner(user_id)
    page_limit = _bounded_limit(limit)
    offset = _offset(cursor)
    page = collection_page(
        "search",
        "library",
        offset=offset,
        limit=page_limit,
        query=str(query or "").strip(),
        bpm_min=bpm_min,
        bpm_max=bpm_max,
    )
    return {
        "tracks": [_track_summary(row) for row in page["items"]],
        "total": int(page["total"]),
        "next_cursor": str(offset + len(page["items"])) if page["has_more"] else None,
    }


def get_track(user_id: str, track_id: str) -> dict[str, Any] | None:
    _require_library_owner(user_id)
    normalized_id = str(track_id or "").strip()
    track = tidal_track_by_id(normalized_id)
    if not track:
        return None
    relationships = collection_relationships([normalized_id]).get(normalized_id, {})
    row = {**track, **relationships}
    username = str(engine.load_runtime_settings().get("lastfm_username", "") or "")
    listening = lastfm_track_stats(username, [normalized_id]).get(normalized_id, {})
    row["play_count"] = listening.get("play_count")
    return _track_summary(row)


def list_collections(
    user_id: str,
    *,
    kind: str = "",
    query: str = "",
    limit: int = 20,
    cursor: str | None = None,
    path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    _require_library_owner(user_id)
    normalized_kind = str(kind or "").strip()
    if normalized_kind and normalized_kind not in READABLE_COLLECTION_TYPES:
        raise ValueError("Collection type is invalid")
    with connect_readonly(path) as connection:
        playlist_cursor, setlist_cursor, watched_cursor, liked_cursor = execute_batch(
            connection,
            [
                (
                    """
                    SELECT p.provider_playlist_id AS id, p.name, p.collection_type AS type,
                           COUNT(pt.provider_track_id) AS track_count
                    FROM playlists p
                    LEFT JOIN playlist_tracks pt
                      ON pt.provider=p.provider
                     AND pt.provider_playlist_id=p.provider_playlist_id
                    WHERE p.provider='tidal'
                    GROUP BY p.provider_playlist_id, p.name, p.collection_type
                    """,
                    (),
                ),
                (
                    """
                    SELECT s.folder_name AS id,
                           COALESCE(NULLIF(s.tidal_playlist_name, ''), s.folder_name) AS name,
                           'setlist' AS type, COUNT(st.provider_track_id) AS track_count
                    FROM setlists s
                    LEFT JOIN setlist_tracks st ON st.folder_name=s.folder_name
                    GROUP BY s.folder_name, s.tidal_playlist_name
                    """,
                    (),
                ),
                (
                    """
                    SELECT wm.video_id AS id,
                           COALESCE(NULLIF(wm.title, ''), wm.video_id) AS name,
                           'watched_mix' AS type,
                           COUNT(wmt.provider_track_id) AS track_count
                    FROM watched_mixes wm
                    LEFT JOIN watched_mix_tracks wmt ON wmt.video_id=wm.video_id
                    GROUP BY wm.video_id, wm.title
                    """,
                    (),
                ),
                (
                    """
                    SELECT COUNT(DISTINCT provider_track_id) AS track_count
                    FROM liked_tracks
                    WHERE provider='tidal'
                    """,
                    (),
                ),
            ],
        )
        rows = [
            *playlist_cursor.fetchall(),
            *setlist_cursor.fetchall(),
            *watched_cursor.fetchall(),
        ]
        liked = liked_cursor.fetchone()
    items = [
        {
            "id": str(row["id"]),
            "name": str(row["name"] or row["id"]),
            "type": str(row["type"] or "playlist"),
            "track_count": int(row["track_count"] or 0),
        }
        for row in rows
    ]
    items.append({
        "id": "liked",
        "name": "TIDAL liked tracks",
        "type": "liked",
        "track_count": int(liked["track_count"] or 0) if liked else 0,
    })
    needle = str(query or "").strip().casefold()
    items = [
        item
        for item in items
        if (not normalized_kind or item["type"] == normalized_kind)
        and (not needle or needle in item["name"].casefold())
    ]
    items.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    offset = _offset(cursor)
    page_limit = _bounded_limit(limit)
    selected = items[offset : offset + page_limit]
    for item in selected:
        item["writable"] = item["type"] == "playlist"
        item["path"] = _collection_path(item["type"], item["id"])
    return {
        "collections": selected,
        "total": len(items),
        "next_cursor": str(offset + len(selected)) if offset + len(selected) < len(items) else None,
    }


def get_collection_tracks(
    user_id: str,
    kind: str,
    collection_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    sort_field: str = "",
    sort_direction: str = "",
) -> dict[str, Any]:
    _require_library_owner(user_id)
    normalized_kind = str(kind or "").strip()
    if normalized_kind not in READABLE_COLLECTION_TYPES:
        raise ValueError("Collection type is invalid")
    collection = descriptor(normalized_kind, str(collection_id or "").strip())
    page_limit = _bounded_limit(limit)
    offset = _offset(cursor)
    page = collection_page(
        normalized_kind,
        collection["id"],
        offset=offset,
        limit=page_limit,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )
    return {
        "collection": {
            **collection,
            "path": _collection_path(normalized_kind, collection["id"]),
        },
        "tracks": [_track_summary(row) for row in page["items"]],
        "total": int(page["total"]),
        "next_cursor": str(offset + len(page["items"])) if page["has_more"] else None,
    }


def get_track_memberships(user_id: str, track_ids: list[str]) -> dict[str, Any]:
    _require_library_owner(user_id)
    unique_ids = list(dict.fromkeys(str(value).strip() for value in track_ids if str(value).strip()))
    if not unique_ids or len(unique_ids) > 50:
        raise ValueError("Provide between 1 and 50 track IDs")
    related = collection_relationships(unique_ids)
    return {
        "tracks": [
            {
                "tidal_track_id": track_id,
                "memberships": {
                    key: value
                    for key, value in related.get(track_id, {}).items()
                    if key in {"playlists", "events", "sources", "mixes", "djmi"}
                },
            }
            for track_id in unique_ids
        ]
    }
