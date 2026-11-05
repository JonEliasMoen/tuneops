from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import main as engine
from backend.music_tools.beatport.beatport import BeatportError, client
from backend.music_tools.tidal_matching import find_tidal_matches

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
def search_tidal_by_artist_and_track(
    artists: str = Query(..., description="Artist name(s)", max_length=100),
    track: str = Query(..., description="Track title", max_length=100)
) -> dict[str, object]:
    """Søker på TIDAL ved å bruke separate artist- og spor-paramtere, og returnerer beste treff basert på vektet poengsum."""
    
    # 1. Forbered input-data i tråd med forventet 'row'-format
    row_input = {
        "artist": artists.strip(),
        "title": track.strip()
    }
    
    if not row_input["artist"] or not row_input["title"]:
        raise HTTPException(
            status_code=400,
            detail="Både 'artists' og 'track' må inneholde tekst."
        )

    try:
        session = engine.tidal_client(interactive=False)
        # 2. Kall den importerte match-funksjonen som håndterer søk og poengberegning
        candidates = find_tidal_matches(engine=engine, session=session, row=row_input, limit=5)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        engine.LOGGER.warning("beatport.tidal_search_failed error=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="TIDAL-søk er midlertidig utilgjengelig.") from exc

    # 3. Sjekk om vi fikk noen treff overhodet
    if not candidates:
        raise HTTPException(status_code=404, detail="Ingen TIDAL-spor ble funnet for dette søket.")

    # Siden find_tidal_matches sorterer etter høyest score, er det første elementet det beste treffet
    best_match = candidates[0]
    track_id = str(best_match.get("id") or "")
    
    if not track_id:
        raise HTTPException(status_code=404, detail="Fant ingen spillbare TIDAL-spor for dette søket.")

    # 4. Returner strukturert data i henhold til API-kontrakten
    return {
        "query": f"{row_input['artist']} - {row_input['title']}",
        "track": {
            "id": track_id,
            "title": str(best_match.get("title") or ""),
            "artist": str(best_match.get("artist") or ""),
            "tidal_uri": f"tidal://track/{track_id}",
            "isrc": str(best_match.get("isrc") or ""),
            "match_score": best_match.get("score", 0)  # Inkludert for enklere debugging av treffsikkerhet
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
