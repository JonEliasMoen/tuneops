from __future__ import annotations

import os

from fastapi import APIRouter

import main as engine
from music_library.database import DATABASE_PATH
from music_library.connection import database_backend
from music_library.credentials import credential_availability

from ..schemas import HealthResponse, ProviderStatus


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    state = engine._connection_state()
    spotify_label = str(state.get("spotify") or "")
    tidal_label = str(state.get("tidal") or "")
    connected = credential_availability(
        {
            "spotify": engine.SPOTIFY_CACHE,
            "tidal": engine.TIDAL_CACHE,
        }
    )
    return HealthResponse(
        database_ready=database_backend() == "turso" or DATABASE_PATH.exists(),
        providers={
            "spotify": ProviderStatus(
                connected=connected["spotify"], label=spotify_label
            ),
            "tidal": ProviderStatus(
                connected=connected["tidal"], label=tidal_label
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
