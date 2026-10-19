from __future__ import annotations

import os
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import main as engine
from music_library.database import (
    clear_orphaned_tidal_tracks,
    delete_orphaned_tidal_track,
    delete_tidal_playlist_cache,
    orphaned_tidal_tracks,
)

from ..schemas import PublicSettings, SettingsPatch, SyncMappings


router = APIRouter(tags=["settings"])
LOGGER = logging.getLogger("musicsync")
_PLAYLIST_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_PLAYLIST_CACHE_LOCK = threading.Lock()
_PLAYLIST_CACHE_SECONDS = 300


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
        mix_quick_views=list(config.get("mix_quick_views") or []),
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
    mix_quick_views = values.pop("mix_quick_views", None)
    config.setdefault("settings", {}).update(values)
    if quick_views is not None:
        defaults = sum(bool(view.get("default")) for view in quick_views)
        if defaults > 1:
            raise HTTPException(status_code=422, detail="Only one Quick View can be the default")
        config["quick_views"] = quick_views
    if mix_quick_views is not None:
        defaults = sum(bool(view.get("default")) for view in mix_quick_views)
        if defaults > 1:
            raise HTTPException(status_code=422, detail="Only one My Mixes Quick View can be the default")
        config["mix_quick_views"] = mix_quick_views
    engine.save_config(config)
    return _public(config)


@router.get("/sync/mappings", response_model=SyncMappings)
def sync_mappings() -> SyncMappings:
    return SyncMappings(playlists=engine.load_config().get("playlists", []))


@router.get("/settings/orphaned-tracks")
def get_orphaned_tracks(
    limit: int = Query(default=250, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return orphaned_tidal_tracks(limit=limit, offset=offset)


@router.delete("/settings/orphaned-tracks")
def delete_orphaned_tracks() -> dict[str, int]:
    return clear_orphaned_tidal_tracks()


@router.delete("/settings/orphaned-tracks/{track_id}")
def delete_orphaned_track(track_id: str) -> dict[str, int]:
    result = delete_orphaned_tidal_track(track_id)
    if not result["deleted_tracks"]:
        raise HTTPException(
            status_code=409,
            detail="The track no longer exists or is no longer orphaned.",
        )
    return result


def _provider_playlists(provider: str) -> list[dict[str, str]]:
    with _PLAYLIST_CACHE_LOCK:
        cached = _PLAYLIST_CACHE.get(provider)
        if cached and time.monotonic() - cached[0] < _PLAYLIST_CACHE_SECONDS:
            return cached[1]
    try:
        if provider == "spotify":
            client = engine.spotify_client()
            page = client.current_user_playlists(limit=50)
            raw: list[Any] = []
            while page:
                raw.extend(page.get("items") or [])
                page = client.next(page) if page.get("next") else None
            playlists = [
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "url": str((item.get("external_urls") or {}).get("spotify") or item.get("id") or ""),
                }
                for item in raw if item.get("id")
            ]
        else:
            session = engine.tidal_client(interactive=False)
            playlists = [
                {
                    "id": str(item.id),
                    "name": str(getattr(item, "name", "") or ""),
                    "url": f"https://tidal.com/playlist/{item.id}",
                }
                for item in session.user.playlists() if getattr(item, "id", None)
            ]
    except Exception as exc:
        LOGGER.exception("sync.playlist_picker provider=%s failed", provider)
        raise HTTPException(status_code=409, detail=f"Could not load {provider.title()} playlists.") from exc
    playlists.sort(key=lambda item: item["name"].casefold())
    with _PLAYLIST_CACHE_LOCK:
        _PLAYLIST_CACHE[provider] = (time.monotonic(), playlists)
    return playlists


@router.get("/sync/playlists")
def search_sync_playlists(
    provider: str = Query(pattern="^(spotify|tidal)$"),
    query: str = Query(default="", max_length=200),
) -> list[dict[str, str]]:
    needle = query.strip().casefold()
    matches = _provider_playlists(provider)
    if needle:
        matches = [item for item in matches if needle in item["name"].casefold()]
        return matches[:100]
    return matches


@router.put("/sync/mappings", response_model=SyncMappings)
def save_sync_mappings(body: SyncMappings) -> SyncMappings:
    config = engine.load_config()
    existing = list(config.get("playlists") or [])
    existing_by_id = {
        str(row.get("_mapping_id")): row
        for row in existing if row.get("_mapping_id")
    }
    merged: list[dict[str, Any]] = []
    for index, incoming in enumerate(body.playlists):
        mapping_id = str(incoming.get("_mapping_id") or "")
        if mapping_id:
            row = dict(existing_by_id.get(mapping_id) or {})
        else:
            # Compatibility for older callers that do not know stable mapping IDs.
            row = dict(existing[index]) if index < len(existing) else {}
        row.update(incoming)
        direction = str(row.get("direction") or "spotify_to_tidal")
        section = str(row.get("collection_type") or "playlist")
        if direction not in {"spotify_to_tidal", "tidal_to_spotify", "tidal_cache"}:
            raise HTTPException(status_code=422, detail=f"Invalid sync direction at row {index + 1}")
        if section not in {"playlist", "event", "source"}:
            raise HTTPException(status_code=422, detail=f"Invalid library section at row {index + 1}")
        merged.append(row)
    retained_ids = {
        str(row.get("_mapping_id")) for row in merged if row.get("_mapping_id")
    }
    removed = [
        row for row in existing
        if row.get("_mapping_id") and str(row.get("_mapping_id")) not in retained_ids
    ]
    config["playlists"] = merged
    engine.save_config(config)
    retained_tidal_ids = {
        engine._id(str(row.get("tidal") or ""))
        for row in merged if row.get("tidal")
    }
    for row in removed:
        playlist_id = engine._id(str(row.get("tidal") or ""))
        if playlist_id and playlist_id not in retained_tidal_ids:
            delete_tidal_playlist_cache(playlist_id)
            LOGGER.info(
                "sync.mapping_removed local_playlist_cache_deleted playlist_id=%s",
                playlist_id,
            )
    return SyncMappings(playlists=merged)
