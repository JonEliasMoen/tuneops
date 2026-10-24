"""Transactional SQLite storage for MusicSync configuration.

The public shape intentionally remains compatible with the historical
``music_sync.json`` document while callers are moved to narrower repository
operations. Provider credentials and OAuth sessions never belong here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from music_library.database import DATABASE_PATH, connect, connect_readonly, initialize


PROFILE_ID = "local"
SCHEMA_VERSION = 1
_MAPPING_FIELDS = {
    "name", "enabled", "direction", "collection_type", "spotify", "tidal",
    "tidal_name", "last_sync", "source_version", "unmatched", "_mapping_id",
}
_VIEW_FIELDS = {"id", "name", "fields", "default"}
_TOP_LEVEL_FIELDS = {"settings", "playlists", "quick_views", "mix_quick_views"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _object(value: str, fallback: Any) -> Any:
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return result


def exists(path: Path = DATABASE_PATH) -> bool:
    initialize(path)
    with connect(path) as connection:
        return connection.execute(
            "SELECT 1 FROM config_store_meta WHERE profile_id=?", (PROFILE_ID,)
        ).fetchone() is not None


def _mapping_id(mapping: dict[str, Any], position: int) -> str:
    supplied = str(mapping.get("_mapping_id") or "").strip()
    if supplied:
        return supplied
    identity = "\x1f".join((
        str(mapping.get("name") or ""),
        str(mapping.get("direction") or "spotify_to_tidal"),
        str(mapping.get("spotify") or ""),
        str(mapping.get("tidal") or ""),
        str(position),
    ))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"musicsync:mapping:{identity}"))


def _unmatched_key(record: dict[str, Any], position: int) -> str:
    key = str(record.get("key") or "").strip()
    if key:
        return key
    digest = hashlib.sha256(_json(record).encode("utf-8")).hexdigest()[:24]
    return f"legacy:{position}:{digest}"


def replace(config: dict[str, Any], path: Path = DATABASE_PATH) -> None:
    """Atomically replace the compatible configuration document in SQLite."""
    mappings = config.get("playlists")
    if not isinstance(mappings, list):
        raise ValueError("The config must contain a 'playlists' list")
    settings = config.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("The config 'settings' value must be an object")
    now = _now()
    initialize(path)
    with connect(path) as connection:
        connection.execute("DELETE FROM sync_mappings")
        for position, raw_mapping in enumerate(mappings):
            if not isinstance(raw_mapping, dict):
                raise ValueError(f"Playlist mapping {position + 1} must be an object")
            mapping = dict(raw_mapping)
            direction = str(mapping.get("direction") or "spotify_to_tidal")
            collection_type = str(mapping.get("collection_type") or "playlist")
            if direction not in {"spotify_to_tidal", "tidal_to_spotify", "tidal_cache"}:
                raise ValueError(f"Invalid sync direction at mapping {position + 1}")
            if collection_type not in {"playlist", "event", "source"}:
                raise ValueError(f"Invalid collection type at mapping {position + 1}")
            mapping_id = _mapping_id(mapping, position)
            extra = {key: value for key, value in mapping.items() if key not in _MAPPING_FIELDS}
            # Presence is meaningful for a lossless JSON round-trip even when
            # the historical unmatched object is currently empty.
            extra["_config_unmatched_present"] = "unmatched" in mapping
            raw_unmatched = mapping.get("unmatched")
            extra["_config_empty_unmatched_directions"] = [
                str(key) for key, value in raw_unmatched.items()
                if isinstance(raw_unmatched, dict) and isinstance(value, list) and not value
            ] if isinstance(raw_unmatched, dict) else []
            connection.execute(
                """
                INSERT INTO sync_mappings(
                    id, name, enabled, direction, collection_type,
                    spotify_reference, tidal_reference, tidal_name,
                    last_sync, source_version, position, extra_json,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping_id, str(mapping.get("name") or ""),
                    int(bool(mapping.get("enabled", True))), direction, collection_type,
                    str(mapping.get("spotify") or ""), str(mapping.get("tidal") or ""),
                    str(mapping.get("tidal_name") or ""),
                    mapping.get("last_sync") or None, mapping.get("source_version") or None,
                    position, _json(extra), now, now,
                ),
            )
            unmatched = mapping.get("unmatched") or {}
            if not isinstance(unmatched, dict):
                unmatched = {}
            for sync_direction, records in unmatched.items():
                if not isinstance(records, list):
                    continue
                for item_position, raw_record in enumerate(records):
                    if not isinstance(raw_record, dict):
                        continue
                    record = dict(raw_record)
                    connection.execute(
                        """
                        INSERT INTO sync_unmatched_tracks(
                            mapping_id, sync_direction, source_track_key, position,
                            metadata_json, first_seen_at, last_attempted_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mapping_id, str(sync_direction),
                            _unmatched_key(record, item_position), item_position,
                            _json(record), record.get("first_seen_at"),
                            record.get("last_attempted_at"),
                        ),
                    )

        connection.execute("DELETE FROM quick_views")
        for view_type, config_key in (("track", "quick_views"), ("mix", "mix_quick_views")):
            views = config.get(config_key) or []
            if not isinstance(views, list):
                raise ValueError(f"The config '{config_key}' value must be a list")
            defaults = sum(bool(item.get("default")) for item in views if isinstance(item, dict))
            if defaults > 1:
                raise ValueError(f"Only one {view_type} Quick View can be the default")
            for position, raw_view in enumerate(views):
                if not isinstance(raw_view, dict):
                    raise ValueError(f"{config_key} item {position + 1} must be an object")
                view = dict(raw_view)
                view_id = str(view.get("id") or uuid.uuid4())
                fields = view.get("fields") or []
                if not isinstance(fields, list):
                    raise ValueError(f"Quick View '{view_id}' fields must be a list")
                extra = {key: value for key, value in view.items() if key not in _VIEW_FIELDS}
                connection.execute(
                    """
                    INSERT INTO quick_views(
                        view_type, id, name, is_default, position,
                        fields_json, extra_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        view_type, view_id, str(view.get("name") or ""),
                        int(bool(view.get("default"))), position,
                        _json([str(field) for field in fields]), _json(extra), now, now,
                    ),
                )

        connection.execute(
            """
            INSERT INTO app_settings(profile_id, settings_json, schema_version, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                settings_json=excluded.settings_json,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (PROFILE_ID, _json(settings), SCHEMA_VERSION, now),
        )
        top_level_extra = {
            key: value for key, value in config.items() if key not in _TOP_LEVEL_FIELDS
        }
        connection.execute(
            """
            INSERT INTO config_store_meta(profile_id, extra_json, imported_at, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at
            """,
            (PROFILE_ID, _json(top_level_extra), now, now),
        )


def load(path: Path = DATABASE_PATH, *, include_internal: bool = True) -> dict[str, Any] | None:
    initialize(path)
    with connect(path) as connection:
        meta = connection.execute(
            "SELECT extra_json FROM config_store_meta WHERE profile_id=?", (PROFILE_ID,)
        ).fetchone()
        if meta is None:
            return None
        settings_row = connection.execute(
            "SELECT settings_json FROM app_settings WHERE profile_id=?", (PROFILE_ID,)
        ).fetchone()
        result = _object(meta["extra_json"], {})
        if not isinstance(result, dict):
            result = {}
        settings = _object(settings_row["settings_json"], {}) if settings_row else {}
        result["settings"] = settings if isinstance(settings, dict) else {}
        mappings: list[dict[str, Any]] = []
        for row in connection.execute("SELECT * FROM sync_mappings ORDER BY position, id"):
            mapping = _object(row["extra_json"], {})
            if not isinstance(mapping, dict):
                mapping = {}
            unmatched_present = bool(mapping.pop("_config_unmatched_present", False))
            empty_unmatched_directions = mapping.pop(
                "_config_empty_unmatched_directions", []
            )
            mapping.update({
                "enabled": bool(row["enabled"]), "name": row["name"],
                "direction": row["direction"], "collection_type": row["collection_type"],
                "spotify": row["spotify_reference"], "tidal": row["tidal_reference"],
                "tidal_name": row["tidal_name"],
            })
            if row["last_sync"] is not None:
                mapping["last_sync"] = row["last_sync"]
            if row["source_version"] is not None:
                mapping["source_version"] = row["source_version"]
            if include_internal:
                mapping["_mapping_id"] = row["id"]
            unmatched: dict[str, list[dict[str, Any]]] = {}
            if isinstance(empty_unmatched_directions, list):
                unmatched.update({str(direction): [] for direction in empty_unmatched_directions})
            records = connection.execute(
                """
                SELECT sync_direction, metadata_json FROM sync_unmatched_tracks
                WHERE mapping_id=? ORDER BY sync_direction, position
                """,
                (row["id"],),
            )
            for record in records:
                payload = _object(record["metadata_json"], {})
                if isinstance(payload, dict):
                    unmatched.setdefault(record["sync_direction"], []).append(payload)
            if unmatched or unmatched_present:
                mapping["unmatched"] = unmatched
            mappings.append(mapping)
        result["playlists"] = mappings
        for view_type, config_key in (("track", "quick_views"), ("mix", "mix_quick_views")):
            views: list[dict[str, Any]] = []
            for row in connection.execute(
                "SELECT * FROM quick_views WHERE view_type=? ORDER BY position, id", (view_type,)
            ):
                view = _object(row["extra_json"], {})
                if not isinstance(view, dict):
                    view = {}
                fields = _object(row["fields_json"], [])
                view.update({
                    "id": row["id"], "name": row["name"],
                    "fields": fields if isinstance(fields, list) else [],
                    "default": bool(row["is_default"]),
                })
                views.append(view)
            result[config_key] = views
        return result


def load_settings_bundle(path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    """Load only public settings and Quick Views without hydrating mappings.

    The full compatibility document performs mapping-specific unmatched-track
    queries. That is useful to the sync engine, but unnecessarily expensive for
    the Settings UI when the database is remote. Keep this read to one SQL
    execution so its cost does not grow with the number of sync mappings.
    """
    initialize(path)
    with connect_readonly(path) as connection:
        rows = connection.execute(
            """
            SELECT
                'meta' AS record_type,
                '' AS view_type,
                '' AS id,
                '' AS name,
                0 AS is_default,
                0 AS position,
                NULL AS fields_json,
                NULL AS extra_json,
                NULL AS settings_json
            FROM config_store_meta
            WHERE profile_id=?
            UNION ALL
            SELECT
                'settings', '', '', '', 0, 0, NULL, NULL, settings_json
            FROM app_settings
            WHERE profile_id=?
            UNION ALL
            SELECT
                'view', view_type, id, name, is_default, position,
                fields_json, extra_json, NULL
            FROM quick_views
            WHERE view_type IN ('track', 'mix')
            ORDER BY record_type, view_type, position, id
            """,
            (PROFILE_ID, PROFILE_ID),
        ).fetchall()

    if not any(row["record_type"] == "meta" for row in rows):
        return None

    result: dict[str, Any] = {
        "settings": {},
        "quick_views": [],
        "mix_quick_views": [],
    }
    for row in rows:
        if row["record_type"] == "settings":
            settings = _object(row["settings_json"], {})
            result["settings"] = settings if isinstance(settings, dict) else {}
            continue
        if row["record_type"] != "view":
            continue
        view = _object(row["extra_json"], {})
        if not isinstance(view, dict):
            view = {}
        fields = _object(row["fields_json"], [])
        view.update({
            "id": row["id"],
            "name": row["name"],
            "fields": fields if isinstance(fields, list) else [],
            "default": bool(row["is_default"]),
        })
        config_key = "quick_views" if row["view_type"] == "track" else "mix_quick_views"
        result[config_key].append(view)
    return result


def load_runtime_settings(path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    """Load only application settings in one read-only database request."""
    initialize(path)
    with connect_readonly(path) as connection:
        row = connection.execute(
            """
            SELECT settings.settings_json
            FROM config_store_meta AS meta
            LEFT JOIN app_settings AS settings
              ON settings.profile_id=meta.profile_id
            WHERE meta.profile_id=?
            """,
            (PROFILE_ID,),
        ).fetchone()
    if row is None:
        return None
    settings = _object(row["settings_json"], {})
    return settings if isinstance(settings, dict) else {}


def load_sync_mappings(
    path: Path = DATABASE_PATH, *, include_internal: bool = True,
) -> list[dict[str, Any]] | None:
    """Load mappings and unmatched state with one read-only SQL statement."""
    initialize(path)
    with connect_readonly(path) as connection:
        rows = connection.execute(
            """
            SELECT
                mapping.id AS mapping_id,
                mapping.name,
                mapping.enabled,
                mapping.direction,
                mapping.collection_type,
                mapping.spotify_reference,
                mapping.tidal_reference,
                mapping.tidal_name,
                mapping.last_sync,
                mapping.source_version,
                mapping.position AS mapping_position,
                mapping.extra_json AS mapping_extra_json,
                unmatched.sync_direction,
                unmatched.position AS unmatched_position,
                unmatched.metadata_json
            FROM config_store_meta AS meta
            LEFT JOIN sync_mappings AS mapping ON 1=1
            LEFT JOIN sync_unmatched_tracks AS unmatched
              ON unmatched.mapping_id=mapping.id
            WHERE meta.profile_id=?
            ORDER BY mapping.position, mapping.id,
                     unmatched.sync_direction, unmatched.position
            """,
            (PROFILE_ID,),
        ).fetchall()
    if not rows:
        return None

    mappings: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    unmatched_by_id: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        mapping_id = str(row["mapping_id"] or "")
        if not mapping_id:
            continue
        mapping = by_id.get(mapping_id)
        if mapping is None:
            mapping = _object(row["mapping_extra_json"], {})
            if not isinstance(mapping, dict):
                mapping = {}
            unmatched_present = bool(mapping.pop("_config_unmatched_present", False))
            empty_directions = mapping.pop("_config_empty_unmatched_directions", [])
            mapping.update({
                "enabled": bool(row["enabled"]),
                "name": row["name"],
                "direction": row["direction"],
                "collection_type": row["collection_type"],
                "spotify": row["spotify_reference"],
                "tidal": row["tidal_reference"],
                "tidal_name": row["tidal_name"],
            })
            if row["last_sync"] is not None:
                mapping["last_sync"] = row["last_sync"]
            if row["source_version"] is not None:
                mapping["source_version"] = row["source_version"]
            if include_internal:
                mapping["_mapping_id"] = mapping_id
            unmatched = {
                str(direction): [] for direction in empty_directions
            } if isinstance(empty_directions, list) else {}
            if unmatched_present:
                mapping["unmatched"] = unmatched
            mappings.append(mapping)
            by_id[mapping_id] = mapping
            unmatched_by_id[mapping_id] = unmatched
        if row["sync_direction"] is not None:
            payload = _object(row["metadata_json"], {})
            if isinstance(payload, dict):
                unmatched_by_id[mapping_id].setdefault(
                    str(row["sync_direction"]), []
                ).append(payload)
                mapping["unmatched"] = unmatched_by_id[mapping_id]
    return mappings


def _write_sync_mappings(
    connection: Any, mappings: list[dict[str, Any]], now: str,
) -> None:
    connection.execute("DELETE FROM sync_mappings")
    for position, raw_mapping in enumerate(mappings):
        if not isinstance(raw_mapping, dict):
            raise ValueError(f"Playlist mapping {position + 1} must be an object")
        mapping = dict(raw_mapping)
        direction = str(mapping.get("direction") or "spotify_to_tidal")
        collection_type = str(mapping.get("collection_type") or "playlist")
        if direction not in {"spotify_to_tidal", "tidal_to_spotify", "tidal_cache"}:
            raise ValueError(f"Invalid sync direction at mapping {position + 1}")
        if collection_type not in {"playlist", "event", "source"}:
            raise ValueError(f"Invalid collection type at mapping {position + 1}")
        mapping_id = _mapping_id(mapping, position)
        extra = {key: value for key, value in mapping.items() if key not in _MAPPING_FIELDS}
        extra["_config_unmatched_present"] = "unmatched" in mapping
        raw_unmatched = mapping.get("unmatched")
        extra["_config_empty_unmatched_directions"] = [
            str(key) for key, value in raw_unmatched.items()
            if isinstance(raw_unmatched, dict) and isinstance(value, list) and not value
        ] if isinstance(raw_unmatched, dict) else []
        connection.execute(
            """
            INSERT INTO sync_mappings(
                id, name, enabled, direction, collection_type,
                spotify_reference, tidal_reference, tidal_name,
                last_sync, source_version, position, extra_json,
                created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapping_id, str(mapping.get("name") or ""),
                int(bool(mapping.get("enabled", True))), direction, collection_type,
                str(mapping.get("spotify") or ""), str(mapping.get("tidal") or ""),
                str(mapping.get("tidal_name") or ""),
                mapping.get("last_sync") or None, mapping.get("source_version") or None,
                position, _json(extra), now, now,
            ),
        )
        unmatched = raw_unmatched if isinstance(raw_unmatched, dict) else {}
        for sync_direction, records in unmatched.items():
            if not isinstance(records, list):
                continue
            for item_position, raw_record in enumerate(records):
                if not isinstance(raw_record, dict):
                    continue
                record = dict(raw_record)
                connection.execute(
                    """
                    INSERT INTO sync_unmatched_tracks(
                        mapping_id, sync_direction, source_track_key, position,
                        metadata_json, first_seen_at, last_attempted_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mapping_id, str(sync_direction),
                        _unmatched_key(record, item_position), item_position,
                        _json(record), record.get("first_seen_at"),
                        record.get("last_attempted_at"),
                    ),
                )


def replace_sync_mappings(
    mappings: list[dict[str, Any]], path: Path = DATABASE_PATH,
) -> None:
    """Atomically replace mappings without rewriting settings or Quick Views."""
    if not isinstance(mappings, list):
        raise ValueError("The mappings value must be a list")
    now = _now()
    initialize(path)
    with connect(path) as connection:
        _write_sync_mappings(connection, mappings, now)


def _validate_views(views: Any, config_key: str, view_type: str) -> list[dict[str, Any]]:
    if not isinstance(views, list):
        raise ValueError(f"The config '{config_key}' value must be a list")
    if sum(bool(item.get("default")) for item in views if isinstance(item, dict)) > 1:
        raise ValueError(f"Only one {view_type} Quick View can be the default")
    result: list[dict[str, Any]] = []
    for position, raw_view in enumerate(views):
        if not isinstance(raw_view, dict):
            raise ValueError(f"{config_key} item {position + 1} must be an object")
        view = dict(raw_view)
        fields = view.get("fields") or []
        if not isinstance(fields, list):
            raise ValueError(f"Quick View '{view.get('id') or ''}' fields must be a list")
        result.append(view)
    return result


def save_settings_bundle(
    settings: dict[str, Any],
    quick_views: list[dict[str, Any]],
    mix_quick_views: list[dict[str, Any]],
    path: Path = DATABASE_PATH,
) -> None:
    """Save settings and views without hydrating or rewriting sync mappings."""
    if not isinstance(settings, dict):
        raise ValueError("The config 'settings' value must be an object")
    view_groups = (
        ("track", "quick_views", _validate_views(quick_views, "quick_views", "track")),
        ("mix", "mix_quick_views", _validate_views(mix_quick_views, "mix_quick_views", "mix")),
    )
    now = _now()
    initialize(path)
    with connect(path) as connection:
        connection.execute("DELETE FROM quick_views")
        for view_type, _config_key, views in view_groups:
            for position, view in enumerate(views):
                view_id = str(view.get("id") or uuid.uuid4())
                fields = view.get("fields") or []
                extra = {key: value for key, value in view.items() if key not in _VIEW_FIELDS}
                connection.execute(
                    """
                    INSERT INTO quick_views(
                        view_type, id, name, is_default, position,
                        fields_json, extra_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        view_type, view_id, str(view.get("name") or ""),
                        int(bool(view.get("default"))), position,
                        _json([str(field) for field in fields]), _json(extra), now, now,
                    ),
                )
        connection.execute(
            """
            INSERT INTO app_settings(profile_id, settings_json, schema_version, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                settings_json=excluded.settings_json,
                schema_version=excluded.schema_version,
                updated_at=excluded.updated_at
            """,
            (PROFILE_ID, _json(settings), SCHEMA_VERSION, now),
        )
        connection.execute(
            """
            INSERT INTO config_store_meta(profile_id, extra_json, imported_at, updated_at)
            VALUES(?, '{}', ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (PROFILE_ID, now, now),
        )


def export(path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    """Return a portable document without internal SQLite-only identifiers."""
    return load(path, include_internal=False)
