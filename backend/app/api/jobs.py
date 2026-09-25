from __future__ import annotations

import os
import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

import main as engine
from music_library.database import lastfm_import_summary
from music_library.database import replace_tidal_track_dimensions
from music_library.database import pending_track, pending_tracks, update_pending_track_candidates, watched_mix
from music_tools.auto_tagging import auto_tag_tracks
from music_tools.liked_tracks.service import fetch_library_tracks
from music_tools.lastfm import import_scrobbles, reconcile_track_matches
from music_tools.mixes.service import import_tidal_setlist, mix_for
from music_tools.watched_mixes.tracklist import find_tidal_matches

from ..jobs import JOBS
from ..schemas import AutoTagRequest, JobResponse, MixTidalImportRequest, TracklistSearchRequest
from ..services.library import CollectionNotFound, descriptor


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
        return [asdict(result) for result in engine.run_all_syncs(progress=progress)]

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("playlist-sync", execute)))


@router.get("/lastfm/status")
def lastfm_status() -> dict[str, object]:
    username = str(engine.load_config().get("settings", {}).get("lastfm_username", "") or "").strip()
    return {
        "username": username,
        "api_key_configured": bool(os.getenv("LASTFM_API_KEY", "").strip()),
        **lastfm_import_summary(username),
    }


@router.post("/lastfm/import", response_model=JobResponse, status_code=202)
def run_lastfm_import() -> JobResponse:
    settings = engine.load_config().get("settings", {})
    username = str(settings.get("lastfm_username", "") or "").strip()
    api_key = os.getenv("LASTFM_API_KEY", "")

    def execute(progress):
        return import_scrobbles(
            username,
            api_key,
            delay_seconds=float(settings.get("lastfm_import_delay_seconds", 0.5)),
            progress=progress,
        )

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("lastfm-import", execute)))


@router.post("/lastfm/reconcile", response_model=JobResponse, status_code=202)
def run_lastfm_reconcile() -> JobResponse:
    username = str(engine.load_config().get("settings", {}).get("lastfm_username", "") or "").strip()

    def execute(progress):
        progress("Matching cached Last.fm identities to the TIDAL library")
        return reconcile_track_matches(username)

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("lastfm-reconcile", execute)))


@router.post("/tracks/auto-tag", response_model=JobResponse, status_code=202)
def run_auto_tag(body: AutoTagRequest) -> JobResponse:
    settings = engine.load_config().get("settings", {})
    wanted = set(dict.fromkeys(body.track_ids))

    def execute(progress):
        progress(f"Loading metadata for {len(wanted)} selected track(s)")
        records, _ = fetch_library_tracks(limit=1_000_000)
        selected = [record for record in records if str(record.get("id") or "") in wanted]
        if len(selected) != len(wanted):
            missing = len(wanted) - len(selected)
            raise RuntimeError(f"{missing} selected track(s) are no longer in the local library.")
        progress(f"Classifying {len(selected)} track(s) with {settings.get('ollama_model', 'qwen3:4b')}")
        suggestions = auto_tag_tracks(
            selected,
            model=str(settings.get("ollama_model", "qwen3:4b")),
            base_url=str(settings.get("ollama_url", "http://127.0.0.1:11434")),
            timeout_seconds=float(settings.get("ollama_timeout_seconds", 300)),
        )
        tagged = 0
        for track in selected:
            track_id = str(track.get("id") or "")
            dimensions = suggestions.get(track_id)
            if not dimensions:
                continue
            replace_tidal_track_dimensions(track_id, dimensions)
            tagged += 1
        progress(f"Stored tags for {tagged} of {len(selected)} track(s)")
        return {"requested": len(selected), "tagged": tagged}

    return JobResponse.model_validate(JOBS.snapshot(JOBS.submit("auto-tag", execute)))


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
            return engine.maintain_tidal_liked_tracks(
                tidal,
                engine.load_config().get("settings", {}),
                progress=progress,
            )
        progress(f"Checking {collection['name']} on TIDAL")
        return engine.refresh_tidal_playlist_cache(collection_id, force=force)

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
        return {"playlist_name": playlist_name, "tracks": len(tracks)}

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit(f"mix-tidal-import:{folder_name}", execute))
    )


@router.post(
    "/watched-mixes/{video_id}/tracklist/search",
    response_model=JobResponse,
    status_code=202,
)
def search_watched_mix_tracklist(video_id: str, body: TracklistSearchRequest) -> JobResponse:
    if not watched_mix(video_id):
        raise HTTPException(status_code=404, detail="Watched mix was not found")
    rows = [dict(row) for row in body.rows]
    def execute(progress):
        session = engine.tidal_client(interactive=False)
        delay = max(0.0, float(settings.get("tidal_search_delay_seconds", 0.35)))
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
    settings = engine.load_config().get("settings", {})

    def execute(progress):
        rows = pending_tracks()
        session = engine.tidal_client(interactive=False) if rows else None
        delay = max(0.0, float(settings.get("tidal_search_delay_seconds", 0.35)))
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
