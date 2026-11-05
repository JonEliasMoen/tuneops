from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import main as engine
from backend.music_tools.beatport.beatport import BeatportError, client
from backend.music_tools.tidal_matching import find_tidal_matches

from ..schemas import BeatportChartReference
from ..services.beatport_charts import (
    CHART_TYPES,
    SEARCHABLE_TYPES,
    SETTING_KEY,
    chart_page,
    followed_chart_references,
    valid_chart_reference,
)
from ..services.navigation_cache import invalidate_navigation_snapshot


router = APIRouter(prefix="/charts", tags=["charts"])
_valid_reference = valid_chart_reference
_followed = followed_chart_references


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
    try:
        return chart_page(type, entity_id, mode=mode, offset=offset, limit=limit)
    except BeatportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
