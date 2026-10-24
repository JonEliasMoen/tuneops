from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api import settings
from backend.app.schemas import SettingsPatch, SyncMappings


def test_public_settings_never_exposes_private_config_values(monkeypatch):
    monkeypatch.setattr(settings.engine, "load_settings_config", lambda: {
        "settings": {
            "dark_mode": False,
            "internal_token": "must-not-leak",
        },
        "quick_views": [{"id": "dj", "name": "DJ", "fields": ["title"]}],
        "mix_quick_views": [{"id": "performance", "name": "Performance", "fields": ["youtube_views"]}],
    })

    result = settings.settings()

    assert result.dark_mode is False
    assert result.default_sort_direction == "asc"
    assert "internal_token" not in result.model_dump()
    assert result.quick_views[0]["id"] == "dj"
    assert result.mix_quick_views[0]["id"] == "performance"


def test_my_mix_settings_are_database_only(monkeypatch):
    monkeypatch.setattr(
        settings,
        "discover_mixes",
        lambda: [
            type("Mix", (), {
                "folder_name": "darkprog",
                "tidal_playlist_id": "playlist-id",
                "tidal_playlist_name": "djset darkprog",
                "track_count": 12,
            })(),
            type("Mix", (), {
                "folder_name": "futurehouse",
                "tidal_playlist_id": "",
                "tidal_playlist_name": "",
                "track_count": 0,
            })(),
        ],
    )

    result = settings.my_mix_settings()

    assert result["items"][0] == {
        "internal_name": "darkprog",
        "expected_tidal_name": "djset darkprog",
        "tidal_playlist_id": "playlist-id",
        "tidal_playlist_name": "djset darkprog",
        "track_count": 12,
        "status": "connected",
    }
    assert result["items"][1]["status"] == "not_discovered"


def test_settings_patch_persists_only_submitted_public_values(monkeypatch):
    config = {"settings": {"dark_mode": True, "provider_secret": "keep"}, "quick_views": []}
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(settings.engine, "load_settings_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_settings_config", lambda value: saved.append(value.copy()))

    result = settings.patch_settings(SettingsPatch(dark_mode=False, lastfm_username="Aruzhu"))

    assert result.dark_mode is False
    assert result.lastfm_username == "Aruzhu"
    assert config["settings"]["provider_secret"] == "keep"
    assert saved and saved[0]["settings"] == config["settings"]


def test_settings_patch_persists_default_sort_direction(monkeypatch):
    config = {"settings": {}, "quick_views": []}
    monkeypatch.setattr(settings.engine, "load_settings_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_settings_config", lambda _value: None)

    result = settings.patch_settings(SettingsPatch(default_sort_direction="desc"))

    assert result.default_sort_direction == "desc"
    assert config["settings"]["default_sort_direction"] == "desc"


def test_settings_rejects_multiple_default_quick_views_without_saving(monkeypatch):
    config = {"settings": {}, "quick_views": []}
    monkeypatch.setattr(settings.engine, "load_settings_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_settings_config", lambda _value: pytest.fail("invalid configuration must not save"))

    with pytest.raises(HTTPException) as raised:
        settings.patch_settings(SettingsPatch(quick_views=[
            {"id": "one", "name": "One", "fields": ["title"], "default": True},
            {"id": "two", "name": "Two", "fields": ["artist"], "default": True},
        ]))

    assert raised.value.status_code == 422


def test_settings_rejects_multiple_default_mix_quick_views_without_saving(monkeypatch):
    config = {"settings": {}, "quick_views": [], "mix_quick_views": []}
    monkeypatch.setattr(settings.engine, "load_settings_config", lambda: config)
    monkeypatch.setattr(settings.engine, "save_settings_config", lambda _value: pytest.fail("invalid configuration must not save"))

    with pytest.raises(HTTPException) as raised:
        settings.patch_settings(SettingsPatch(mix_quick_views=[
            {"id": "one", "name": "One", "fields": ["folder_name"], "default": True},
            {"id": "two", "name": "Two", "fields": ["youtube_views"], "default": True},
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
    monkeypatch.setattr(settings.engine, "load_sync_mappings", lambda: config["playlists"])
    monkeypatch.setattr(settings.engine, "save_sync_mappings", lambda value: saved.extend(value))

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
    monkeypatch.setattr(settings.engine, "load_sync_mappings", lambda: [])
    monkeypatch.setattr(settings.engine, "save_sync_mappings", lambda _value: pytest.fail("invalid mapping must not save"))

    with pytest.raises(HTTPException) as raised:
        settings.save_sync_mappings(SyncMappings(playlists=[{
            "name": "Bad", "direction": "reverse_everything", "collection_type": "playlist",
        }]))

    assert raised.value.status_code == 422


def test_mapping_removal_deletes_only_unreferenced_local_tidal_cache(monkeypatch):
    config = {"playlists": [
        {"_mapping_id": "one", "name": "First", "direction": "tidal_cache", "collection_type": "playlist", "tidal": "https://tidal.com/playlist/shared"},
        {"_mapping_id": "two", "name": "Second", "direction": "tidal_cache", "collection_type": "event", "tidal": "https://tidal.com/playlist/shared"},
        {"_mapping_id": "three", "name": "Gone", "direction": "tidal_cache", "collection_type": "source", "tidal": "https://tidal.com/playlist/remove-me"},
    ]}
    deleted: list[str] = []
    monkeypatch.setattr(settings.engine, "load_sync_mappings", lambda: config["playlists"])
    monkeypatch.setattr(settings.engine, "save_sync_mappings", lambda _value: None)
    monkeypatch.setattr(settings, "delete_tidal_playlist_cache", deleted.append)

    settings.save_sync_mappings(SyncMappings(playlists=[
        {"_mapping_id": "two", "name": "Second", "direction": "tidal_cache", "collection_type": "event", "tidal": "https://tidal.com/playlist/shared"},
    ]))

    assert deleted == ["remove-me"]


def test_orphaned_settings_endpoints_delegate_to_local_database(monkeypatch):
    page = {"items": [], "total": 0, "offset": 0, "limit": 25, "has_more": False}
    monkeypatch.setattr(settings, "orphaned_tidal_tracks", lambda limit, offset: page)
    monkeypatch.setattr(settings, "clear_orphaned_tidal_tracks", lambda: {"deleted_tracks": 2, "cleared_lastfm_matches": 1})

    assert settings.get_orphaned_tracks(limit=25, offset=0) == page
    assert settings.delete_orphaned_tracks() == {"deleted_tracks": 2, "cleared_lastfm_matches": 1}


def test_delete_one_orphan_returns_conflict_when_membership_changed(monkeypatch):
    monkeypatch.setattr(settings, "delete_orphaned_tidal_track", lambda _track_id: {"deleted_tracks": 0, "cleared_lastfm_matches": 0})

    with pytest.raises(HTTPException) as raised:
        settings.delete_orphaned_track("now-liked")

    assert raised.value.status_code == 409


def test_search_spotify_playlists_filters_and_returns_urls(monkeypatch):
    settings._PLAYLIST_CACHE.clear()

    class Spotify:
        def current_user_playlists(self, limit):
            assert limit == 50
            return {"items": [
                {"id": "one", "name": "Deep House", "external_urls": {"spotify": "https://open.spotify.com/playlist/one"}},
                {"id": "two", "name": "Techno", "external_urls": {}},
            ], "next": None}

    monkeypatch.setattr(settings.engine, "spotify_client", Spotify)

    result = settings.search_sync_playlists("spotify", "deep")

    assert result == [{"id": "one", "name": "Deep House", "url": "https://open.spotify.com/playlist/one"}]


def test_search_tidal_playlists_uses_cached_user_playlist_list(monkeypatch):
    settings._PLAYLIST_CACHE.clear()
    calls = []
    playlist = type("Playlist", (), {"id": "tidal-id", "name": "Melodic Techno"})()
    user = type("User", (), {"playlists": lambda self: calls.append(True) or [playlist]})()
    session = type("Session", (), {"user": user})()
    monkeypatch.setattr(settings.engine, "tidal_client", lambda interactive=False: session)

    first = settings.search_sync_playlists("tidal", "melodic")
    second = settings.search_sync_playlists("tidal", "techno")

    assert first == second == [{
        "id": "tidal-id", "name": "Melodic Techno",
        "url": "https://tidal.com/playlist/tidal-id",
    }]
    assert len(calls) == 1
