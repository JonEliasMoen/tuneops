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
    album_art_url TEXT NOT NULL DEFAULT '',
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
    date_added TEXT,
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

CREATE TABLE IF NOT EXISTS track_dimension_values (
    provider TEXT NOT NULL,
    provider_track_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_track_id, dimension, value),
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS track_dimensions_by_track
    ON track_dimension_values(provider, provider_track_id, dimension);

CREATE TABLE IF NOT EXISTS setlists (
    folder_name TEXT PRIMARY KEY,
    youtube_url TEXT NOT NULL DEFAULT '',
    tidal_url TEXT NOT NULL DEFAULT '',
    tidal_playlist_id TEXT NOT NULL DEFAULT '',
    tidal_playlist_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setlist_tracks (
    folder_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'tidal',
    provider_track_id TEXT NOT NULL,
    mix_position TEXT NOT NULL DEFAULT '',
    date_added TEXT,
    PRIMARY KEY (folder_name, position),
    FOREIGN KEY (folder_name) REFERENCES setlists(folder_name) ON DELETE CASCADE,
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS setlist_tracks_by_track
    ON setlist_tracks(provider, provider_track_id);
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
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(playlist_tracks)")
        }
        if "date_added" not in columns:
            connection.execute("ALTER TABLE playlist_tracks ADD COLUMN date_added TEXT")
            # Existing memberships predate this field and must be fetched once
            # more before their per-playlist added timestamps are trustworthy.
            connection.execute(
                "UPDATE playlists SET source_last_updated=NULL WHERE provider='tidal'"
            )
        track_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(tracks)")
        }
        if "album_art_url" not in track_columns:
            connection.execute(
                "ALTER TABLE tracks ADD COLUMN album_art_url TEXT NOT NULL DEFAULT ''"
            )
            connection.execute(
                "UPDATE playlists SET source_last_updated=NULL WHERE provider='tidal'"
            )
            connection.execute("DELETE FROM liked_track_snapshots WHERE provider='tidal'")
        legacy_mix_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mixes'"
        ).fetchone()
        if legacy_mix_exists:
            mix_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(mixes)")
            }
            for column in ("tidal_url", "tidal_playlist_id", "tidal_playlist_name"):
                if column not in mix_columns:
                    connection.execute(
                        f"ALTER TABLE mixes ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )
            connection.execute(
                """
                INSERT OR REPLACE INTO setlists(
                    folder_name, youtube_url, tidal_url,
                    tidal_playlist_id, tidal_playlist_name, updated_at
                )
                SELECT folder_name, youtube_url, tidal_url,
                       tidal_playlist_id, tidal_playlist_name, updated_at
                FROM mixes
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO setlist_tracks(
                    folder_name, position, provider, provider_track_id,
                    mix_position, date_added
                )
                SELECT s.folder_name, pt.position, pt.provider,
                       pt.provider_track_id, '', pt.date_added
                FROM setlists s
                JOIN playlist_tracks pt
                  ON pt.provider='tidal'
                 AND pt.provider_playlist_id=s.tidal_playlist_id
                WHERE s.tidal_playlist_id != ''
                """
            )
            # These playlists existed only because the old mix implementation
            # reused playlist storage. Membership now lives in setlist_tracks.
            connection.execute(
                """
                DELETE FROM playlists
                WHERE provider='tidal' AND provider_playlist_id IN (
                    SELECT tidal_playlist_id FROM setlists
                    WHERE tidal_playlist_id != ''
                )
                """
            )
            connection.execute("DROP TABLE mixes")


def setlist_metadata(path: Path = DATABASE_PATH) -> dict[str, dict[str, str]]:
    """Return all persisted user-owned metadata for local setlists."""
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT folder_name, youtube_url, tidal_url,
                   tidal_playlist_id, tidal_playlist_name
            FROM setlists ORDER BY folder_name COLLATE NOCASE
            """
        ).fetchall()
    return {
        str(row["folder_name"]): {
            "youtube_url": str(row["youtube_url"] or ""),
            "tidal_url": str(row["tidal_url"] or ""),
            "tidal_playlist_id": str(row["tidal_playlist_id"] or ""),
            "tidal_playlist_name": str(row["tidal_playlist_name"] or ""),
        }
        for row in rows
    }


def save_setlist_youtube_url(
    folder_name: str, youtube_url: str, path: Path = DATABASE_PATH
) -> None:
    """Persist user-owned metadata for a discovered local mix."""
    name = str(folder_name).strip()
    if not name:
        raise ValueError("Mix folder name cannot be empty")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO setlists(folder_name, youtube_url, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(folder_name) DO UPDATE SET
                youtube_url=excluded.youtube_url,
                updated_at=excluded.updated_at
            """,
            (name, str(youtube_url or "").strip(), datetime.now(timezone.utc).isoformat()),
        )


def save_setlist_tidal_source(
    folder_name: str,
    tidal_url: str,
    playlist_id: str = "",
    playlist_name: str = "",
    path: Path = DATABASE_PATH,
) -> None:
    """Save a setlist's TIDAL import source without creating playlist membership."""
    name = str(folder_name).strip()
    if not name:
        raise ValueError("Mix folder name cannot be empty")
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO setlists(
                folder_name, youtube_url, tidal_url,
                tidal_playlist_id, tidal_playlist_name, updated_at
            ) VALUES(?, '', ?, ?, ?, ?)
            ON CONFLICT(folder_name) DO UPDATE SET
                tidal_url=excluded.tidal_url,
                tidal_playlist_id=excluded.tidal_playlist_id,
                tidal_playlist_name=excluded.tidal_playlist_name,
                updated_at=excluded.updated_at
            """,
            (
                name,
                str(tidal_url or "").strip(),
                str(playlist_id or "").strip(),
                str(playlist_name or "").strip(),
                now,
            ),
        )


def tidal_track_record(track: Any) -> dict[str, Any]:
    """Return all currently useful provider metadata without user-owned fields."""
    artists = getattr(track, "artists", None) or []
    artist_names = [str(getattr(item, "name", "") or "") for item in artists]
    artist_names = [name for name in artist_names if name]
    artist = ", ".join(artist_names) or str(
        getattr(getattr(track, "artist", None), "name", "") or ""
    )
    album = getattr(track, "album", None)
    try:
        album_art_url = album.image(320) if album else ""
    except (AttributeError, TypeError, ValueError):
        album_art_url = ""
    release = getattr(album, "release_date", None) or getattr(track, "tidal_release_date", None)
    release_text = _timestamp(release) or ""
    year = int(release_text[:4]) if len(release_text) >= 4 and release_text[:4].isdigit() else None
    return {
        "id": str(getattr(track, "id", "")),
        "title": str(getattr(track, "name", "") or ""),
        "artist": artist,
        "remix": str(getattr(track, "version", "") or ""),
        "album": str(getattr(album, "name", "") or ""),
        "album_art_url": album_art_url,
        "duration_seconds": getattr(track, "duration", None),
        "bpm": getattr(track, "bpm", None),
        "musical_key": str(getattr(track, "key", "") or ""),
        "key_scale": str(getattr(track, "key_scale", "") or ""),
        "year": year,
        "isrc": str(getattr(track, "isrc", "") or ""),
        "date_added": _timestamp(
            getattr(track, "user_date_added", None) or getattr(track, "date_added", None)
        ),
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
                   t.release_year AS year, t.isrc, t.album_art_url, pt.date_added
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
                    provider, provider_track_id, title, artist, remix, album, album_art_url,
                    duration_seconds, bpm, musical_key, key_scale, release_year,
                    isrc, refreshed_at
                ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, remix=excluded.remix,
                    album=excluded.album, album_art_url=excluded.album_art_url,
                    duration_seconds=excluded.duration_seconds,
                    bpm=excluded.bpm, musical_key=excluded.musical_key,
                    key_scale=excluded.key_scale, release_year=excluded.release_year,
                    isrc=excluded.isrc, refreshed_at=excluded.refreshed_at
                """,
                (
                    track_id, record.get("title", ""), record.get("artist", ""),
                    record.get("remix", ""), record.get("album", ""),
                    record.get("album_art_url", ""),
                    record.get("duration_seconds"), record.get("bpm"),
                    record.get("musical_key", ""), record.get("key_scale", ""),
                    record.get("year"), record.get("isrc", ""), now,
                ),
            )
            connection.execute(
                "INSERT INTO playlist_tracks(provider, provider_playlist_id, position, provider_track_id, date_added) "
                "VALUES('tidal', ?, ?, ?, ?)",
                (playlist_id, position, track_id, record.get("date_added")),
            )


def store_tidal_setlist(
    folder_name: str,
    tidal_url: str,
    playlist: Any,
    tracks: list[Any] | list[dict[str, Any]],
    mix_positions: list[str],
    path: Path = DATABASE_PATH,
) -> None:
    """Replace one setlist inventory without creating indexed-playlist rows."""
    name = str(folder_name).strip()
    if not name:
        raise ValueError("Setlist folder name cannot be empty")
    initialize(path)
    playlist_id = str(getattr(playlist, "id", "") or "")
    playlist_name = str(getattr(playlist, "name", "") or name)
    records = [item if isinstance(item, dict) else tidal_track_record(item) for item in tracks]
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO setlists(
                folder_name, youtube_url, tidal_url,
                tidal_playlist_id, tidal_playlist_name, updated_at
            ) VALUES(?, '', ?, ?, ?, ?)
            ON CONFLICT(folder_name) DO UPDATE SET
                tidal_url=excluded.tidal_url,
                tidal_playlist_id=excluded.tidal_playlist_id,
                tidal_playlist_name=excluded.tidal_playlist_name,
                updated_at=excluded.updated_at
            """,
            (name, str(tidal_url), playlist_id, playlist_name, now),
        )
        connection.execute("DELETE FROM setlist_tracks WHERE folder_name=?", (name,))
        for position, record in enumerate(records):
            track_id = str(record.get("id", ""))
            if not track_id:
                continue
            connection.execute(
                """
                INSERT INTO tracks(
                    provider, provider_track_id, title, artist, remix, album, album_art_url,
                    duration_seconds, bpm, musical_key, key_scale, release_year,
                    isrc, refreshed_at
                ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, remix=excluded.remix,
                    album=excluded.album, album_art_url=excluded.album_art_url,
                    duration_seconds=excluded.duration_seconds,
                    bpm=excluded.bpm, musical_key=excluded.musical_key,
                    key_scale=excluded.key_scale, release_year=excluded.release_year,
                    isrc=excluded.isrc, refreshed_at=excluded.refreshed_at
                """,
                (
                    track_id, record.get("title", ""), record.get("artist", ""),
                    record.get("remix", ""), record.get("album", ""),
                    record.get("album_art_url", ""), record.get("duration_seconds"),
                    record.get("bpm"), record.get("musical_key", ""),
                    record.get("key_scale", ""), record.get("year"),
                    record.get("isrc", ""), now,
                ),
            )
            connection.execute(
                """
                INSERT INTO setlist_tracks(
                    folder_name, position, provider, provider_track_id,
                    mix_position, date_added
                ) VALUES(?, ?, 'tidal', ?, ?, ?)
                """,
                (
                    name,
                    position,
                    track_id,
                    mix_positions[position] if position < len(mix_positions) else "",
                    record.get("date_added"),
                ),
            )


def tidal_setlists_for_track(
    track_id: str, path: Path = DATABASE_PATH
) -> list[dict[str, str]]:
    """Return every setlist containing a TIDAL track, including its timestamp."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT s.folder_name AS id,
                   COALESCE(NULLIF(s.tidal_playlist_name, ''), s.folder_name) AS name,
                   st.mix_position
            FROM setlist_tracks st
            JOIN setlists s ON s.folder_name=st.folder_name
            WHERE st.provider='tidal' AND st.provider_track_id=?
            ORDER BY s.folder_name COLLATE NOCASE, st.position
            """,
            (str(track_id),),
        ).fetchall()
        return [dict(row) for row in rows]


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


def tidal_playlists_for_tracks(
    track_ids: list[str], path: Path = DATABASE_PATH
) -> dict[str, list[dict[str, str]]]:
    """Batch reverse-membership lookup for a set of TIDAL track IDs."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    result: dict[str, list[dict[str, str]]] = {track_id: [] for track_id in unique_ids}
    if not unique_ids or not path.exists():
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT pt.provider_track_id AS track_id,
                            p.provider_playlist_id AS id, p.name
            FROM playlist_tracks pt
            JOIN playlists p
              ON p.provider=pt.provider AND p.provider_playlist_id=pt.provider_playlist_id
            WHERE pt.provider='tidal'
              AND pt.provider_track_id IN ({placeholders})
            ORDER BY p.name COLLATE NOCASE
            """,
            unique_ids,
        ).fetchall()
    for row in rows:
        result[row["track_id"]].append({"id": row["id"], "name": row["name"]})
    return result


def tidal_indexed_playlists(path: Path = DATABASE_PATH) -> list[dict[str, str]]:
    """Return every locally indexed TIDAL playlist in display order."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT provider_playlist_id AS id, name
            FROM playlists
            WHERE provider='tidal'
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]


def tidal_playlist_tracks_page(
    playlist_id: str,
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read one ordered page from an indexed TIDAL playlist."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc, t.album_art_url, pt.date_added
            FROM playlist_tracks pt
            JOIN tracks t
              ON t.provider=pt.provider AND t.provider_track_id=pt.provider_track_id
            WHERE pt.provider='tidal' AND pt.provider_playlist_id=?
            ORDER BY pt.position
            LIMIT ? OFFSET ?
            """,
            (str(playlist_id), int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def tidal_setlist_tracks_page(
    folder_name: str,
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read one ordered page from a setlist, independently of playlists."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc, t.album_art_url,
                   st.date_added, st.mix_position
            FROM setlist_tracks st
            JOIN tracks t
              ON t.provider=st.provider AND t.provider_track_id=st.provider_track_id
            WHERE st.provider='tidal' AND st.folder_name=?
            ORDER BY st.position
            LIMIT ? OFFSET ?
            """,
            (str(folder_name), int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def add_tidal_playlist_membership(
    playlist_id: str, track_id: str, path: Path = DATABASE_PATH
) -> None:
    """Mirror a successful provider add in the local membership index."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        exists = connection.execute(
            """
            SELECT 1 FROM playlist_tracks
            WHERE provider='tidal' AND provider_playlist_id=? AND provider_track_id=?
            LIMIT 1
            """,
            (str(playlist_id), str(track_id)),
        ).fetchone()
        if exists is None:
            position = connection.execute(
                """
                SELECT COALESCE(MAX(position), -1) + 1
                FROM playlist_tracks
                WHERE provider='tidal' AND provider_playlist_id=?
                """,
                (str(playlist_id),),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO playlist_tracks(
                    provider, provider_playlist_id, position, provider_track_id
                ) VALUES('tidal', ?, ?, ?)
                """,
                (str(playlist_id), position, str(track_id)),
            )
        connection.execute(
            """
            UPDATE playlists SET source_last_updated=NULL, indexed_at=?
            WHERE provider='tidal' AND provider_playlist_id=?
            """,
            (now, str(playlist_id)),
        )


def remove_tidal_playlist_membership(
    playlist_id: str, track_id: str, path: Path = DATABASE_PATH
) -> None:
    """Mirror one successful provider removal in the local membership index."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT position FROM playlist_tracks
            WHERE provider='tidal' AND provider_playlist_id=? AND provider_track_id=?
            ORDER BY position LIMIT 1
            """,
            (str(playlist_id), str(track_id)),
        ).fetchone()
        if row is not None:
            connection.execute(
                """
                DELETE FROM playlist_tracks
                WHERE provider='tidal' AND provider_playlist_id=? AND position=?
                """,
                (str(playlist_id), row["position"]),
            )
        connection.execute(
            """
            UPDATE playlists SET source_last_updated=NULL, indexed_at=?
            WHERE provider='tidal' AND provider_playlist_id=?
            """,
            (now, str(playlist_id)),
        )


def tidal_dimensions_for_tracks(
    track_ids: list[str], path: Path = DATABASE_PATH
) -> dict[str, dict[str, list[str]]]:
    """Return all local classification dimensions for several TIDAL tracks."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    result: dict[str, dict[str, list[str]]] = {track_id: {} for track_id in unique_ids}
    if not unique_ids or not path.exists():
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT provider_track_id AS track_id, dimension, value
            FROM track_dimension_values
            WHERE provider='tidal' AND provider_track_id IN ({placeholders})
            ORDER BY dimension, value COLLATE NOCASE
            """,
            unique_ids,
        ).fetchall()
    for row in rows:
        result[row["track_id"]].setdefault(row["dimension"], []).append(row["value"])
    return result


def toggle_tidal_track_dimension(
    track_id: str,
    dimension: str,
    value: str,
    multiple: bool,
    path: Path = DATABASE_PATH,
) -> list[str]:
    """Toggle a local dimension value, optionally enforcing one value only."""
    allowed = {"rating", "energy", "vibe", "movement", "function", "structure"}
    dimension = dimension.strip().lower()
    value = value.strip()
    if dimension not in allowed or not value:
        raise ValueError("Invalid track dimension or value")
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        exists = connection.execute(
            """
            SELECT 1 FROM track_dimension_values
            WHERE provider='tidal' AND provider_track_id=? AND dimension=? AND value=?
            """,
            (str(track_id), dimension, value),
        ).fetchone()
        if exists is not None:
            connection.execute(
                """
                DELETE FROM track_dimension_values
                WHERE provider='tidal' AND provider_track_id=? AND dimension=? AND value=?
                """,
                (str(track_id), dimension, value),
            )
        else:
            if not multiple:
                connection.execute(
                    """
                    DELETE FROM track_dimension_values
                    WHERE provider='tidal' AND provider_track_id=? AND dimension=?
                    """,
                    (str(track_id), dimension),
                )
            connection.execute(
                """
                INSERT INTO track_dimension_values(
                    provider, provider_track_id, dimension, value, created_at
                ) VALUES('tidal', ?, ?, ?, ?)
                """,
                (str(track_id), dimension, value, now),
            )
        rows = connection.execute(
            """
            SELECT value FROM track_dimension_values
            WHERE provider='tidal' AND provider_track_id=? AND dimension=?
            ORDER BY value COLLATE NOCASE
            """,
            (str(track_id), dimension),
        ).fetchall()
        return [row["value"] for row in rows]


def cached_tidal_liked_tracks(
    user_id: str,
    limit: int = 10,
    max_age_seconds: int = 300,
    path: Path = DATABASE_PATH,
    offset: int = 0,
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
                   t.release_year AS year, t.isrc, t.album_art_url, lt.date_added
            FROM liked_tracks lt
            JOIN tracks t
              ON t.provider=lt.provider AND t.provider_track_id=lt.provider_track_id
            WHERE lt.provider='tidal' AND lt.provider_user_id=?
            ORDER BY lt.position
            LIMIT ? OFFSET ?
            """,
            (str(user_id), int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def store_tidal_liked_tracks(
    user_id: str,
    tracks: list[Any],
    path: Path = DATABASE_PATH,
    offset: int = 0,
) -> None:
    """Store one ordered page of a user's liked-track snapshot."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    records = [(tidal_track_record(track), track) for track in tracks]
    with connect(path) as connection:
        if offset == 0:
            connection.execute(
                """
                INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
                VALUES('tidal', ?, ?)
                ON CONFLICT(provider, provider_user_id) DO UPDATE SET cached_at=excluded.cached_at
                """,
                (str(user_id), now),
            )
        connection.execute(
            "DELETE FROM liked_tracks "
            "WHERE provider='tidal' AND provider_user_id=? AND position>=?",
            (str(user_id), int(offset)),
        )
        for position, (record, track) in enumerate(records):
            track_id = record["id"]
            if not track_id:
                continue
            connection.execute(
                """
                INSERT INTO tracks(
                    provider, provider_track_id, title, artist, remix, album, album_art_url,
                    duration_seconds, bpm, musical_key, key_scale, release_year,
                    isrc, refreshed_at
                ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, remix=excluded.remix,
                    album=excluded.album, album_art_url=excluded.album_art_url,
                    duration_seconds=excluded.duration_seconds,
                    bpm=excluded.bpm, musical_key=excluded.musical_key,
                    key_scale=excluded.key_scale, release_year=excluded.release_year,
                    isrc=excluded.isrc, refreshed_at=excluded.refreshed_at
                """,
                (
                    track_id, record["title"], record["artist"], record["remix"],
                    record["album"], record["album_art_url"],
                    record["duration_seconds"], record["bpm"],
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
                (str(user_id), offset + position, track_id, _timestamp(added)),
            )
