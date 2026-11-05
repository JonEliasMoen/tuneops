"""Bounded TuneOps/TIDAL adapters exposed through MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import main as engine
from backend.music_library.collection_query import collection_relationships, execute_batch
from backend.music_library.credentials import current_user_id
from backend.music_library.database import (
    DATABASE_PATH,
    connect_readonly,
    lastfm_track_stats,
    tidal_track_record,
    tidal_track_by_id,
    youtube_video_metadata,
)
from backend.music_tools.mixes.service import (
    Mix,
    discover_mixes,
    mix_for,
    youtube_thumbnail_url,
    youtube_video_id,
)
from backend.music_tools.beatport.beatport import BEATPORT_CACHE_SECONDS

from .actions import TrackActionError, mutate_playlist_tracks
from .beatport_charts import chart_page, followed_chart_references
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


def _chart_path(chart_type: str, chart_id: str) -> str:
    return f"/charts/{quote(chart_type, safe='')}/{quote(chart_id, safe='')}"


def _chart_track_summary(row: dict[str, Any]) -> dict[str, Any]:
    tidal_track = row.get("tidal_track") or {}
    tidal_track_id = str(tidal_track.get("id") or "")
    return {
        "position": int(row.get("position") or 0),
        "beatport_track_id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "mix": str(row.get("mix") or ""),
        "artists": list(row.get("artist_refs") or []),
        "artist_text": str(row.get("artists") or ""),
        "bpm": row.get("bpm"),
        "key": str(row.get("key") or ""),
        "label": {
            "id": str(row.get("label_id") or ""),
            "name": str(row.get("label") or ""),
        },
        "genre": {
            "id": str(row.get("genre_id") or ""),
            "name": str(row.get("genre") or ""),
        },
        "isrc": str(row.get("isrc") or ""),
        "release_date": str(row.get("release_date") or ""),
        "exclusive": bool(row.get("exclusive")),
        "tidal_match": (
            {
                "tidal_track_id": tidal_track_id,
                "title": str(tidal_track.get("title") or ""),
                "artist": str(tidal_track.get("artist") or ""),
                "tidal_uri": f"tidal://track/{tidal_track_id}",
            }
            if tidal_track_id
            else None
        ),
    }


def list_followed_charts(user_id: str) -> dict[str, Any]:
    """Return the deployment owner's bounded followed Beatport chart list."""
    _require_library_owner(user_id)
    charts = followed_chart_references()
    return {
        "charts": [
            {**chart, "path": _chart_path(chart["type"], chart["id"])}
            for chart in charts
        ],
        "total": len(charts),
    }


def get_chart_tracks(
    user_id: str,
    chart_type: str,
    chart_id: str,
    *,
    mode: str = "top",
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded followed-chart page through the shared Beatport cache."""
    _require_library_owner(user_id)
    normalized_type = str(chart_type or "").strip()
    normalized_id = str(chart_id or "").strip()
    followed = next(
        (
            chart
            for chart in followed_chart_references()
            if chart["type"] == normalized_type and chart["id"] == normalized_id
        ),
        None,
    )
    if followed is None:
        raise ValueError("Chart is not followed")
    offset = _offset(cursor)
    page = chart_page(
        normalized_type,
        normalized_id,
        mode=mode,
        offset=offset,
        limit=_bounded_limit(limit),
        reference=followed,
    )
    items = list(page["items"])
    return {
        "chart": {**followed, "path": _chart_path(normalized_type, normalized_id)},
        "mode": page["mode"],
        "tracks": [_chart_track_summary(row) for row in items],
        "total": int(page["total"]),
        "next_cursor": str(offset + len(items)) if page["has_more"] else None,
        "cache": {
            "provider": "beatport",
            "shared": True,
            "ttl_seconds": int(BEATPORT_CACHE_SECONDS),
        },
    }


def refresh_chart(
    user_id: str,
    chart_type: str,
    chart_id: str,
    *,
    mode: str = "top",
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Load a chart page cache-first; expired entries are refreshed from Beatport."""
    return get_chart_tracks(
        user_id,
        chart_type,
        chart_id,
        mode=mode,
        limit=limit,
        cursor=cursor,
    )


def search_tracks(
    user_id: str,
    query: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
) -> dict[str, Any]:
    """Search the live TIDAL catalog and return IDs usable by write tools."""
    _require_library_owner(user_id)
    page_limit = _bounded_limit(limit)
    offset = _offset(cursor)
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("A TIDAL search query is required")

    import tidalapi

    session = engine.tidal_client(interactive=False)
    response = engine._call(
        "tidal",
        "mcp_search_tracks",
        lambda: session.search(
            normalized_query,
            models=[tidalapi.Track],
            limit=page_limit,
            offset=offset,
        ),
        # Never log the user-entered query; only bounded request metadata.
        limit=page_limit,
        offset=offset,
    )
    provider_tracks = list((response or {}).get("tracks", []))
    records = [tidal_track_record(track) for track in provider_tracks]
    if bpm_min is not None:
        records = [
            row for row in records
            if row.get("bpm") is not None and float(row["bpm"]) >= float(bpm_min)
        ]
    if bpm_max is not None:
        records = [
            row for row in records
            if row.get("bpm") is not None and float(row["bpm"]) <= float(bpm_max)
        ]
    return {
        "source": "tidal",
        "tracks": [_track_summary(row) for row in records],
        "result_count": len(records),
        # TIDAL does not expose a total here. A full page means another page may exist.
        "next_cursor": str(offset + page_limit) if len(provider_tracks) == page_limit else None,
    }


def add_tracks_to_playlist(
    user_id: str,
    playlist_id: str,
    tidal_track_ids: list[str],
) -> dict[str, Any]:
    """Add exact indexed TIDAL tracks through the shared provider-first action."""
    _require_library_owner(user_id)
    unique_ids = list(
        dict.fromkeys(
            str(value).strip() for value in tidal_track_ids if str(value).strip()
        )
    )
    if not unique_ids or len(unique_ids) > 50:
        raise ValueError("Provide between 1 and 50 TIDAL track IDs")
    normalized_playlist_id = str(playlist_id or "").strip()
    if not normalized_playlist_id:
        raise ValueError("A destination playlist ID is required")
    try:
        return mutate_playlist_tracks("add", unique_ids, normalized_playlist_id)
    except TrackActionError as exc:
        raise McpLibraryAccessError(str(exc)) from exc


def remove_tracks_from_collection(
    user_id: str,
    playlist_id: str,
    tidal_track_ids: list[str],
) -> dict[str, Any]:
    """Remove exact tracks from an indexed TIDAL-backed collection."""
    _require_library_owner(user_id)
    unique_ids = list(
        dict.fromkeys(
            str(value).strip() for value in tidal_track_ids if str(value).strip()
        )
    )
    if not unique_ids or len(unique_ids) > 50:
        raise ValueError("Provide between 1 and 50 TIDAL track IDs")
    normalized_playlist_id = str(playlist_id or "").strip()
    if not normalized_playlist_id:
        raise ValueError("A collection playlist ID is required")
    try:
        return mutate_playlist_tracks("remove", unique_ids, normalized_playlist_id)
    except TrackActionError as exc:
        raise McpLibraryAccessError(str(exc)) from exc


def move_tracks_between_playlists(
    user_id: str,
    source_playlist_id: str,
    destination_playlist_id: str,
    tidal_track_ids: list[str],
) -> dict[str, Any]:
    """Move exact tracks provider-first, with rollback if source removal fails."""
    _require_library_owner(user_id)
    unique_ids = list(
        dict.fromkeys(
            str(value).strip() for value in tidal_track_ids if str(value).strip()
        )
    )
    if not unique_ids or len(unique_ids) > 50:
        raise ValueError("Provide between 1 and 50 TIDAL track IDs")
    source_id = str(source_playlist_id or "").strip()
    destination_id = str(destination_playlist_id or "").strip()
    if not source_id or not destination_id:
        raise ValueError("Source and destination playlist IDs are required")
    try:
        return mutate_playlist_tracks(
            "move", unique_ids, destination_id, source_playlist_id=source_id
        )
    except TrackActionError as exc:
        raise McpLibraryAccessError(str(exc)) from exc


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
        # Playlists, Events, and Sources are all indexed TIDAL playlists. The
        # collection type controls TuneOps presentation, not provider writability.
        item["writable"] = item["type"] in {"playlist", "event", "source"}
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
    effective_sort_field = sort_field
    effective_sort_direction = sort_direction
    if normalized_kind == "liked" and not str(sort_field or "").strip():
        effective_sort_field = "date_added"
        effective_sort_direction = "desc"
    page = collection_page(
        normalized_kind,
        collection["id"],
        offset=offset,
        limit=page_limit,
        sort_field=effective_sort_field,
        sort_direction=effective_sort_direction,
    )
    return {
        "collection": {
            **collection,
            "path": _collection_path(normalized_kind, collection["id"]),
        },
        "tracks": [_track_summary(row) for row in page["items"]],
        "total": int(page["total"]),
        "ordering": (
            "newest_liked_first" if normalized_kind == "liked" else "collection_order"
        ),
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


def _mix_summary(mix: Mix, video_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    video_id = youtube_video_id(mix.youtube_url) or ""
    public_metadata = video_metadata.get(video_id, {})
    return {
        "mix_id": mix.folder_name,
        "name": mix.folder_name,
        "track_count": mix.track_count,
        "tidal_playlist_id": mix.tidal_playlist_id,
        "tidal_playlist_name": mix.tidal_playlist_name,
        "tidal_url": mix.tidal_url,
        "youtube_url": mix.youtube_url,
        "youtube_video_id": video_id,
        "youtube_title": str(public_metadata.get("title") or ""),
        "youtube_upload_date": str(public_metadata.get("upload_date") or ""),
        "youtube_cover_url": youtube_thumbnail_url(mix.youtube_url),
        "analytics": {
            "views": mix.youtube_views,
            "watch_minutes": mix.youtube_watch_minutes,
            "average_view_duration_seconds": mix.youtube_average_view_duration,
            "average_view_percentage": mix.youtube_average_view_percentage,
            "likes": mix.youtube_likes,
            "comments": mix.youtube_comments,
            "subscribers_gained": mix.youtube_subscribers_gained,
            "thumbnail_impressions": mix.youtube_thumbnail_impressions,
            "thumbnail_ctr": mix.youtube_thumbnail_ctr,
            "fetched_at": mix.youtube_analytics_fetched_at,
        },
        "updated_at": mix.updated_at,
    }


def list_my_mixes(
    user_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one bounded page of cached, user-owned My Mix metadata."""
    _require_library_owner(user_id)
    page_limit = _bounded_limit(limit)
    offset = _offset(cursor)
    mixes = sorted(discover_mixes(), key=lambda item: item.folder_name.casefold())
    selected = mixes[offset : offset + page_limit]
    metadata = youtube_video_metadata()
    return {
        "mixes": [_mix_summary(mix, metadata) for mix in selected],
        "total": len(mixes),
        "next_cursor": (
            str(offset + len(selected))
            if offset + len(selected) < len(mixes)
            else None
        ),
    }


def get_my_mix(
    user_id: str,
    mix_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any] | None:
    """Return one exact mix and a bounded ordered page of its cached tracks."""
    _require_library_owner(user_id)
    normalized_id = str(mix_id or "").strip()
    if not normalized_id:
        raise ValueError("A My Mix ID is required")
    mix = mix_for(normalized_id)
    if mix is None:
        return None
    tracks = get_collection_tracks(
        user_id,
        "setlist",
        mix.folder_name,
        limit=limit,
        cursor=cursor,
    )
    return {
        "mix": _mix_summary(mix, youtube_video_metadata()),
        "tracks": tracks["tracks"],
        "track_total": tracks["total"],
        "next_cursor": tracks["next_cursor"],
    }
