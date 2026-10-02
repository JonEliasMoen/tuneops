from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import RedirectResponse

from music_library.database import (
    store_youtube_mix_analytics,
    store_youtube_video_metadata,
    youtube_video_metadata,
)
from music_tools.mixes.service import discover_mixes, fetch_youtube_metadata, youtube_video_id
from music_tools.youtube_analytics import service

from ..jobs import JOBS
from ..schemas import JobResponse


router = APIRouter(tags=["youtube"])
LOGGER = logging.getLogger("musicsync")
STATE_COOKIE = "musicsync_youtube_oauth_state"


@router.get("/youtube/status")
def youtube_status() -> dict[str, object]:
    return service.status()


@router.get("/youtube/connect", include_in_schema=False)
def youtube_connect() -> RedirectResponse:
    try:
        state = service.new_state()
        target = service.authorization_url(state)
    except service.YouTubeAuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = RedirectResponse(target, status_code=307)
    response.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=False,
    )
    return response


@router.get("/youtube/callback", include_in_schema=False)
def youtube_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    stored_state: str | None = Cookie(default=None, alias=STATE_COOKIE),
) -> RedirectResponse:
    if error:
        return RedirectResponse("/settings?youtube=denied", status_code=303)
    if not code or not state or not stored_state or state != stored_state:
        raise HTTPException(status_code=400, detail="Google OAuth state was invalid or expired")
    try:
        service.exchange_code(code)
    except service.YouTubeAuthError as exc:
        LOGGER.exception("youtube.oauth callback_failed")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = RedirectResponse("/settings?youtube=connected", status_code=303)
    response.delete_cookie(STATE_COOKIE)
    return response


@router.post("/youtube/analytics/refresh", response_model=JobResponse, status_code=202)
def refresh_youtube_analytics() -> JobResponse:
    if not service.status()["connected"]:
        raise HTTPException(status_code=409, detail="Connect YouTube Analytics first")

    def execute(progress):
        mix_by_video: dict[str, str] = {}
        for mix in discover_mixes():
            video_id = youtube_video_id(mix.youtube_url)
            if video_id:
                mix_by_video[video_id] = mix.folder_name
        progress(f"Requesting analytics for {len(mix_by_video)} My Mixes videos")
        analytics = service.query_video_analytics(list(mix_by_video))
        titles = service.query_video_titles(list(mix_by_video))
        existing_metadata = youtube_video_metadata()
        urls_by_video = {
            video_id: mix.youtube_url
            for mix in discover_mixes()
            if (video_id := youtube_video_id(mix.youtube_url))
        }
        missing_dates = [
            video_id for video_id in mix_by_video
            if not service.cached_video_upload_date(video_id)
            and not existing_metadata.get(video_id, {}).get("upload_date")
        ]
        public_metadata = {}
        if missing_dates:
            progress(f"Fetching upload dates for {len(missing_dates)} videos")
            with ThreadPoolExecutor(max_workers=6) as executor:
                fetched = executor.map(
                    fetch_youtube_metadata,
                    [urls_by_video[video_id] for video_id in missing_dates],
                )
            public_metadata = dict(zip(missing_dates, fetched))
        store_youtube_video_metadata([
            {
                "video_id": video_id,
                "title": titles.get(video_id)
                or existing_metadata.get(video_id, {}).get("title")
                or getattr(public_metadata.get(video_id), "title", ""),
                "upload_date": service.cached_video_upload_date(video_id)
                or existing_metadata.get(video_id, {}).get("upload_date")
                or getattr(public_metadata.get(video_id), "upload_date", ""),
            }
            for video_id in mix_by_video
        ])
        records = [
            {**record, "video_id": video_id, "folder_name": mix_by_video[video_id]}
            for video_id, record in analytics.items()
            if video_id in mix_by_video
        ]
        stored = store_youtube_mix_analytics(records)
        progress(f"Cached analytics for {stored} owned mix videos")
        return {"requested": len(mix_by_video), "matched": len(records), "stored": stored}

    return JobResponse.model_validate(
        JOBS.snapshot(JOBS.submit("youtube-analytics-refresh", execute))
    )
