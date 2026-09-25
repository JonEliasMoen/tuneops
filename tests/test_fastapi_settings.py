from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api import settings
from backend.app.schemas import SettingsPatch, SyncMappings


def test_public_settings_never_exposes_private_config_values(monkeypatch):
    monkeypatch.setattr(settings.engine, "load_config", lambda: {
        "settings": {
            "dark_mode": False,
            "ollama_model": "qwen3:4b",
            "internal_token": "must-not-leak",
        },
        "quick_views": [{"id": "dj", "name": "DJ", "fields": ["title"]}],
    })

    result = settings.settings()

    assert result.dark_mode is False
    assert result.ollama_model == "qwen3:4b"
    assert "internal_token" not in result.model_dump()
    assert result.quick_views[0]["id"] == "dj"


def test_settings_patch_persists_only_submitted_public_values(monkeypatch):
    config = {"settings": {"dark_mode": True, "provider_secret": "keep"}, "quick_views": []}
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(settings.engine, "load_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_config", lambda value: saved.append(value.copy()))

    result = settings.patch_settings(SettingsPatch(dark_mode=False, lastfm_username="Aruzhu"))

    assert result.dark_mode is False
    assert result.lastfm_username == "Aruzhu"
    assert config["settings"]["provider_secret"] == "keep"
    assert saved and saved[0]["settings"] == config["settings"]


def test_settings_rejects_multiple_default_quick_views_without_saving(monkeypatch):
    config = {"settings": {}, "quick_views": []}
    monkeypatch.setattr(settings.engine, "load_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_config", lambda _value: pytest.fail("invalid configuration must not save"))

    with pytest.raises(HTTPException) as raised:
        settings.patch_settings(SettingsPatch(quick_views=[
            {"id": "one", "name": "One", "fields": ["title"], "default": True},
            {"id": "two", "name": "Two", "fields": ["artist"], "default": True},
        ]))

    assert raised.value.status_code == 422


def test_mapping_save_preserves_existing_sync_state(monkeypatch):
    config = {
        "playlists": [{
            "name": "My playlist",
            "direction": "tidal_to_spotify",
            "collection_type": "playlist",
            "last_sync": "2026-09-01T00:00:00+00:00",
            "unmatched": ["unreleased track"],
        }]
    }
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(settings.engine, "load_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_config", lambda value: saved.append(value.copy()))

    result = settings.save_sync_mappings(SyncMappings(playlists=[{
        "name": "Renamed playlist", "direction": "tidal_cache", "collection_type": "event",
    }]))

    row = result.playlists[0]
    assert row["name"] == "Renamed playlist"
    assert row["direction"] == "tidal_cache"
    assert row["collection_type"] == "event"
    assert row["last_sync"] == "2026-09-01T00:00:00+00:00"
    assert row["unmatched"] == ["unreleased track"]
    assert saved


def test_mapping_save_rejects_invalid_direction_without_saving(monkeypatch):
    monkeypatch.setattr(settings.engine, "load_config", lambda: {"playlists": []})
    monkeypatch.setattr(settings.engine, "save_config", lambda _value: pytest.fail("invalid mapping must not save"))

    with pytest.raises(HTTPException) as raised:
        settings.save_sync_mappings(SyncMappings(playlists=[{
            "name": "Bad", "direction": "reverse_everything", "collection_type": "playlist",
        }]))

    assert raised.value.status_code == 422
