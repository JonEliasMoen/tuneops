from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import main as engine
from backend.music_tools.beatport.beatport import BeatportError, client
from backend.music_tools.liked_tracks.service import track_row

from ..schemas import BeatportChartReference
from ..services.library import matched_tidal_tracks_by_isrc
from ..services.navigation_cache import invalidate_navigation_snapshot


router = APIRouter(prefix="/charts", tags=["charts"])
SETTING_KEY = "beatport_followed_charts"
SEARCHABLE_TYPES = frozenset({"genres", "labels", "artists"})
CHART_TYPES = frozenset({*SEARCHABLE_TYPES, "tracks"})


def _valid_reference(row: dict[str, object]) -> bool:
    kind = row.get("type")
    identifier = row.get("id")
    return bool(
        kind in CHART_TYPES
        and identifier
        and (kind != "tracks" or identifier == "top")
    )


def _followed() -> list[dict[str, str]]:
    rows = engine.load_runtime_settings().get(SETTING_KEY) or []
    return [
        {"type": str(row.get("type")), "id": str(row.get("id")), "name": str(row.get("name"))}
        for row in rows
        if isinstance(row, dict) and _valid_reference(row)
        and row.get("name")
    ][:50]


def _save(rows: list[dict[str, str]]) -> None:
    config = engine.load_settings_config()
    config.setdefault("settings", {})[SETTING_KEY] = rows
    engine.save_settings_config(config)
    invalidate_navigation_snapshot()


@router.get("")
def followed_charts() -> dict[str, object]:
    return {"items": _followed()}


@router.get("/search")
def search_charts(
    type: str = Query(pattern="^(genres|labels|artists)$"),
    q: str = Query(min_length=1, max_length=200),
) -> dict[str, object]:
    try:
        return {"items": client.search(type, q, limit=25)}
    except BeatportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/tidal-match")
def search_tidal_by_isrc(
    isrc: str = Query(min_length=8, max_length=20),
) -> dict[str, object]:
    """Resolve one Beatport ISRC on explicit user action without indexing it."""
    normalized = "".join(character for character in isrc.upper() if character.isalnum())
    if len(normalized) != 12:
        raise HTTPException(status_code=422, detail="A valid 12-character ISRC is required.")
    try:
        session = engine.tidal_client(interactive=False)
        candidates = list(session.get_tracks_by_isrc(normalized) or [])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        engine.LOGGER.warning("beatport.tidal_isrc_lookup_failed error=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="TIDAL search is temporarily unavailable.") from exc
    exact = next(
        (
            track for track in candidates
            if "".join(
                character for character in str(getattr(track, "isrc", "") or "").upper()
                if character.isalnum()
            ) == normalized
        ),
        candidates[0] if candidates else None,
    )
    if exact is None:
        raise HTTPException(status_code=404, detail="No TIDAL track was found for this ISRC.")
    row = track_row(exact)
    track_id = str(row.get("id") or "")
    if not track_id:
        raise HTTPException(status_code=404, detail="No playable TIDAL track was found for this ISRC.")
    return {
        "isrc": normalized,
        "track": {
            "id": track_id,
            "title": str(row.get("title") or ""),
            "artist": str(row.get("artist") or ""),
            "tidal_uri": f"tidal://track/{track_id}",
        },
    }


@router.post("", status_code=201)
def follow_chart(body: BeatportChartReference) -> dict[str, object]:
    if body.type == "tracks" and body.id != "top":
        raise HTTPException(status_code=422, detail="Only the global Top Beatport tracks chart can be followed.")
    rows = _followed()
    key = (body.type, body.id)
    if not any((row["type"], row["id"]) == key for row in rows):
        if len(rows) >= 50:
            raise HTTPException(status_code=409, detail="At most 50 Beatport charts can be followed.")
        rows.append(body.model_dump())
        _save(rows)
    return {"items": rows}


@router.delete("/{type}/{entity_id}")
def unfollow_chart(
    type: str,
    entity_id: str,
) -> dict[str, object]:
    if type not in CHART_TYPES or (type == "tracks" and entity_id != "top"):
        raise HTTPException(status_code=404, detail="Chart type was not found.")
    rows = [row for row in _followed() if (row["type"], row["id"]) != (type, entity_id)]
    _save(rows)
    return {"items": rows}


@router.get("/{type}/{entity_id}")
def chart_detail(
    type: str,
    entity_id: str,
    mode: str = Query(default="top", pattern="^(top|recent)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=50),
) -> dict[str, object]:
    if type not in CHART_TYPES or (type == "tracks" and entity_id != "top"):
        raise HTTPException(status_code=404, detail="Chart type was not found.")
    if type == "tracks" and mode != "top":
        raise HTTPException(status_code=400, detail="Top Beatport only supports Top mode.")
    reference = next((row for row in _followed() if row["type"] == type and row["id"] == entity_id), None)
    try:
        if mode == "top":
            # Beatport's Top endpoint has a fixed ten-row provider page. Its
            # trailing `/100` selects the bounded chart, not the page size.
            provider_page_size = 10
            top = client.top_tracks(
                type,
                entity_id,
                page=offset // provider_page_size + 1,
                chart_size=100,
            )
            items = top["items"]
            for position, item in enumerate(items, start=offset + 1):
                item["position"] = position
            has_more = bool(top["has_more"])
            total = int(top["total"])
            limit = int(top["per_page"])
        else:
            page = offset // limit + 1
            recent = client.recent_tracks(
                type, entity_id, page=page, per_page=limit,
            )
            items = recent["items"]
            for position, item in enumerate(items, start=offset + 1):
                item["position"] = position
            has_more = bool(recent["has_more"])
            total = int(recent["total"])
    except BeatportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    matches = matched_tidal_tracks_by_isrc([
        str(item.get("isrc") or "") for item in items
    ])
    for item in items:
        normalized_isrc = str(item.get("isrc") or "").strip().upper().replace("-", "")
        item["tidal_track"] = matches.get(normalized_isrc)
    return {
        "chart": reference or {"type": type, "id": entity_id, "name": entity_id},
        "mode": mode,
        "items": items,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
    }
