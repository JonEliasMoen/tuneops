from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

import main as engine

from ..schemas import PublicSettings, SettingsPatch, SyncMappings


router = APIRouter(tags=["settings"])


PUBLIC_SETTING_KEYS = {
    "dark_mode",
    "tags_collapsed_by_default",
    "ollama_model",
    "ollama_url",
    "lastfm_username",
    "history_top_tracks",
    "spotify_search_delay_seconds",
}


def _public(config: dict[str, Any]) -> PublicSettings:
    settings = config.get("settings", {})
    return PublicSettings(
        **{key: settings.get(key) for key in PUBLIC_SETTING_KEYS if key in settings},
        quick_views=list(config.get("quick_views") or []),
        lastfm_api_key_configured=bool(os.getenv("LASTFM_API_KEY", "").strip()),
    )


@router.get("/settings", response_model=PublicSettings)
def settings() -> PublicSettings:
    return _public(engine.load_config())


@router.patch("/settings", response_model=PublicSettings)
def patch_settings(body: SettingsPatch) -> PublicSettings:
    config = engine.load_config()
    values = body.model_dump(exclude_unset=True)
    quick_views = values.pop("quick_views", None)
    config.setdefault("settings", {}).update(values)
    if quick_views is not None:
        defaults = sum(bool(view.get("default")) for view in quick_views)
        if defaults > 1:
            raise HTTPException(status_code=422, detail="Only one Quick View can be the default")
        config["quick_views"] = quick_views
    engine.save_config(config)
    return _public(config)


@router.get("/sync/mappings", response_model=SyncMappings)
def sync_mappings() -> SyncMappings:
    return SyncMappings(playlists=engine.load_config().get("playlists", []))


@router.put("/sync/mappings", response_model=SyncMappings)
def save_sync_mappings(body: SyncMappings) -> SyncMappings:
    config = engine.load_config()
    existing = list(config.get("playlists") or [])
    merged: list[dict[str, Any]] = []
    for index, incoming in enumerate(body.playlists):
        row = dict(existing[index]) if index < len(existing) else {}
        row.update(incoming)
        direction = str(row.get("direction") or "spotify_to_tidal")
        section = str(row.get("collection_type") or "playlist")
        if direction not in {"spotify_to_tidal", "tidal_to_spotify", "tidal_cache"}:
            raise HTTPException(status_code=422, detail=f"Invalid sync direction at row {index + 1}")
        if section not in {"playlist", "event", "source"}:
            raise HTTPException(status_code=422, detail=f"Invalid library section at row {index + 1}")
        merged.append(row)
    config["playlists"] = merged
    engine.save_config(config)
    return SyncMappings(playlists=merged)
