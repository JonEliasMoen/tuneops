"""SQLite cache and extensible local metadata store for the music tools."""

from __future__ import annotations

import os
import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from music_library.dimensions import DIMENSION_MAX_VALUES, DIMENSION_VALUES


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

CREATE TABLE IF NOT EXISTS artists (
    provider TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    provider_artist_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    PRIMARY KEY (provider, artist_key)
);

CREATE TABLE IF NOT EXISTS track_artists (
    provider TEXT NOT NULL,
    provider_track_id TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (provider, provider_track_id, artist_key),
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE,
    FOREIGN KEY (provider, artist_key)
        REFERENCES artists(provider, artist_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS track_artists_by_artist
    ON track_artists(provider, artist_key, provider_track_id);

CREATE TABLE IF NOT EXISTS playlists (
    provider TEXT NOT NULL,
    provider_playlist_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    collection_type TEXT NOT NULL DEFAULT 'playlist',
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

CREATE TABLE IF NOT EXISTS event_links (
    provider TEXT NOT NULL DEFAULT 'tidal',
    provider_playlist_id TEXT NOT NULL,
    youtube_url TEXT NOT NULL DEFAULT '',
    concert_archives_url TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_playlist_id),
    FOREIGN KEY (provider, provider_playlist_id)
        REFERENCES playlists(provider, provider_playlist_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lastfm_scrobbles (
    username TEXT NOT NULL,
    played_at INTEGER NOT NULL,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    mbid TEXT NOT NULL DEFAULT '',
    normalized_artist TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    tidal_track_id TEXT,
    match_confidence TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL,
    PRIMARY KEY (username, played_at, normalized_artist, normalized_title)
);

CREATE INDEX IF NOT EXISTS lastfm_scrobbles_by_tidal_track
    ON lastfm_scrobbles(username, tidal_track_id, played_at);

CREATE INDEX IF NOT EXISTS lastfm_scrobbles_by_month
    ON lastfm_scrobbles(username, played_at);

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

CREATE TABLE IF NOT EXISTS youtube_mix_analytics (
    folder_name TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    estimated_minutes_watched REAL NOT NULL DEFAULT 0,
    average_view_duration REAL NOT NULL DEFAULT 0,
    average_view_percentage REAL NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    subscribers_gained INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_video_metadata (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    upload_date TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watched_mixes (
    video_id TEXT PRIMARY KEY,
    youtube_url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT '',
    upload_date TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watched_mix_tracks (
    video_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'tidal',
    provider_track_id TEXT NOT NULL,
    associated_at TEXT NOT NULL,
    PRIMARY KEY (video_id, provider, provider_track_id),
    FOREIGN KEY (video_id) REFERENCES watched_mixes(video_id) ON DELETE CASCADE,
    FOREIGN KEY (provider, provider_track_id)
        REFERENCES tracks(provider, provider_track_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS watched_mix_tracks_by_track
    ON watched_mix_tracks(provider, provider_track_id);

CREATE TABLE IF NOT EXISTS pending_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_artist TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    mix_position TEXT NOT NULL DEFAULT '',
    raw_line TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_checked_at TEXT,
    resolved_at TEXT,
    UNIQUE(video_id, normalized_artist, normalized_title),
    FOREIGN KEY (video_id) REFERENCES watched_mixes(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS pending_tracks_by_status
    ON pending_tracks(status, created_at);
"""


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _artist_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(name or "")).casefold()
    return " ".join(normalized.split())


def _record_artists(record: dict[str, Any]) -> list[dict[str, str]]:
    artists = record.get("artists") or []
    cleaned = [
        {"id": str(item.get("id") or ""), "name": str(item.get("name") or "").strip()}
        for item in artists
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if cleaned:
        return cleaned
    return [
        {"id": "", "name": name.strip()}
        for name in str(record.get("artist") or "").split(",")
        if name.strip()
    ]


def _store_track_artists(
    connection: sqlite3.Connection, track_id: str, record: dict[str, Any]
) -> None:
    connection.execute(
        "DELETE FROM track_artists WHERE provider='tidal' AND provider_track_id=?",
        (str(track_id),),
    )
    seen: set[str] = set()
    for position, artist in enumerate(_record_artists(record)):
        name = artist["name"]
        key = _artist_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        connection.execute(
            """
            INSERT INTO artists(
                provider, artist_key, provider_artist_id, name, normalized_name
            ) VALUES('tidal', ?, ?, ?, ?)
            ON CONFLICT(provider, artist_key) DO UPDATE SET
                provider_artist_id=CASE
                    WHEN excluded.provider_artist_id != '' THEN excluded.provider_artist_id
                    ELSE artists.provider_artist_id
                END,
                name=excluded.name,
                normalized_name=excluded.normalized_name
            """,
            (key, artist["id"], name, key),
        )
        connection.execute(
            """
            INSERT INTO track_artists(
                provider, provider_track_id, artist_key, position
            ) VALUES('tidal', ?, ?, ?)
            """,
            (str(track_id), key, position),
        )


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
        # A like is a membership, not a playlist occurrence. Older cache builds
        # could retain the same TIDAL track across overlapping paged snapshots.
        # Keep its earliest position/date and permanently enforce that invariant.
        connection.execute(
            """
            DELETE FROM liked_tracks AS duplicate
            WHERE EXISTS (
                SELECT 1 FROM liked_tracks AS original
                WHERE original.provider=duplicate.provider
                  AND original.provider_user_id=duplicate.provider_user_id
                  AND original.provider_track_id=duplicate.provider_track_id
                  AND original.position < duplicate.position
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS liked_tracks_unique_membership
            ON liked_tracks(provider, provider_user_id, provider_track_id)
            """
        )
        # A playlist cache is also membership-based. Keep the first provider
        # occurrence if an older overlapping fetch stored a track twice.
        connection.execute(
            """
            DELETE FROM playlist_tracks AS duplicate
            WHERE EXISTS (
                SELECT 1 FROM playlist_tracks AS original
                WHERE original.provider=duplicate.provider
                  AND original.provider_playlist_id=duplicate.provider_playlist_id
                  AND original.provider_track_id=duplicate.provider_track_id
                  AND original.position < duplicate.position
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS playlist_tracks_unique_membership
            ON playlist_tracks(provider, provider_playlist_id, provider_track_id)
            """
        )
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
        playlist_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(playlists)")
        }
        if "collection_type" not in playlist_columns:
            connection.execute(
                "ALTER TABLE playlists ADD COLUMN collection_type "
                "TEXT NOT NULL DEFAULT 'playlist'"
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
        watched_mix_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(watched_mixes)")
        }
        for column in ("title", "channel_name", "upload_date"):
            if column not in watched_mix_columns:
                connection.execute(
                    f"ALTER TABLE watched_mixes ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT ''"
                )
        missing_artist_rows = connection.execute(
            """
            SELECT t.provider_track_id, t.artist
            FROM tracks t
            WHERE t.provider='tidal' AND t.artist != ''
              AND NOT EXISTS (
                  SELECT 1 FROM track_artists ta
                  WHERE ta.provider=t.provider
                    AND ta.provider_track_id=t.provider_track_id
              )
            """
        ).fetchall()
        for row in missing_artist_rows:
            _store_track_artists(
                connection,
                row["provider_track_id"],
                {"artist": row["artist"]},
            )
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


def event_links(
    playlist_id: str, path: Path = DATABASE_PATH
) -> dict[str, str]:
    """Return the user-owned links associated with one indexed TIDAL event."""
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT youtube_url, concert_archives_url, updated_at
            FROM event_links
            WHERE provider='tidal' AND provider_playlist_id=?
            """,
            (str(playlist_id),),
        ).fetchone()
    return dict(row) if row else {
        "youtube_url": "",
        "concert_archives_url": "",
        "updated_at": "",
    }


def save_event_links(
    playlist_id: str,
    youtube_url: str,
    concert_archives_url: str,
    path: Path = DATABASE_PATH,
) -> None:
    """Persist event links without fetching either destination."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO event_links(
                provider, provider_playlist_id, youtube_url,
                concert_archives_url, updated_at
            ) VALUES('tidal', ?, ?, ?, ?)
            ON CONFLICT(provider, provider_playlist_id) DO UPDATE SET
                youtube_url=excluded.youtube_url,
                concert_archives_url=excluded.concert_archives_url,
                updated_at=excluded.updated_at
            """,
            (
                str(playlist_id), str(youtube_url or "").strip(),
                str(concert_archives_url or "").strip(), now,
            ),
        )


def lastfm_latest_scrobble(
    username: str, path: Path = DATABASE_PATH
) -> int | None:
    """Return the newest imported Last.fm play timestamp for one user."""
    initialize(path)
    with connect(path) as connection:
        value = connection.execute(
            "SELECT MAX(played_at) FROM lastfm_scrobbles WHERE username=?",
            (str(username).casefold(),),
        ).fetchone()[0]
    return int(value) if value is not None else None


def store_lastfm_scrobbles(
    username: str,
    records: list[dict[str, Any]],
    path: Path = DATABASE_PATH,
) -> int:
    """Insert immutable Last.fm plays and return the number newly stored."""
    if not records:
        return 0
    initialize(path)
    imported_at = datetime.now(timezone.utc).isoformat()
    user_key = str(username).strip().casefold()
    with connect(path) as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT OR IGNORE INTO lastfm_scrobbles(
                username, played_at, artist, title, album, mbid,
                normalized_artist, normalized_title, imported_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_key,
                    int(record["played_at"]),
                    str(record.get("artist") or ""),
                    str(record.get("title") or ""),
                    str(record.get("album") or ""),
                    str(record.get("mbid") or ""),
                    str(record.get("normalized_artist") or ""),
                    str(record.get("normalized_title") or ""),
                    imported_at,
                )
                for record in records
            ],
        )
        return connection.total_changes - before


def lastfm_unmatched_identities(
    username: str, path: Path = DATABASE_PATH
) -> list[dict[str, str]]:
    """Return distinct imported identities that still lack a TIDAL match."""
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT normalized_artist, normalized_title,
                   MIN(artist) AS artist, MIN(title) AS title
            FROM lastfm_scrobbles
            WHERE username=? AND tidal_track_id IS NULL
            GROUP BY normalized_artist, normalized_title
            """,
            (str(username).strip().casefold(),),
        ).fetchall()
    return [dict(row) for row in rows]


def set_lastfm_track_match(
    username: str,
    normalized_artist: str,
    normalized_title: str,
    track_id: str,
    confidence: str,
    path: Path = DATABASE_PATH,
) -> None:
    """Apply one conservative identity match to all corresponding scrobbles."""
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            UPDATE lastfm_scrobbles
            SET tidal_track_id=?, match_confidence=?
            WHERE username=? AND normalized_artist=? AND normalized_title=?
            """,
            (
                str(track_id), str(confidence), str(username).strip().casefold(),
                str(normalized_artist), str(normalized_title),
            ),
        )


def set_lastfm_track_matches(
    username: str,
    matches: list[dict[str, str]],
    path: Path = DATABASE_PATH,
) -> int:
    """Apply several conservative Last.fm-to-TIDAL identity matches at once."""
    if not matches:
        return 0
    initialize(path)
    user_key = str(username).strip().casefold()
    with connect(path) as connection:
        before = connection.total_changes
        connection.executemany(
            """
            UPDATE lastfm_scrobbles
            SET tidal_track_id=?, match_confidence=?
            WHERE username=? AND normalized_artist=? AND normalized_title=?
              AND tidal_track_id IS NULL
            """,
            [
                (
                    str(match["track_id"]), str(match["confidence"]), user_key,
                    str(match["normalized_artist"]),
                    str(match["normalized_title"]),
                )
                for match in matches
            ],
        )
        return connection.total_changes - before


def lastfm_track_stats(
    username: str,
    track_ids: list[str],
    path: Path = DATABASE_PATH,
) -> dict[str, dict[str, Any]]:
    """Return play count and most recent play for matched TIDAL tracks."""
    unique_ids = list(dict.fromkeys(str(value) for value in track_ids if value))
    if not unique_ids or not str(username or "").strip():
        return {}
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT tidal_track_id, COUNT(*) AS play_count,
                   MAX(played_at) AS last_played
            FROM lastfm_scrobbles
            WHERE username=? AND tidal_track_id IN ({placeholders})
            GROUP BY tidal_track_id
            """,
            [str(username).strip().casefold(), *unique_ids],
        ).fetchall()
    return {
        str(row["tidal_track_id"]): {
            "play_count": int(row["play_count"]),
            "last_played": int(row["last_played"]),
        }
        for row in rows
    }


def lastfm_history_months(
    username: str,
    minimum_tracks: int = 20,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Return months containing at least the requested distinct matched tracks."""
    if not str(username or "").strip():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT strftime('%Y', played_at, 'unixepoch', 'localtime') AS year,
                   strftime('%m', played_at, 'unixepoch', 'localtime') AS month,
                   COUNT(DISTINCT tidal_track_id) AS track_count,
                   COUNT(*) AS play_count
            FROM lastfm_scrobbles
            WHERE username=? AND tidal_track_id IS NOT NULL
            GROUP BY year, month
            HAVING COUNT(DISTINCT tidal_track_id) >= ?
            ORDER BY year DESC, month DESC
            """,
            (str(username).strip().casefold(), max(1, int(minimum_tracks))),
        ).fetchall()
    return [dict(row) for row in rows]


def lastfm_history_years(
    username: str,
    minimum_tracks: int = 20,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Return years containing at least the requested distinct matched tracks."""
    if not str(username or "").strip():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT strftime('%Y', played_at, 'unixepoch', 'localtime') AS year,
                   COUNT(DISTINCT tidal_track_id) AS track_count,
                   COUNT(*) AS play_count
            FROM lastfm_scrobbles
            WHERE username=? AND tidal_track_id IS NOT NULL
            GROUP BY year
            HAVING COUNT(DISTINCT tidal_track_id) >= ?
            ORDER BY year DESC
            """,
            (str(username).strip().casefold(), max(1, int(minimum_tracks))),
        ).fetchall()
    return [dict(row) for row in rows]


def lastfm_month_top_tracks(
    username: str,
    year: int,
    month: int,
    limit: int = 20,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Return the most-played matched TIDAL tracks for one local calendar month."""
    if not str(username or "").strip() or month < 1 or month > 12:
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix,
                   t.album, t.album_art_url, t.duration_seconds, t.bpm,
                   t.musical_key, t.key_scale, t.release_year AS year, t.isrc,
                   COUNT(*) AS play_count, MAX(ls.played_at) AS last_played
            FROM lastfm_scrobbles ls
            JOIN tracks t ON t.provider='tidal'
                         AND t.provider_track_id=ls.tidal_track_id
            WHERE ls.username=?
              AND strftime('%Y', ls.played_at, 'unixepoch', 'localtime')=?
              AND strftime('%m', ls.played_at, 'unixepoch', 'localtime')=?
            GROUP BY ls.tidal_track_id
            ORDER BY play_count DESC, last_played DESC, t.title COLLATE NOCASE
            LIMIT ?
            """,
            (str(username).strip().casefold(), f"{int(year):04d}", f"{int(month):02d}", max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def lastfm_year_top_tracks(
    username: str,
    year: int,
    limit: int = 20,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Return the most-played matched TIDAL tracks for one local calendar year."""
    if not str(username or "").strip():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix,
                   t.album, t.album_art_url, t.duration_seconds, t.bpm,
                   t.musical_key, t.key_scale, t.release_year AS year, t.isrc,
                   COUNT(*) AS play_count, MAX(ls.played_at) AS last_played
            FROM lastfm_scrobbles ls
            JOIN tracks t ON t.provider='tidal'
                         AND t.provider_track_id=ls.tidal_track_id
            WHERE ls.username=?
              AND strftime('%Y', ls.played_at, 'unixepoch', 'localtime')=?
            GROUP BY ls.tidal_track_id
            ORDER BY play_count DESC, last_played DESC, t.title COLLATE NOCASE
            LIMIT ?
            """,
            (str(username).strip().casefold(), f"{int(year):04d}", max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def lastfm_all_time_top_tracks(
    username: str,
    limit: int = 20,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Return the most-played matched TIDAL tracks across all cached history."""
    if not str(username or "").strip():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix,
                   t.album, t.album_art_url, t.duration_seconds, t.bpm,
                   t.musical_key, t.key_scale, t.release_year AS year, t.isrc,
                   COUNT(*) AS play_count, MAX(ls.played_at) AS last_played
            FROM lastfm_scrobbles ls
            JOIN tracks t ON t.provider='tidal'
                         AND t.provider_track_id=ls.tidal_track_id
            WHERE ls.username=?
            GROUP BY ls.tidal_track_id
            ORDER BY play_count DESC, last_played DESC, t.title COLLATE NOCASE
            LIMIT ?
            """,
            (str(username).strip().casefold(), max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def lastfm_import_summary(
    username: str, path: Path = DATABASE_PATH
) -> dict[str, Any]:
    """Summarize the local Last.fm history cache for Settings."""
    if not str(username or "").strip():
        return {"scrobbles": 0, "matched": 0, "latest": None}
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS scrobbles,
                   SUM(CASE WHEN tidal_track_id IS NOT NULL THEN 1 ELSE 0 END) AS matched,
                   MAX(played_at) AS latest
            FROM lastfm_scrobbles WHERE username=?
            """,
            (str(username).strip().casefold(),),
        ).fetchone()
    return {
        "scrobbles": int(row["scrobbles"] or 0),
        "matched": int(row["matched"] or 0),
        "latest": int(row["latest"]) if row["latest"] is not None else None,
    }


def setlist_metadata(path: Path = DATABASE_PATH) -> dict[str, dict[str, Any]]:
    """Return all persisted user-owned metadata for local setlists."""
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT s.folder_name, s.youtube_url, s.tidal_url,
                   s.tidal_playlist_id, s.tidal_playlist_name, s.updated_at,
                   COUNT(st.provider_track_id) AS track_count,
                   ya.video_id, ya.views, ya.estimated_minutes_watched,
                   ya.average_view_duration, ya.average_view_percentage,
                   ya.likes, ya.comments, ya.subscribers_gained,
                   ya.fetched_at AS analytics_fetched_at
            FROM setlists AS s
            LEFT JOIN setlist_tracks AS st ON st.folder_name = s.folder_name
            LEFT JOIN youtube_mix_analytics AS ya ON ya.folder_name = s.folder_name
            GROUP BY s.folder_name, s.youtube_url, s.tidal_url,
                     s.tidal_playlist_id, s.tidal_playlist_name, s.updated_at,
                     ya.video_id, ya.views, ya.estimated_minutes_watched,
                     ya.average_view_duration, ya.average_view_percentage,
                     ya.likes, ya.comments, ya.subscribers_gained, ya.fetched_at
            ORDER BY s.folder_name COLLATE NOCASE
            """
        ).fetchall()
    return {
        str(row["folder_name"]): {
            "youtube_url": str(row["youtube_url"] or ""),
            "tidal_url": str(row["tidal_url"] or ""),
            "tidal_playlist_id": str(row["tidal_playlist_id"] or ""),
            "tidal_playlist_name": str(row["tidal_playlist_name"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "track_count": int(row["track_count"] or 0),
            "youtube_video_id": str(row["video_id"] or ""),
            "youtube_views": int(row["views"] or 0) if row["video_id"] else None,
            "youtube_watch_minutes": float(row["estimated_minutes_watched"] or 0) if row["video_id"] else None,
            "youtube_average_view_duration": float(row["average_view_duration"] or 0) if row["video_id"] else None,
            "youtube_average_view_percentage": float(row["average_view_percentage"] or 0) if row["video_id"] else None,
            "youtube_likes": int(row["likes"] or 0) if row["video_id"] else None,
            "youtube_comments": int(row["comments"] or 0) if row["video_id"] else None,
            "youtube_subscribers_gained": int(row["subscribers_gained"] or 0) if row["video_id"] else None,
            "youtube_analytics_fetched_at": str(row["analytics_fetched_at"] or ""),
        }
        for row in rows
    }


def store_youtube_mix_analytics(
    records: list[dict[str, Any]], path: Path = DATABASE_PATH,
) -> int:
    """Upsert independent cached YouTube Analytics rows for local mixes."""
    initialize(path)
    fetched_at = datetime.now(timezone.utc).isoformat()
    accepted = [
        record for record in records
        if str(record.get("folder_name") or "") and str(record.get("video_id") or "")
    ]
    with connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO youtube_mix_analytics(
                folder_name, video_id, views, estimated_minutes_watched,
                average_view_duration, average_view_percentage, likes,
                comments, subscribers_gained, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(folder_name) DO UPDATE SET
                video_id=excluded.video_id,
                views=excluded.views,
                estimated_minutes_watched=excluded.estimated_minutes_watched,
                average_view_duration=excluded.average_view_duration,
                average_view_percentage=excluded.average_view_percentage,
                likes=excluded.likes,
                comments=excluded.comments,
                subscribers_gained=excluded.subscribers_gained,
                fetched_at=excluded.fetched_at
            """,
            [
                (
                    str(record.get("folder_name") or ""),
                    str(record.get("video_id") or ""),
                    int(record.get("views") or 0),
                    float(record.get("estimatedMinutesWatched") or 0),
                    float(record.get("averageViewDuration") or 0),
                    float(record.get("averageViewPercentage") or 0),
                    int(record.get("likes") or 0),
                    int(record.get("comments") or 0),
                    int(record.get("subscribersGained") or 0),
                    fetched_at,
                )
                for record in accepted
            ],
        )
    return len(accepted)


def store_youtube_video_metadata(
    records: list[dict[str, Any]], path: Path = DATABASE_PATH,
) -> int:
    """Upsert independent cached public metadata for YouTube videos."""
    initialize(path)
    fetched_at = datetime.now(timezone.utc).isoformat()
    accepted = [record for record in records if str(record.get("video_id") or "").strip()]
    with connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO youtube_video_metadata(video_id, title, upload_date, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title=excluded.title,
                upload_date=excluded.upload_date,
                fetched_at=excluded.fetched_at
            """,
            [
                (
                    str(record.get("video_id") or "").strip(),
                    str(record.get("title") or "").strip(),
                    str(record.get("upload_date") or "").strip(),
                    fetched_at,
                )
                for record in accepted
            ],
        )
    return len(accepted)


def youtube_video_metadata(path: Path = DATABASE_PATH) -> dict[str, dict[str, str]]:
    """Return cached YouTube metadata keyed by video ID."""
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT video_id, title, upload_date, fetched_at FROM youtube_video_metadata"
        ).fetchall()
    return {str(row["video_id"]): dict(row) for row in rows}


def watched_mixes(path: Path = DATABASE_PATH) -> list[dict[str, str]]:
    """Return manually saved YouTube mixes, newest first."""
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT video_id, youtube_url, title, channel_name, upload_date, added_at
            FROM watched_mixes
            ORDER BY added_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def watched_mix(video_id: str, path: Path = DATABASE_PATH) -> dict[str, str] | None:
    """Return one saved YouTube mix."""
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT video_id, youtube_url, title, channel_name, upload_date, added_at
            FROM watched_mixes WHERE video_id=?
            """,
            (str(video_id),),
        ).fetchone()
    return dict(row) if row else None


def save_watched_mix(
    video_id: str,
    youtube_url: str,
    title: str = "",
    channel_name: str = "",
    upload_date: str = "",
    path: Path = DATABASE_PATH,
) -> dict[str, str]:
    """Save a validated watched-mix URL without overwriting its first-added date."""
    normalized_id = str(video_id or "").strip()
    normalized_url = str(youtube_url or "").strip()
    if not normalized_id or not normalized_url:
        raise ValueError("A YouTube video ID and URL are required")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO watched_mixes(
                video_id, youtube_url, title, channel_name, upload_date, added_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                youtube_url=excluded.youtube_url,
                title=excluded.title,
                channel_name=excluded.channel_name,
                upload_date=excluded.upload_date
            """,
            (
                normalized_id,
                normalized_url,
                str(title or "").strip(),
                str(channel_name or "").strip(),
                str(upload_date or "").strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return watched_mix(normalized_id, path) or {}


def delete_watched_mix(video_id: str, path: Path = DATABASE_PATH) -> bool:
    """Remove one user-managed watched mix and its dependent associations."""
    initialize(path)
    with connect(path) as connection:
        cursor = connection.execute(
            "DELETE FROM watched_mixes WHERE video_id=?", (str(video_id),)
        )
    return cursor.rowcount > 0


def associate_tidal_tracks_with_watched_mix(
    video_id: str, track_ids: list[str], path: Path = DATABASE_PATH
) -> int:
    """Associate existing local TIDAL tracks with a watched mix in input order."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    if not unique_ids:
        return 0
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        if connection.execute(
            "SELECT 1 FROM watched_mixes WHERE video_id=?", (str(video_id),)
        ).fetchone() is None:
            raise ValueError("Watched mix was not found")
        next_position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM watched_mix_tracks WHERE video_id=?",
            (str(video_id),),
        ).fetchone()[0]
        added = 0
        for track_id in unique_ids:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO watched_mix_tracks(
                    video_id, position, provider, provider_track_id, associated_at
                ) VALUES(?, ?, 'tidal', ?, ?)
                """,
                (str(video_id), next_position + added, track_id, now),
            )
            added += cursor.rowcount
    return added


def add_pending_track(
    video_id: str,
    artist: str,
    title: str,
    mix_position: str = "",
    raw_line: str = "",
    path: Path = DATABASE_PATH,
) -> tuple[dict[str, Any], bool]:
    """Add an unresolved watched-mix track to the persistent search queue."""
    clean_artist = str(artist or "").strip()
    clean_title = str(title or "").strip()
    if not clean_artist or not clean_title:
        raise ValueError("Pending tracks require both an artist and a title")
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    normalized_artist = _artist_key(clean_artist)
    normalized_title = _artist_key(clean_title)
    with connect(path) as connection:
        if connection.execute(
            "SELECT 1 FROM watched_mixes WHERE video_id=?", (str(video_id),)
        ).fetchone() is None:
            raise ValueError("Watched mix was not found")
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO pending_tracks(
                video_id, artist, title, normalized_artist, normalized_title,
                mix_position, raw_line, status, candidates_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 'pending', '[]', ?)
            """,
            (
                str(video_id), clean_artist, clean_title, normalized_artist,
                normalized_title, str(mix_position or ""), str(raw_line or ""), now,
            ),
        )
        row = connection.execute(
            """
            SELECT id FROM pending_tracks
            WHERE video_id=? AND normalized_artist=? AND normalized_title=?
            """,
            (str(video_id), normalized_artist, normalized_title),
        ).fetchone()
        pending_id = int(row["id"])
    return pending_track(pending_id, path) or {}, bool(cursor.rowcount)


def _pending_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    try:
        candidates = json.loads(record.pop("candidates_json", "[]") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        candidates = []
    record["candidates"] = candidates if isinstance(candidates, list) else []
    return record


def pending_track(pending_id: int, path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    """Return one queued track together with its watched-mix metadata."""
    if not path.exists():
        return None
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT pt.*, wm.title AS mix_title, wm.channel_name
            FROM pending_tracks pt
            JOIN watched_mixes wm ON wm.video_id=pt.video_id
            WHERE pt.id=?
            """,
            (int(pending_id),),
        ).fetchone()
    return _pending_record(row) if row else None


def pending_tracks(path: Path = DATABASE_PATH) -> list[dict[str, Any]]:
    """Return the active pending queue, oldest discoveries first."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT pt.*, wm.title AS mix_title, wm.channel_name
            FROM pending_tracks pt
            JOIN watched_mixes wm ON wm.video_id=pt.video_id
            WHERE pt.status != 'resolved'
            ORDER BY pt.created_at, pt.id
            """
        ).fetchall()
    return [_pending_record(row) for row in rows]


def update_pending_track_candidates(
    pending_id: int,
    candidates: list[dict[str, Any]],
    status: str,
    path: Path = DATABASE_PATH,
) -> None:
    """Persist the latest TIDAL search result for one pending track."""
    if status not in {"matched", "ambiguous", "not_found", "pending"}:
        raise ValueError(f"Invalid pending-track status: {status}")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            UPDATE pending_tracks
            SET candidates_json=?, status=?, last_checked_at=?
            WHERE id=?
            """,
            (
                json.dumps(candidates, ensure_ascii=False),
                status,
                datetime.now(timezone.utc).isoformat(),
                int(pending_id),
            ),
        )


def resolve_pending_track(pending_id: int, path: Path = DATABASE_PATH) -> None:
    """Mark a pending track resolved while retaining its discovery history."""
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            UPDATE pending_tracks SET status='resolved', resolved_at=? WHERE id=?
            """,
            (datetime.now(timezone.utc).isoformat(), int(pending_id)),
        )


def delete_pending_track(pending_id: int, path: Path = DATABASE_PATH) -> None:
    """Remove one unwanted item from the pending queue."""
    if not path.exists():
        return
    initialize(path)
    with connect(path) as connection:
        connection.execute("DELETE FROM pending_tracks WHERE id=?", (int(pending_id),))


def tidal_watched_mix_tracks_page(
    video_id: str,
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read an ordered page of tracks associated with one watched mix."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix, t.album,
                   t.duration_seconds, t.bpm, t.musical_key, t.key_scale,
                   t.release_year AS year, t.isrc, t.album_art_url,
                   wmt.associated_at AS date_added
            FROM watched_mix_tracks wmt
            JOIN tracks t
              ON t.provider=wmt.provider AND t.provider_track_id=wmt.provider_track_id
            WHERE wmt.provider='tidal' AND wmt.video_id=?
            ORDER BY wmt.position
            LIMIT ? OFFSET ?
            """,
            (str(video_id), int(limit), int(offset)),
        ).fetchall()
    return [dict(row) for row in rows]


def tidal_watched_mixes_for_tracks(
    track_ids: list[str], path: Path = DATABASE_PATH
) -> dict[str, list[dict[str, str]]]:
    """Return watched mixes associated with each requested TIDAL track."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    result: dict[str, list[dict[str, str]]] = {track_id: [] for track_id in unique_ids}
    if not unique_ids or not path.exists():
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT wmt.provider_track_id AS track_id, wm.video_id AS id,
                   COALESCE(NULLIF(wm.channel_name, ''), NULLIF(wm.title, ''), wm.video_id) AS name,
                   wm.title
            FROM watched_mix_tracks wmt
            JOIN watched_mixes wm ON wm.video_id=wmt.video_id
            WHERE wmt.provider='tidal'
              AND wmt.provider_track_id IN ({placeholders})
            ORDER BY name COLLATE NOCASE, wm.title COLLATE NOCASE
            """,
            unique_ids,
        ).fetchall()
    for row in rows:
        result[row["track_id"]].append(
            {"id": row["id"], "name": row["name"], "title": row["title"]}
        )
    return result


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


def save_setlist_tidal_url(
    folder_name: str, tidal_url: str, path: Path = DATABASE_PATH
) -> None:
    """Edit only the saved TIDAL URL, preserving an imported setlist identity."""
    name = str(folder_name).strip()
    if not name:
        raise ValueError("Mix folder name cannot be empty")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO setlists(folder_name, tidal_url, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(folder_name) DO UPDATE SET
                tidal_url=excluded.tidal_url, updated_at=excluded.updated_at
            """,
            (name, str(tidal_url or "").strip(), datetime.now(timezone.utc).isoformat()),
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
        "artists": [
            {
                "id": str(getattr(item, "id", "") or ""),
                "name": str(getattr(item, "name", "") or ""),
            }
            for item in artists
            if str(getattr(item, "name", "") or "")
        ],
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
            _store_track_artists(connection, track_id, record)
            connection.execute(
                "INSERT OR IGNORE INTO playlist_tracks(provider, provider_playlist_id, position, provider_track_id, date_added) "
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
            _store_track_artists(connection, track_id, record)
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


def tidal_setlists_for_tracks(
    track_ids: list[str], path: Path = DATABASE_PATH
) -> dict[str, list[dict[str, str]]]:
    """Batch reverse-membership lookup for TIDAL tracks in local setlists."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    result: dict[str, list[dict[str, str]]] = {track_id: [] for track_id in unique_ids}
    if not unique_ids or not path.exists():
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT st.provider_track_id AS track_id,
                            s.folder_name AS id,
                            COALESCE(NULLIF(s.tidal_playlist_name, ''), s.folder_name) AS name
            FROM setlist_tracks st
            JOIN setlists s ON s.folder_name=st.folder_name
            WHERE st.provider='tidal'
              AND st.provider_track_id IN ({placeholders})
            ORDER BY name COLLATE NOCASE
            """,
            unique_ids,
        ).fetchall()
    for row in rows:
        result[row["track_id"]].append({"id": row["id"], "name": row["name"]})
    return result


def tidal_artists_for_tracks(
    track_ids: list[str], path: Path = DATABASE_PATH
) -> dict[str, list[dict[str, str]]]:
    """Return ordered individual artists for several TIDAL tracks."""
    unique_ids = list(dict.fromkeys(str(track_id) for track_id in track_ids if track_id))
    result: dict[str, list[dict[str, str]]] = {track_id: [] for track_id in unique_ids}
    if not unique_ids or not path.exists():
        return result
    initialize(path)
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(path) as connection:
        rows = connection.execute(
            f"""
            SELECT ta.provider_track_id AS track_id, a.artist_key AS id, a.name
            FROM track_artists ta
            JOIN artists a
              ON a.provider=ta.provider AND a.artist_key=ta.artist_key
            WHERE ta.provider='tidal'
              AND ta.provider_track_id IN ({placeholders})
            ORDER BY ta.provider_track_id, ta.position
            """,
            unique_ids,
        ).fetchall()
    for row in rows:
        result[row["track_id"]].append({"id": row["id"], "name": row["name"]})
    return result


def tidal_artist(artist_key: str, path: Path = DATABASE_PATH) -> dict[str, str] | None:
    """Return one normalized artist identity from the local TIDAL index."""
    if not path.exists():
        return None
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT artist_key AS id, provider_artist_id, name
            FROM artists WHERE provider='tidal' AND artist_key=?
            """,
            (str(artist_key),),
        ).fetchone()
        return dict(row) if row else None


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
            SELECT DISTINCT p.provider_playlist_id AS id, p.name, p.collection_type
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
                            p.provider_playlist_id AS id, p.name, p.collection_type
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
        result[row["track_id"]].append(
            {
                "id": row["id"],
                "name": row["name"],
                "collection_type": row["collection_type"],
            }
        )
    return result


def tidal_indexed_playlists(
    path: Path = DATABASE_PATH, collection_type: str | None = None
) -> list[dict[str, str]]:
    """Return every locally indexed TIDAL playlist in display order."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT provider_playlist_id AS id, name, collection_type
            FROM playlists
            WHERE provider='tidal' AND (? IS NULL OR collection_type=?)
            ORDER BY name COLLATE NOCASE
            """,
            (collection_type, collection_type),
        ).fetchall()
        return [dict(row) for row in rows]


def set_tidal_playlist_collection_type(
    playlist_id: str, collection_type: str, path: Path = DATABASE_PATH
) -> None:
    """Classify an already indexed TIDAL playlist for library presentation."""
    kind = str(collection_type or "playlist").strip().lower()
    if kind not in {"playlist", "event", "source"}:
        raise ValueError(f"Unknown playlist collection type: {collection_type!r}")
    if not path.exists():
        return
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """
            UPDATE playlists SET collection_type=?
            WHERE provider='tidal' AND provider_playlist_id=?
            """,
            (kind, str(playlist_id)),
        )


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


def tidal_liked_tracks_page(
    user_id: str,
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read an indexed liked-track page without applying cache-age policy."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
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


def tidal_library_tracks_page(
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read unique TIDAL tracks present in the searchable local library."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            WITH library_memberships AS (
                SELECT provider, provider_track_id, date_added
                FROM liked_tracks
                WHERE provider='tidal'
                UNION ALL
                SELECT provider, provider_track_id, date_added
                FROM playlist_tracks
                WHERE provider='tidal'
                UNION ALL
                SELECT provider, provider_track_id, date_added
                FROM setlist_tracks
                WHERE provider='tidal'
            )
            SELECT t.provider_track_id AS id, t.title, t.artist, t.remix,
                   t.album, t.duration_seconds, t.bpm, t.musical_key,
                   t.key_scale, t.release_year AS year, t.isrc,
                   t.album_art_url, MAX(lm.date_added) AS date_added
            FROM library_memberships lm
            JOIN tracks t
              ON t.provider=lm.provider
             AND t.provider_track_id=lm.provider_track_id
            GROUP BY t.provider, t.provider_track_id
            ORDER BY t.artist COLLATE NOCASE, t.title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def latest_tidal_liked_user_id(path: Path = DATABASE_PATH) -> str | None:
    """Return the most recently refreshed local TIDAL liked-library owner."""
    if not path.exists():
        return None
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT provider_user_id
            FROM liked_track_snapshots
            WHERE provider='tidal'
            ORDER BY cached_at DESC
            LIMIT 1
            """
        ).fetchone()
    return str(row["provider_user_id"]) if row else None


def tidal_liked_track_ids(
    user_id: str, path: Path = DATABASE_PATH
) -> list[str]:
    """Return all cached liked-track IDs in their current order."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT provider_track_id
            FROM liked_tracks
            WHERE provider='tidal' AND provider_user_id=?
            ORDER BY position
            """,
            (str(user_id),),
        ).fetchall()
    return [str(row["provider_track_id"]) for row in rows]


def tidal_track_by_id(
    track_id: str,
    path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    """Return one cached canonical TIDAL track record."""
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT provider_track_id AS id, title, artist, remix, album,
                   album_art_url, duration_seconds, bpm, musical_key,
                   key_scale, release_year AS year, isrc
            FROM tracks
            WHERE provider='tidal' AND provider_track_id=?
            """,
            (str(track_id),),
        ).fetchone()
    return dict(row) if row else None


def merge_tidal_liked_tracks_prefix(
    user_id: str,
    tracks: list[Any],
    boundary_track_id: str | None,
    preserve_unscanned_tail: bool = True,
    path: Path = DATABASE_PATH,
) -> dict[str, int]:
    """Replace the known live prefix while preserving the unscanned cached tail."""
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    records = [(tidal_track_record(track), track) for track in tracks]
    with connect(path) as connection:
        existing_rows = connection.execute(
            """
            SELECT provider_track_id, date_added
            FROM liked_tracks
            WHERE provider='tidal' AND provider_user_id=?
            ORDER BY position
            """,
            (str(user_id),),
        ).fetchall()
        existing = [
            (str(row["provider_track_id"]), row["date_added"])
            for row in existing_rows
        ]
        existing_ids = {track_id for track_id, _date_added in existing}
        boundary_index = next(
            (
                index
                for index, (track_id, _date_added) in enumerate(existing)
                if track_id == str(boundary_track_id or "")
            ),
            0,
        )
        live_ids: list[str] = []
        live_dates: dict[str, str | None] = {}
        seen: set[str] = set()
        for record, track in records:
            track_id = str(record.get("id") or "")
            if not track_id or track_id in seen:
                continue
            seen.add(track_id)
            live_ids.append(track_id)
            added = getattr(track, "user_date_added", None) or getattr(track, "date_added", None)
            live_dates[track_id] = _timestamp(added)
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
            _store_track_artists(connection, track_id, record)

        tail = (
            existing[boundary_index + 1 :] if boundary_track_id else existing
        ) if preserve_unscanned_tail else []
        merged = [(track_id, live_dates[track_id]) for track_id in live_ids]
        merged.extend(
            (track_id, date_added)
            for track_id, date_added in tail
            if track_id not in seen
        )
        connection.execute(
            "DELETE FROM liked_tracks WHERE provider='tidal' AND provider_user_id=?",
            (str(user_id),),
        )
        connection.executemany(
            """
            INSERT INTO liked_tracks(
                provider, provider_user_id, position, provider_track_id, date_added
            ) VALUES('tidal', ?, ?, ?, ?)
            """,
            [
                (str(user_id), position, track_id, date_added)
                for position, (track_id, date_added) in enumerate(merged)
            ],
        )
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', ?, ?)
            ON CONFLICT(provider, provider_user_id) DO UPDATE SET cached_at=excluded.cached_at
            """,
            (str(user_id), now),
        )
    return {
        "fetched": len(live_ids),
        "added": sum(track_id not in existing_ids for track_id in live_ids),
        "cached": len(merged),
    }


def tidal_artist_tracks_page(
    artist_key: str,
    limit: int = 30,
    offset: int = 0,
    path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Read unique locally indexed tracks credited to one artist."""
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT t.provider_track_id AS id, t.title, t.artist,
                   t.remix, t.album, t.duration_seconds, t.bpm,
                   t.musical_key, t.key_scale, t.release_year AS year,
                   t.isrc, t.album_art_url, NULL AS date_added
            FROM track_artists ta
            JOIN tracks t
              ON t.provider=ta.provider AND t.provider_track_id=ta.provider_track_id
            WHERE ta.provider='tidal' AND ta.artist_key=?
              AND (
                  EXISTS (
                      SELECT 1 FROM playlist_tracks pt
                      WHERE pt.provider=ta.provider
                        AND pt.provider_track_id=ta.provider_track_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM liked_tracks lt
                      WHERE lt.provider=ta.provider
                        AND lt.provider_track_id=ta.provider_track_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM setlist_tracks st
                      WHERE st.provider=ta.provider
                        AND st.provider_track_id=ta.provider_track_id
                  )
              )
            ORDER BY t.artist COLLATE NOCASE, t.title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (str(artist_key), int(limit), int(offset)),
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
            ORDER BY dimension, created_at, value COLLATE NOCASE
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
    dimension = dimension.strip().lower()
    value = value.strip()
    if dimension not in DIMENSION_VALUES or value not in DIMENSION_VALUES[dimension]:
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
            else:
                maximum = DIMENSION_MAX_VALUES.get(dimension)
                if maximum:
                    existing_values = connection.execute(
                        """
                        SELECT value FROM track_dimension_values
                        WHERE provider='tidal' AND provider_track_id=? AND dimension=?
                        ORDER BY created_at, value COLLATE NOCASE
                        """,
                        (str(track_id), dimension),
                    ).fetchall()
                    overflow = len(existing_values) - maximum + 1
                    for old_value in existing_values[:max(0, overflow)]:
                        connection.execute(
                            """
                            DELETE FROM track_dimension_values
                            WHERE provider='tidal' AND provider_track_id=?
                              AND dimension=? AND value=?
                            """,
                            (str(track_id), dimension, old_value["value"]),
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
            ORDER BY created_at, value COLLATE NOCASE
            """,
            (str(track_id), dimension),
        ).fetchall()
        return [row["value"] for row in rows]


def replace_tidal_track_dimensions(
    track_id: str,
    dimensions: dict[str, list[str]],
    path: Path = DATABASE_PATH,
) -> dict[str, list[str]]:
    """Replace supplied dimensions atomically while leaving omitted ones untouched."""
    clean: dict[str, list[str]] = {}
    for dimension, values in dimensions.items():
        key = str(dimension).strip().lower()
        if key not in DIMENSION_VALUES:
            continue
        allowed = DIMENSION_VALUES[key]
        accepted = [value for value in dict.fromkeys(values or []) if value in allowed]
        maximum = DIMENSION_MAX_VALUES.get(key)
        if maximum:
            accepted = accepted[:maximum]
        clean[key] = accepted
    initialize(path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        for dimension, values in clean.items():
            connection.execute(
                """
                DELETE FROM track_dimension_values
                WHERE provider='tidal' AND provider_track_id=? AND dimension=?
                """,
                (str(track_id), dimension),
            )
            connection.executemany(
                """
                INSERT INTO track_dimension_values(
                    provider, provider_track_id, dimension, value, created_at
                ) VALUES('tidal', ?, ?, ?, ?)
                """,
                [
                    (str(track_id), dimension, value, now)
                    for value in values
                ],
            )
    return clean


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
            _store_track_artists(connection, track_id, record)
            added = getattr(track, "user_date_added", None) or getattr(track, "date_added", None)
            connection.execute(
                """
                INSERT OR IGNORE INTO liked_tracks(
                    provider, provider_user_id, position, provider_track_id, date_added
                ) VALUES('tidal', ?, ?, ?, ?)
                """,
                (str(user_id), offset + position, track_id, _timestamp(added)),
            )


def add_tidal_liked_track(
    user_id: str,
    track: Any | dict[str, Any],
    path: Path = DATABASE_PATH,
) -> bool:
    """Upsert one provider-liked track at the front of the local snapshot."""
    initialize(path)
    record = track if isinstance(track, dict) else tidal_track_record(track)
    track_id = str(record.get("id") or "")
    if not track_id:
        raise ValueError("A TIDAL track ID is required")
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO tracks(
                provider, provider_track_id, title, artist, remix, album,
                album_art_url, duration_seconds, bpm, musical_key, key_scale,
                release_year, isrc, refreshed_at
            ) VALUES('tidal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, provider_track_id) DO UPDATE SET
                title=excluded.title, artist=excluded.artist,
                remix=excluded.remix, album=excluded.album,
                album_art_url=excluded.album_art_url,
                duration_seconds=excluded.duration_seconds, bpm=excluded.bpm,
                musical_key=excluded.musical_key,
                key_scale=excluded.key_scale,
                release_year=excluded.release_year, isrc=excluded.isrc,
                refreshed_at=excluded.refreshed_at
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
        _store_track_artists(connection, track_id, record)
        exists = connection.execute(
            """
            SELECT 1 FROM liked_tracks
            WHERE provider='tidal' AND provider_user_id=? AND provider_track_id=?
            """,
            (str(user_id), track_id),
        ).fetchone()
        added = exists is None
        if added:
            # Two-phase renumbering avoids primary-key collisions while opening
            # position zero for the newly liked track.
            connection.execute(
                """
                UPDATE liked_tracks SET position=-(position + 1)
                WHERE provider='tidal' AND provider_user_id=?
                """,
                (str(user_id),),
            )
            connection.execute(
                """
                UPDATE liked_tracks SET position=-position
                WHERE provider='tidal' AND provider_user_id=?
                """,
                (str(user_id),),
            )
            connection.execute(
                """
                INSERT INTO liked_tracks(
                    provider, provider_user_id, position,
                    provider_track_id, date_added
                ) VALUES('tidal', ?, 0, ?, ?)
                """,
                (str(user_id), track_id, now),
            )
        connection.execute(
            """
            INSERT INTO liked_track_snapshots(provider, provider_user_id, cached_at)
            VALUES('tidal', ?, ?)
            ON CONFLICT(provider, provider_user_id)
            DO UPDATE SET cached_at=excluded.cached_at
            """,
            (str(user_id), now),
        )
    return added
