"""SQLite cache and extensible local metadata store for the music tools."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = Path(os.getenv("MUSICSYNC_DATABASE", ROOT / "music_library.sqlite3"))


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    provider TEXT NOT NULL,
    provider_track_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    remix TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    bpm REAL,
    musical_key TEXT NOT NULL DEFAULT '',
    key_scale TEXT NOT NULL DEFAULT '',
    release_year INTEGER,
    isrc TEXT NOT NULL DEFAULT '',
    refreshed_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_track_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    provider TEXT NOT NULL,
    provider_playlist_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    source_last_updated TEXT,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_playlist_id)
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    provider TEXT NOT NULL,
    provider_playlist_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    provider_track_id TEXT NOT NULL,
    PRIMARY KEY (provider, provider_playlist_id, position),
    FOREIGN KEY (provider, provider_playlist_id)
        REFERENCES playlists(provider, provider_playlist_id) ON DELETE CASCADE,
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS playlist_tracks_by_track
    ON playlist_tracks(provider, provider_track_id);

CREATE TABLE IF NOT EXISTS liked_track_snapshots (
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS liked_tracks (
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    provider_track_id TEXT NOT NULL,
    date_added TEXT,
    PRIMARY KEY (provider, provider_user_id, position),
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS liked_tracks_by_track
    ON liked_tracks(provider, provider_track_id);

CREATE TABLE IF NOT EXISTS track_user_metadata (
    provider TEXT NOT NULL,
    provider_track_id TEXT NOT NULL,
    star_rating INTEGER CHECK (star_rating BETWEEN 0 AND 5),
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_track_id),
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS track_tags (
    provider TEXT NOT NULL,
    provider_track_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (provider, provider_track_id, tag_id),
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
"""


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


@contextmanager
def connect(path: Path = DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path: Path = DATABASE_PATH) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)


def tidal_track_record(track: Any) -> dict[str, Any]:
    """Return all currently useful provider metadata without user-owned fields."""
    artists = getattr(track, "artists", None) or []
    artist_names = [str(getattr(item, "name", "") or "") for item in artists]
    artist_names = [name for name in artist_names if name]
    artist = ", ".join(artist_names) or str(
        getattr(getattr(track, "artist", None), "name", "") or ""
    )
    album = getattr(track, "album", None)
    release = getattr(album, "release_date", None) or getattr(track, "tidal_release_date", None)
    release_text = _timestamp(release) or ""
    year = int(release_text[:4]) if len(release_text) >= 4 and release_text[:4].isdigit() else None
    return {
        "id": str(getattr(track, "id", "")),
        "title": str(getattr(track, "name", "") or ""),
        "artist": artist,
        "remix": str(getattr(track, "version", "") or ""),
        "album": str(getattr(album, "name", "") or ""),
        "duration_seconds": getattr(track, "duration", None),
        "bpm": getattr(track, "bpm", None),
        "musical_key": str(getattr(track, "key", "") or ""),
        "key_scale": str(getattr(track, "key_scale", "") or ""),
        "year": year,
        "isrc": str(getattr(track, "isrc", "") or ""),
    }


def cached_tidal_playlist(
    playlist_id: str, source_last_updated: Any, path: Path = DATABASE_PATH
) -> list[dict[str, Any]] | None:
    """Return cached tracks only when the provider version matches exactly."""
    version = _timestamp(source_last_updated)
    if version is None or not path.exists():
        return None
    initialize(path)
    with connect(path) as connection:
        playlist = connection.execute(
            "SELECT source_last_updated FROM playlists "
            "WHERE provider = 'tidal' AND provider_playlist_id = ?",
            (str(playlist_id),),
        ).fetchone()
        if playlist is None or playlist["source_last_updated"] != version:
            return None
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc
            FROM playlist_tracks pt
            JOIN tracks t
              ON t.provider = pt.provider AND t.provider_track_id = pt.provider_track_id
            WHERE pt.provider = 'tidal' AND pt.provider_playlist_id = ?
            ORDER BY pt.position
            """,
            (str(playlist_id),),
        ).fetchall()
        return [dict(row) for row in rows]


def store_tidal_playlist(
    playlist: Any,
    tracks: list[Any] | list[dict[str, Any]],
    path: Path = DATABASE_PATH,
    source_last_updated: Any = ...,
) -> None:
    """Atomically replace one playlist inventory while preserving user metadata."""
    initialize(path)
    playlist_id = str(getattr(playlist, "id", playlist))
    playlist_name = str(getattr(playlist, "name", "") or "")
    version = (
        _timestamp(getattr(playlist, "last_updated", None))
        if source_last_updated is ...
        else _timestamp(source_last_updated)
    )
    records = [item if isinstance(item, dict) else tidal_track_record(item) for item in tracks]
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO playlists(provider, provider_playlist_id, name, source_last_updated, indexed_at)
            VALUES('tidal', ?, ?, ?, ?)
            ON CONFLICT(provider, provider_playlist_id) DO UPDATE SET
                name=excluded.name,
                source_last_updated=excluded.source_last_updated,
                indexed_at=excluded.indexed_at
            """,
            (playlist_id, playlist_name, version, now),
        )
        connection.execute(
            "DELETE FROM playlist_tracks WHERE provider='tidal' AND provider_playlist_id=?",
            (playlist_id,),
        )
        for position, record in enumerate(records):
            track_id = str(record.get("id", ""))
            if not track_id:
                continue
            connection.execute(
                """
                INSERT INTO tracks(
                    provider, provider_track_id, title, artist, remix, album,
                    duration_seconds, bpm, musical_key, key_scale, release_year,
                    isrc, refreshed_at
                ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, remix=excluded.remix,
                    album=excluded.album, duration_seconds=excluded.duration_seconds,
                    bpm=excluded.bpm, musical_key=excluded.musical_key,
                    key_scale=excluded.key_scale, release_year=excluded.release_year,
                    isrc=excluded.isrc, refreshed_at=excluded.refreshed_at
                """,
                (
                    track_id, record.get("title", ""), record.get("artist", ""),
                    record.get("remix", ""), record.get("album", ""),
                    record.get("duration_seconds"), record.get("bpm"),
                    record.get("musical_key", ""), record.get("key_scale", ""),
                    record.get("year"), record.get("isrc", ""), now,
                ),
            )
            connection.execute(
                "INSERT INTO playlist_tracks(provider, provider_playlist_id, position, provider_track_id) "
                "VALUES('tidal', ?, ?, ?)",
                (playlist_id, position, track_id),
            )


def tidal_playlists_for_track(
    track_id: str, path: Path = DATABASE_PATH
) -> list[dict[str, str]]:
    """Reverse membership lookup supported by the playlist_tracks index."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT p.provider_playlist_id AS id, p.name
            FROM playlist_tracks pt
            JOIN playlists p
              ON p.provider = pt.provider AND p.provider_playlist_id = pt.provider_playlist_id
            WHERE pt.provider='tidal' AND pt.provider_track_id=?
            ORDER BY p.name COLLATE NOCASE
            """,
            (str(track_id),),
        ).fetchall()
        return [dict(row) for row in rows]


def cached_tidal_liked_tracks(
    user_id: str,
    limit: int = 10,
    max_age_seconds: int = 300,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]] | None:
    """Return a recent liked-tracks snapshot, or None when it needs refreshing."""
    if not path.exists():
        return None
    initialize(path)
    with connect(path) as connection:
        snapshot = connection.execute(
            "SELECT cached_at FROM liked_track_snapshots "
            "WHERE provider='tidal' AND provider_user_id=?",
            (str(user_id),),
        ).fetchone()
        if snapshot is None:
            return None
        cached_at = datetime.fromisoformat(snapshot["cached_at"])
        age = (datetime.now(timezone.utc) - cached_at.astimezone(timezone.utc)).total_seconds()
        if age > max_age_seconds:
            return None
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc, lt.date_added
            FROM liked_tracks lt
            JOIN tracks t
              ON t.provider=lt.provider AND t.provider_track_id=lt.provider_track_id
            WHERE lt.provider='tidal' AND lt.provider_user_id=?
            ORDER BY lt.position
            LIMIT ?
            """,
            (str(user_id), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]


def store_tidal_liked_tracks(
    user_id: str,
    tracks: list[Any],
    path: Path = DATABASE_PATH,
) -> None:
    """Atomically replace one user's cached liked-track snapshot."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    records = [(tidal_track_record(track), track) for track in tracks]
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', ?, ?)
            ON CONFLICT(provider, provider_user_id) DO UPDATE SET cached_at=excluded.cached_at
            """,
            (str(user_id), now),
        )
        connection.execute(
            "DELETE FROM liked_tracks WHERE provider='tidal' AND provider_user_id=?",
            (str(user_id),),
        )
        for position, (record, track) in enumerate(records):
            track_id = record["id"]
            if not track_id:
                continue
            connection.execute(
                """
                INSERT INTO tracks(
                    provider, provider_track_id, title, artist, remix, album,
                    duration_seconds, bpm, musical_key, key_scale, release_year,
                    isrc, refreshed_at
                ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, remix=excluded.remix,
                    album=excluded.album, duration_seconds=excluded.duration_seconds,
                    bpm=excluded.bpm, musical_key=excluded.musical_key,
                    key_scale=excluded.key_scale, release_year=excluded.release_year,
                    isrc=excluded.isrc, refreshed_at=excluded.refreshed_at
                """,
                (
                    track_id, record["title"], record["artist"], record["remix"],
                    record["album"], record["duration_seconds"], record["bpm"],
                    record["musical_key"], record["key_scale"], record["year"],
                    record["isrc"], now,
                ),
            )
            added = getattr(track, "user_date_added", None) or getattr(track, "date_added", None)
            connection.execute(
                """
                INSERT INTO liked_tracks(
                    provider, provider_user_id, position, provider_track_id, date_added
                ) VALUES('tidal', ?, ?, ?, ?)
                """,
                (str(user_id), position, track_id, _timestamp(added)),
            )
