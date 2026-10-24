from __future__ import annotations

import copy
import json

import pytest

from music_library import config_store


@pytest.fixture
def sample_config():
    return {
        "settings": {"dark_mode": True, "country_code": "NO"},
        "quick_views": [{
            "id": "default", "name": "Default", "fields": ["title", "artist"],
            "default": True, "future_option": "keep",
        }],
        "mix_quick_views": [{
            "id": "mix", "name": "Mix", "fields": ["cover", "youtube_views"],
            "default": True,
        }],
        "playlists": [{
            "enabled": True, "name": "Event", "direction": "tidal_to_spotify",
            "collection_type": "event", "spotify": "spotify-id", "tidal": "tidal-id",
            "tidal_name": "Event source", "last_sync": "2026-10-01T12:00:00",
            "source_version": "version", "future_mapping_value": {"keep": True},
            "unmatched": {
                "tidal_to_spotify": [
                    {"key": "isrc:one", "title": "One", "artist": "Artist", "isrc": "ONE"},
                    {"title": "Legacy", "artist": "Artist", "isrc": ""},
                ]
            },
        }],
        "future_top_level": {"keep": True},
    }


def test_config_round_trip_preserves_portable_data(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"

    config_store.replace(sample_config, database)
    exported = config_store.export(database)

    assert exported == sample_config
    loaded = config_store.load(database)
    assert loaded is not None
    assert loaded["playlists"][0]["_mapping_id"]
    assert config_store.exists(database)


def test_settings_bundle_omits_mappings_and_preserves_quick_view_extras(
    tmp_path, sample_config,
):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)

    result = config_store.load_settings_bundle(database)

    assert result == {
        "settings": sample_config["settings"],
        "quick_views": sample_config["quick_views"],
        "mix_quick_views": sample_config["mix_quick_views"],
    }
    assert "playlists" not in result
    assert "future_top_level" not in result


def test_settings_bundle_is_absent_before_config_import(tmp_path):
    database = tmp_path / "library.sqlite3"

    assert config_store.load_settings_bundle(database) is None


def test_runtime_settings_omit_views_mappings_and_top_level_extras(
    tmp_path, sample_config,
):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)

    result = config_store.load_runtime_settings(database)

    assert result == sample_config["settings"]


def test_runtime_settings_are_absent_before_config_import(tmp_path):
    database = tmp_path / "library.sqlite3"

    assert config_store.load_runtime_settings(database) is None


def test_replace_is_transactional_on_invalid_mapping(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)
    invalid = copy.deepcopy(sample_config)
    invalid["playlists"][0]["direction"] = "sideways"

    with pytest.raises(ValueError):
        config_store.replace(invalid, database)

    assert config_store.export(database) == sample_config


def test_mapping_ids_survive_runtime_round_trip(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)
    loaded = config_store.load(database)
    mapping_id = loaded["playlists"][0]["_mapping_id"]
    loaded["playlists"][0]["last_sync"] = "2026-10-17T18:00:00"

    config_store.replace(loaded, database)

    updated = config_store.load(database)
    assert updated["playlists"][0]["_mapping_id"] == mapping_id
    assert updated["playlists"][0]["last_sync"] == "2026-10-17T18:00:00"


def test_only_one_default_quick_view_is_allowed(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    invalid = copy.deepcopy(sample_config)
    invalid["quick_views"].append({
        "id": "other", "name": "Other", "fields": ["title"], "default": True,
    })

    with pytest.raises(ValueError, match="Only one track Quick View"):
        config_store.replace(invalid, database)


def test_export_is_valid_json(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)

    serialized = json.dumps(config_store.export(database), ensure_ascii=False)

    assert "_mapping_id" not in serialized


def test_empty_unmatched_object_round_trips(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    sample_config["playlists"][0]["unmatched"] = {}

    config_store.replace(sample_config, database)

    assert config_store.export(database)["playlists"][0]["unmatched"] == {}


def test_empty_unmatched_direction_round_trips(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    sample_config["playlists"][0]["unmatched"] = {"tidal_to_spotify": []}

    config_store.replace(sample_config, database)

    assert config_store.export(database)["playlists"][0]["unmatched"] == {
        "tidal_to_spotify": []
    }


def test_sync_mapping_read_includes_runtime_state_in_one_bundle(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)

    mappings = config_store.load_sync_mappings(database)

    assert mappings is not None
    assert mappings[0]["_mapping_id"]
    assert mappings[0]["future_mapping_value"] == {"keep": True}
    assert mappings[0]["unmatched"] == sample_config["playlists"][0]["unmatched"]


def test_settings_save_does_not_rewrite_mappings_or_top_level_extras(
    tmp_path, sample_config,
):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)
    original_mappings = config_store.load_sync_mappings(database)

    config_store.save_settings_bundle(
        {"dark_mode": False, "country_code": "NO"},
        [{"id": "compact", "name": "Compact", "fields": ["title"], "future": 1}],
        sample_config["mix_quick_views"],
        database,
    )

    exported = config_store.export(database)
    assert exported["future_top_level"] == {"keep": True}
    assert exported["playlists"] == sample_config["playlists"]
    assert exported["settings"]["dark_mode"] is False
    assert exported["quick_views"][0]["future"] == 1
    assert config_store.load_sync_mappings(database) == original_mappings


def test_mapping_save_does_not_rewrite_settings_or_views(tmp_path, sample_config):
    database = tmp_path / "library.sqlite3"
    config_store.replace(sample_config, database)
    mappings = config_store.load_sync_mappings(database)
    assert mappings is not None
    mappings[0]["name"] = "Renamed"

    config_store.replace_sync_mappings(mappings, database)

    exported = config_store.export(database)
    assert exported["settings"] == sample_config["settings"]
    assert exported["quick_views"] == sample_config["quick_views"]
    assert exported["mix_quick_views"] == sample_config["mix_quick_views"]
    assert exported["future_top_level"] == sample_config["future_top_level"]
    assert exported["playlists"][0]["name"] == "Renamed"
    assert config_store.load_sync_mappings(database)[0]["_mapping_id"] == mappings[0]["_mapping_id"]
