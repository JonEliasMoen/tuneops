from __future__ import annotations

import os
import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

import main as engine
from backend.music_library.database import lastfm_import_summary
from backend.music_library.database import pending_track, pending_tracks, update_pending_track_candidates, watched_mix
from backend.music_tools.lastfm.service import import_scrobbles
from backend.music_tools.mixes.service import discover_tidal_mixes, import_tidal_setlist, mix_for
from backend.music_tools.tidal_matching import find_tidal_matches

from ..config import number_setting
from ..jobs import JOBS
from ..schemas import JobResponse, MixTidalImportRequest, TracklistSearchRequest
from ..services.library import CollectionNotFound, descriptor
from ..services.mix_export import export_mix_to_spotify
from ..services.navigation_cache import invalidate_navigation_snapshot


router = APIRouter(tags=["jobs"])


def _pending_match_status(candidates: list[dict[str, object]]) -> str:
    if not candidates:
        return "not_found"
    return "matched" if int(candidates[0].get("score", 0) or 0) >= 8 else "ambiguous"


@router.get("/jobs/{job_id}", response_model=JobResponse)
def job(job_id: str) -> JobResponse:
    record = JOBS.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job was not found")
    return JobResponse.model_validate(record)


@router.post("/sync/run", response_model=JobResponse, status_code=202)
def run_sync() -> JobResponse:
    def execute(progress):
        result = [asdict(item) for item in engine.run_all_syncs(progress=progress)]
        invalidate_navigation_snapshot()
        return result

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("playlist-sync", execute)))


@router.get("/lastfm/status")
def lastfm_status() -> dict[str, object]:
    username = str(engine.load_runtime_settings().get("lastfm_username", "") or "").strip()
    return {
        "username": username,
        "api_key_configured": bool(os.getenv("LASTFM_API_KEY", "").strip()),
        **lastfm_import_summary(username),
    }


@router.post("/lastfm/import", response_model=JobResponse, status_code=202)
def run_lastfm_import() -> JobResponse:
    settings = engine.load_runtime_settings()
    username = str(settings.get("lastfm_username", "") or "").strip()
    api_key = os.getenv("LASTFM_API_KEY", "")

    def execute(progress):
        result = import_scrobbles(
            username,
            api_key,
            delay_seconds=number_setting(
                settings, "lastfm_import_delay_seconds", 0.5, minimum=0,
            ),
            progress=progress,
        )
        invalidate_navigation_snapshot()
        return result

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("lastfm-import", execute)))


@router.post(
    "/collections/{kind}/{collection_id}/refresh",
    response_model=JobResponse,
    status_code=202,
)
def refresh_collection(kind: str, collection_id: str, force: bool = False) -> JobResponse:
    """Refresh provider-backed caches without blocking the SQLite track view."""
    if kind not in {"liked", "playlist", "event", "source"}:
        raise HTTPException(status_code=400, detail="This collection is SQLite-only")
    try:
        collection = descriptor(kind, collection_id)
    except CollectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def execute(progress):
        if kind == "liked":
            progress("Checking recent TIDAL likes")
            tidal = engine.tidal_client(interactive=False)
            result = engine.maintain_tidal_liked_tracks(
                tidal,
                engine.load_runtime_settings(),
                progress=progress,
            )
            engine.backfill_new_lastfm_tracks(progress)
        else:
            progress(f"Checking {collection['name']} on TIDAL")
            result = engine.refresh_tidal_playlist_cache(collection_id, force=force)
        invalidate_navigation_snapshot()
        return result

    job_kind = f"collection-refresh:{kind}:{collection_id}"
    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit(job_kind, execute)))


@router.post("/mixes/{folder_name}/import-tidal", response_model=JobResponse, status_code=202)
def import_mix_tidal_setlist(folder_name: str, body: MixTidalImportRequest) -> JobResponse:
    mix = mix_for(folder_name)
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix was not found")

    def execute(progress):
        progress(f"Importing TIDAL setlist for {mix.folder_name}")
        playlist, tracks = import_tidal_setlist(engine, mix, body.tidal_url)
        playlist_name = str(getattr(playlist, "name", "") or "")
        progress(f"Stored {len(tracks)} tracks from {playlist_name or 'the TIDAL playlist'}")
        invalidate_navigation_snapshot()
        return {"playlist_name": playlist_name, "tracks": len(tracks)}

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit(f"mix-tidal-import:{folder_name}", execute))
    )


@router.post(
    "/mixes/{folder_name}/export-spotify",
    response_model=JobResponse,
    status_code=202,
)
def export_mix_spotify(folder_name: str) -> JobResponse:
    """Create one Spotify playlist without adding a Playlist Sync mapping."""
    mix = mix_for(folder_name)
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix was not found")
    if not (mix.tidal_playlist_id or mix.tidal_url):
        raise HTTPException(
            status_code=409,
            detail="Import a TIDAL setlist before exporting this mix to Spotify",
        )

    def execute(progress):
        return export_mix_to_spotify(mix, progress=progress)

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit(f"mix-spotify-export:{folder_name}", execute))
    )


@router.post("/mixes/discover-tidal", response_model=JobResponse, status_code=202)
def discover_tidal_mix_setlists() -> JobResponse:
    def execute(progress):
        result = discover_tidal_mixes(engine, progress=progress)
        attention = sum(
            row.get("status") in {"ambiguous", "name_conflict", "empty", "failed"}
            for row in result["results"]
        )
        suffix = f"; {attention} need attention" if attention else ""
        progress(
            f"Discovery complete: {result['imported']} new of "
            f"{result['candidates']} djset playlists imported{suffix}"
        )
        if result["imported"]:
            invalidate_navigation_snapshot()
        return result

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit("mix-tidal-discovery", execute))
    )


@router.post(
    "/watched-mixes/{video_id}/tracklist/search",
    response_model=JobResponse,
    status_code=202,
)
def search_watched_mix_tracklist(video_id: str, body: TracklistSearchRequest) -> JobResponse:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    settings = engine.load_runtime_settings()
    rows = [dict(row) for row in body.rows]

    def execute(progress):
        session = engine.tidal_client(interactive=False)
        delay = number_setting(settings, "tidal_search_delay_seconds", 0.35, minimum=0)
        searchable = [
            row for row in rows
            if row.get("status") not in {"invalid", "unresolved", "imported", "watching"}
        ]
        for index, row in enumerate(searchable):
            progress(f"Searching TIDAL: {index + 1}/{len(searchable)}")
            matches = find_tidal_matches(engine, session, row)
            row["matches"] = matches
            row["selected_id"] = str(matches[0].get("id") or "") if matches else ""
            row["status"] = (
                "matched" if matches and int(matches[0].get("score", 0)) >= 8
                else "ambiguous" if matches else "not_found"
            )
            if delay and index + 1 < len(searchable):
                time.sleep(delay)
        return {"rows": rows, "searched": len(searchable)}

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit(f"watched-tracklist-search:{video_id}", execute))
    )


@router.post("/pending-tracks/refresh", response_model=JobResponse, status_code=202)
def refresh_pending_tracks() -> JobResponse:
    settings = engine.load_runtime_settings()

    def execute(progress):
        rows = pending_tracks()
        session = engine.tidal_client(interactive=False) if rows else None
        delay = number_setting(settings, "tidal_search_delay_seconds", 0.35, minimum=0)
        for index, row in enumerate(rows):
            progress(f"Searching pending tracks: {index + 1}/{len(rows)}")
            candidates = find_tidal_matches(engine, session, row)
            status = _pending_match_status(candidates)
            update_pending_track_candidates(int(row["id"]), candidates, status)
            if delay and index + 1 < len(rows):
                time.sleep(delay)
        return {"searched": len(rows)}

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("pending-track-refresh", execute)))


@router.post("/pending-tracks/{pending_id}/refresh", response_model=JobResponse, status_code=202)
def refresh_one_pending_track(pending_id: int) -> JobResponse:
    record = pending_track(pending_id)
    if not record:
        raise HTTPException(status_code=404, detail="Pending track was not found")

    def execute(progress):
        progress(f"Searching TIDAL for {record['artist']} — {record['title']}")
        session = engine.tidal_client(interactive=False)
        candidates = find_tidal_matches(engine, session, record)
        status = _pending_match_status(candidates)
        update_pending_track_candidates(pending_id, candidates, status)
        return {"id": pending_id, "status": status, "candidates": len(candidates)}

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit(f"pending-track-refresh:{pending_id}", execute))
    )
