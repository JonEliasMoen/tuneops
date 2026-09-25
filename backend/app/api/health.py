from __future__ import annotations

import os

from fastapi import APIRouter

import main as engine
from music_library.database import DATABASE_PATH

from ..schemas import HealthResponse, ProviderStatus


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    state = engine._connection_state()
    spotify_label = str(state.get("spotify") or "")
    tidal_label = str(state.get("tidal") or "")
    return HealthResponse(
        database_ready=DATABASE_PATH.exists(),
        providers={
            "spotify": ProviderStatus(
                connected=engine.SPOTIFY_CACHE.exists(), label=spotify_label
            ),
            "tidal": ProviderStatus(
                connected=engine.TIDAL_CACHE.exists(), label=tidal_label
            ),
        },
        lastfm_api_key_configured=bool(os.getenv("LASTFM_API_KEY", "").strip()),
    )


@router.get("/info")
def info() -> dict[str, object]:
    return {
        "name": "MusicSync",
        "api_version": "v1",
        "ui": "react",
        "capabilities": [
            "library",
            "collections",
            "search",
            "dimensions",
            "settings",
            "sync_jobs",
            "lastfm_jobs",
        ],
    }
