"""Provider clients and sync engine shared by FastAPI and startup jobs.

Run the React/FastAPI UI with ``python react_app.py`` or ``python main.py``.
The same ``run_all_syncs`` function is used by ``startup_sync.py``, so scheduled
and manual syncs behave identically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
import webbrowser
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Load this local app's simple KEY=VALUE file without another dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

from music_library.database import (  # noqa: E402 - local .env configures its path
    cached_tidal_playlist,
    merge_tidal_liked_tracks_prefix,
    set_tidal_playlist_collection_type,
    store_tidal_liked_tracks,
    store_tidal_playlist,
    tidal_liked_track_ids,
    tidal_track_record,
)
from music_library import config_store  # noqa: E402
from music_library.credentials import (  # noqa: E402
    SpotifyDatabaseCacheHandler,
    credentials_available,
    load_or_import_file_credentials,
    read_json_file,
    save_credentials,
    storage_enabled as credential_storage_enabled,
)

CONFIG_PATH = Path(os.getenv("MUSICSYNC_CONFIG", ROOT / "music_sync.json"))
SPOTIFY_CACHE = ROOT / ".spotify_cache"
TIDAL_CACHE = ROOT / ".tidal_session.json"
LOG_PATH = ROOT / "music_sync.log"
CONNECTION_STATE = ROOT / ".connection_state.json"
LOGGER = logging.getLogger("musicsync")
CURRENT_MAPPING: ContextVar[str] = ContextVar("current_mapping", default="-")


def configure_logging() -> None:
    """Log application activity to disk and the terminal without HTTP secrets."""
    from logging.handlers import RotatingFileHandler

    level_name = os.getenv("MUSICSYNC_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    LOGGER.setLevel(level)
    if not LOGGER.handlers:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Vercel's deployed application bundle is read-only. Its log collector
        # captures stdout/stderr, while local runs retain the rotating file.
        if not os.getenv("VERCEL"):
            file_handler = RotatingFileHandler(
                LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            LOGGER.addHandler(file_handler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        LOGGER.addHandler(console_handler)
    LOGGER.propagate = False


def _call(provider: str, action: str, function: Callable[[], Any], **details: Any) -> Any:
    """Time one remote operation and log only caller-supplied, non-secret metadata."""
    safe_details = " ".join(f"{key}={value!r}" for key, value in details.items())
    safe_details = f"mapping={CURRENT_MAPPING.get()!r} {safe_details}".rstrip()
    LOGGER.info("call.start provider=%s action=%s %s", provider, action, safe_details)
    started = time.perf_counter()
    try:
        result = function()
    except Exception:
        LOGGER.exception(
            "call.failed provider=%s action=%s duration_ms=%d %s",
            provider,
            action,
            round((time.perf_counter() - started) * 1000),
            safe_details,
        )
        raise
    LOGGER.info(
        "call.ok provider=%s action=%s duration_ms=%d %s",
        provider,
        action,
        round((time.perf_counter() - started) * 1000),
        safe_details,
    )
    return result


@dataclass
class SyncResult:
    source: str
    target: str
    found: int = 0
    added: int = 0
    already_present: int = 0
    unmatched: int = 0
    error: str = ""
    label: str = ""
    skipped: bool = False
    cached: int = 0


def default_config() -> dict[str, Any]:
    return {
        "settings": {
            "country_code": "NO",
            "search_limit": 8,
            "spotify_search_delay_seconds": 0.75,
            "dark_mode": True,
            "tags_collapsed_by_default": True,
            "default_sort_direction": "asc",
            "tidal_search_delay_seconds": 0.35,
            "maintain_liked_tracks_cache": True,
            "liked_tracks_cache_page_size": 50,
            "liked_tracks_cache_max_pages": 10,
            "liked_tracks_cache_delay_seconds": 0.25,
            "lastfm_username": "",
            "lastfm_import_delay_seconds": 0.5,
        },
        "quick_views": [
            {
                "id": "default",
                "name": "Default",
                "fields": [
                    "title", "artist", "remix", "album", "length", "bpm",
                    "key", "year", "date_added", "playlists", "events",
                    "play_count", "last_played", "sources", "mixes", "djmi",
                ],
                "default": True,
            }
        ],
        "mix_quick_views": [
            {
                "id": "mix-default",
                "name": "Default",
                "fields": [
                    "cover", "folder_name", "youtube_title",
                    "tidal_playlist_name", "track_count",
                    "youtube_upload_date", "youtube_duration_seconds",
                    "youtube_views", "youtube_views_per_day",
                    "youtube_thumbnail_ctr",
                    "youtube_average_view_percentage", "youtube_likes",
                    "youtube_comments", "youtube_performance",
                    "youtube_verdict", "youtube_url",
                    "youtube_analytics_url",
                ],
                "default": True,
            }
        ],
        "playlists": [
            {
                "enabled": True,
                "name": "My playlist sync",
                "direction": "spotify_to_tidal",
                "collection_type": "playlist",
                "spotify": "https://open.spotify.com/playlist/PASTE_ID_HERE",
                "tidal": "",
                "tidal_name": "",
            }
        ],
    }


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("playlists"), list):
        raise ValueError("The config must contain a 'playlists' list")
    data.setdefault("settings", {})
    data.setdefault("quick_views", default_config()["quick_views"])
    data.setdefault("mix_quick_views", default_config()["mix_quick_views"])
    return data


def _uses_sqlite_config(path: Path) -> bool:
    return path.resolve() == CONFIG_PATH.resolve()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not _uses_sqlite_config(path):
        return _load_json_config(path)
    stored = config_store.load()
    if stored is not None:
        return stored
    # First-run/import bridge. Once imported, SQLite remains authoritative even
    # if the JSON file is later edited or removed.
    data = _load_json_config(path)
    config_store.replace(data)
    return config_store.load() or data


def load_settings_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load the settings-facing subset without loading sync mapping state."""
    if not _uses_sqlite_config(path):
        data = _load_json_config(path)
        return {
            "settings": data.get("settings", {}),
            "quick_views": data.get("quick_views", []),
            "mix_quick_views": data.get("mix_quick_views", []),
        }
    stored = config_store.load_settings_bundle()
    if stored is not None:
        return stored
    # Preserve the same first-run JSON import behavior as load_config().
    load_config(path)
    return config_store.load_settings_bundle() or {
        "settings": {}, "quick_views": [], "mix_quick_views": [],
    }


def load_runtime_settings(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load settings without mappings or Quick Views."""
    if not _uses_sqlite_config(path):
        return _load_json_config(path).get("settings", {})
    stored = config_store.load_runtime_settings()
    if stored is not None:
        return stored
    # Preserve the first-run JSON import bridge used by the other config reads.
    load_config(path)
    return config_store.load_runtime_settings() or {}


def save_config(data: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    if _uses_sqlite_config(path):
        config_store.replace(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _connection_state() -> dict[str, str]:
    try:
        return json.loads(CONNECTION_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _remember_connection(provider: str, label: str) -> None:
    state = _connection_state()
    state[provider] = label
    CONNECTION_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _connection_badge(provider: str, cache: Path) -> tuple[str, str]:
    label = _connection_state().get(provider)
    connected = credentials_available(provider, cache)
    if connected and label:
        return f"● {provider.title()} connected: {label}", "connection connected"
    if connected:
        return f"● {provider.title()} credentials saved", "connection connected"
    return f"○ {provider.title()} not connected", "connection disconnected"


def _id(value: str) -> str:
    """Extract a Spotify/TIDAL ID from a raw ID, URI, or web URL."""
    value = (value or "").strip().split("?")[0].rstrip("/")
    if not value:
        return ""
    return re.split(r"[/:]", value)[-1]


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = re.sub(r"\s*[\[(].*?(remaster|version|edit|live).*?[\])]", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _identity_keys(track: dict[str, Any]) -> set[str]:
    """Cross-service identities, strongest first but all usable for a local diff."""
    keys: set[str] = set()
    isrc = (track.get("isrc") or "").strip().upper()
    if isrc:
        keys.add(f"isrc:{isrc}")
    title = _normalized(track.get("title", ""))
    artist = _normalized(track.get("artist", ""))
    if title and artist:
        keys.add(f"meta:{title}|{artist}")
    return keys


def _playlist_diff(
    source_tracks: list[dict[str, Any]], target_identities: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """Return unique source tracks absent from target and the skipped count."""
    missing: list[dict[str, Any]] = []
    seen = set(target_identities)
    already_present = 0
    for track in source_tracks:
        keys = _identity_keys(track)
        if keys and keys & seen:
            already_present += 1
            continue
        missing.append(track)
        seen.update(keys)
    return missing, already_present


def _unmatched_key(track: dict[str, Any]) -> str:
    keys = _identity_keys(track)
    isrc_keys = sorted(key for key in keys if key.startswith("isrc:"))
    if isrc_keys:
        return isrc_keys[0]
    metadata_keys = sorted(key for key in keys if key.startswith("meta:"))
    if metadata_keys:
        return metadata_keys[0]
    return f'unknown:{_normalized(track.get("title", ""))}|{_normalized(track.get("artist", ""))}'


def _unmatched_records(entry: dict[str, Any], direction: str) -> list[dict[str, str]]:
    cache = entry.setdefault("unmatched", {})
    if not isinstance(cache, dict):
        cache = {}
        entry["unmatched"] = cache
    records = cache.setdefault(direction, [])
    if not isinstance(records, list):
        records = []
        cache[direction] = records
    return records


def _remember_unmatched(records: list[dict[str, str]], track: dict[str, Any]) -> None:
    key = _unmatched_key(track)
    if any(record.get("key") == key for record in records):
        return
    records.append(
        {
            "key": key,
            "title": track.get("title", ""),
            "artist": track.get("artist", ""),
            "isrc": track.get("isrc", ""),
        }
    )


def _tidal_track_data(track: Any) -> dict[str, Any]:
    return tidal_track_record(track)


def _spotify_track_data(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": track.get("name", ""),
        "artist": ", ".join(a.get("name", "") for a in track.get("artists", [])),
        "album": (track.get("album") or {}).get("name", ""),
        "isrc": (track.get("external_ids") or {}).get("isrc", ""),
    }


def spotify_client():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    client_id = os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8080/callback")
    if not client_id or not client_secret:
        LOGGER.error("spotify.auth configuration missing client_id=%s client_secret=%s", bool(client_id), bool(client_secret))
        raise RuntimeError("Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET")
    LOGGER.info(
        "spotify.auth initialize client_id_suffix=%s redirect_uri=%s cache_exists=%s",
        client_id[-6:],
        redirect,
        SPOTIFY_CACHE.exists(),
    )
    auth_options: dict[str, Any] = {}
    if credential_storage_enabled():
        auth_options["cache_handler"] = SpotifyDatabaseCacheHandler(SPOTIFY_CACHE)
    else:
        auth_options["cache_path"] = str(SPOTIFY_CACHE)
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect,
        scope="playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public",
        open_browser=True,
        **auth_options,
    )
    return spotipy.Spotify(auth_manager=auth)


def spotify_auth_manager():
    """Build the OAuth manager without starting Spotipy's temporary web server."""
    try:
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    client_id = os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8080/callback")
    if not client_id or not client_secret:
        raise RuntimeError("Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET")
    auth_options: dict[str, Any] = {}
    if credential_storage_enabled():
        auth_options["cache_handler"] = SpotifyDatabaseCacheHandler(SPOTIFY_CACHE)
    else:
        auth_options["cache_path"] = str(SPOTIFY_CACHE)
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect,
        scope="playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public",
        open_browser=False,
        **auth_options,
    )


def _save_tidal_session(session: Any) -> None:
    expiry = session.expiry_time
    payload = {
        "token_type": session.token_type,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time": expiry.isoformat() if expiry else None,
    }
    if credential_storage_enabled():
        user = getattr(session, "user", None)
        save_credentials(
            "tidal",
            payload,
            provider_account_id=str(getattr(user, "id", "") or ""),
            expires_at=payload["expiry_time"],
            event_type="credentials_refreshed",
        )
    else:
        TIDAL_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOGGER.info("tidal.auth session_saved expiry=%s", expiry.isoformat() if expiry else "unknown")


def tidal_client(interactive: bool = False, message: Callable[[str], None] = print):
    try:
        import tidalapi
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    session = tidalapi.Session()
    database_credentials = credential_storage_enabled()
    cache_exists = TIDAL_CACHE.exists()
    LOGGER.info(
        "tidal.auth initialize storage=%s credentials_available=%s interactive=%s",
        "database" if database_credentials else "file",
        credentials_available("tidal", TIDAL_CACHE),
        interactive,
    )
    try:
        saved = (
            load_or_import_file_credentials("tidal", TIDAL_CACHE)
            if database_credentials
            else (read_json_file(TIDAL_CACHE) if cache_exists else None)
        )
        if saved:
            expiry = datetime.fromisoformat(saved["expiry_time"]) if saved.get("expiry_time") else None
            if session.load_oauth_session(
                saved["token_type"], saved["access_token"], saved.get("refresh_token"), expiry
            ):
                _save_tidal_session(session)  # Persist a possibly refreshed token.
                LOGGER.info("tidal.auth cached_session_loaded user_id=%s", session.user.id)
                return session
    except (KeyError, ValueError, json.JSONDecodeError):
        LOGGER.exception("tidal.auth cached_session_invalid")
    if not interactive:
        raise RuntimeError("TIDAL is not connected. Use the Connect TIDAL button first.")
    login, login_future = session.login_oauth()
    url = login.verification_uri_complete
    LOGGER.info("tidal.auth device_login_started expires_in=%s", getattr(login, "expires_in", "unknown"))
    message(f"Complete TIDAL login at {url}")
    if not webbrowser.open(url):
        LOGGER.warning("tidal.auth browser_open_returned_false url=%s", url)
    login_future.result()
    if not session.check_login():
        raise RuntimeError("TIDAL login did not complete")
    _save_tidal_session(session)
    LOGGER.info("tidal.auth interactive_login_complete user_id=%s", session.user.id)
    return session


def spotify_tracks(
    client: Any, playlist_value: str, metadata: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    playlist_id = _id(playlist_value)
    if not playlist_id:
        raise ValueError("Spotify playlist is empty")
    LOGGER.info("spotify.playlist begin playlist_id=%s", playlist_id)
    if metadata is None:
        metadata = _call(
            "spotify",
            "playlist_metadata",
            lambda: client.playlist(playlist_id, fields="id,name,owner,snapshot_id,items(total)"),
            playlist_id=playlist_id,
        )
    owner = metadata.get("owner") or {}
    declared_total = (metadata.get("items") or {}).get("total")
    LOGGER.info(
        "spotify.playlist metadata playlist_id=%s name=%r owner_id=%s owner_name=%r declared_total=%s",
        playlist_id,
        metadata.get("name"),
        owner.get("id"),
        owner.get("display_name"),
        declared_total,
    )
    page = _call(
        "spotify",
        "playlist_items",
        lambda: client.playlist_items(playlist_id, additional_types=("track",), limit=100),
        playlist_id=playlist_id,
        page=1,
        limit=100,
    )
    tracks: list[dict[str, Any]] = []
    page_number = 1
    while page:
        received = len(page.get("items", []))
        LOGGER.info("spotify.playlist page playlist_id=%s page=%d items=%d", playlist_id, page_number, received)
        for item in page.get("items", []):
            track = item.get("track") or item.get("item") or {}
            if not track or track.get("is_local"):
                continue
            tracks.append(_spotify_track_data(track))
        if page.get("next"):
            page_number += 1
            page = _call(
                "spotify",
                "playlist_items_next",
                lambda: client.next(page),
                playlist_id=playlist_id,
                page=page_number,
            )
        else:
            page = None
    LOGGER.info("spotify.playlist complete playlist_id=%s usable_tracks=%d", playlist_id, len(tracks))
    if not tracks:
        current_user = client.current_user().get("id")
        owner_id = owner.get("id")
        ownership = (
            f"Spotify says its owner is {owner_id!r}, while you authenticated as {current_user!r}. "
            if owner_id and owner_id != current_user
            else "Spotify identifies you as the owner, but still returned no playlist items. "
        )
        raise RuntimeError(
            f"Spotify returned zero tracks for {metadata.get('name') or playlist_id!r}. "
            + ownership
            + "Development Mode only exposes the contents of playlists owned by the authenticated user. "
            + "Make a new playlist on your account, copy the Shazam tracks into it, and sync that playlist URL."
        )
    return metadata, tracks


def _tidal_search(session: Any, track: dict[str, Any], limit: int) -> Any | None:
    import tidalapi

    queries = []
    if track["isrc"]:
        queries.append(track["isrc"])
    queries.append(f'{track["title"]} {track["artist"]}')
    wanted_title, wanted_artist = _normalized(track["title"]), _normalized(track["artist"])
    best, best_score = None, -1
    for query in queries:
        # At INFO level we log the source track, not every query/result. Set
        # MUSICSYNC_LOG_LEVEL=DEBUG when individual search queries are useful.
        LOGGER.debug("tidal.search request query=%r limit=%d", query, limit)
        response = _call(
            "tidal",
            "search",
            lambda: session.search(query, models=[tidalapi.Track], limit=limit),
            query=query,
            limit=limit,
        )
        results = response.get("tracks", [])
        LOGGER.debug("tidal.search response query=%r candidates=%d", query, len(results))
        for candidate in results:
            candidate_isrc = getattr(candidate, "isrc", "") or ""
            if track["isrc"] and candidate_isrc.upper() == track["isrc"].upper():
                LOGGER.info(
                    "match.isrc source=%r artist=%r tidal_id=%s",
                    track["title"], track["artist"], candidate.id,
                )
                return candidate
            title = _normalized(getattr(candidate, "name", ""))
            artist = _normalized(getattr(getattr(candidate, "artist", None), "name", ""))
            score = (3 if title == wanted_title else 0) + (2 if artist and artist in wanted_artist else 0)
            if score > best_score:
                best, best_score = candidate, score
        if best_score >= 5:
            break
    if best is not None and best_score >= 3:
        LOGGER.info(
            "match.metadata source=%r artist=%r tidal_id=%s score=%d",
            track["title"], track["artist"], best.id, best_score,
        )
        return best
    LOGGER.warning("match.unmatched source=%r artist=%r isrc=%s", track["title"], track["artist"], track["isrc"] or "none")
    return None


def _target_playlist(session: Any, playlist_id: str, name: str):
    if playlist_id:
        target_id = _id(playlist_id)
        playlist = _call("tidal", "get_playlist", lambda: session.playlist(target_id), playlist_id=target_id)
        if hasattr(playlist, "add"):
            return playlist
        # Fetching through user playlists returns the writable subclass on versions
        # where session.playlist only returns a read-only Playlist.
        user_playlists = _call("tidal", "user_playlists", session.user.playlists)
        for candidate in user_playlists:
            if str(candidate.id) == str(playlist.id):
                return candidate
        return playlist
    if not name.strip():
        raise ValueError("Set either a TIDAL playlist ID or a name for a new playlist")
    return _call(
        "tidal",
        "create_playlist",
        lambda: session.user.create_playlist(name.strip(), "Synced from Spotify by Music Sync"),
        playlist_name=name.strip(),
    )


def _tidal_playlist_track_records(playlist: Any, action: str) -> list[dict[str, Any]]:
    playlist_id = str(playlist.id)
    last_updated = getattr(playlist, "last_updated", None)
    cached = cached_tidal_playlist(playlist_id, last_updated)
    if cached is not None:
        LOGGER.info(
            "tidal.playlist cache_hit playlist_id=%s last_updated=%s tracks=%d",
            playlist_id,
            last_updated,
            len(cached),
        )
        return cached
    LOGGER.info(
        "tidal.playlist cache_miss playlist_id=%s last_updated=%s",
        playlist_id,
        last_updated,
    )
    items = _call("tidal", action, playlist.tracks, playlist_id=playlist_id)
    records = [tidal_track_record(track) for track in items]
    store_tidal_playlist(playlist, records)
    LOGGER.info("tidal.playlist indexed playlist_id=%s tracks=%d", playlist_id, len(records))
    return records


def tidal_tracks(session: Any, playlist_value: str) -> tuple[Any, list[dict[str, Any]]]:
    playlist_id = _id(playlist_value)
    if not playlist_id:
        raise ValueError("TIDAL source playlist is empty")
    playlist = _call("tidal", "get_source_playlist", lambda: session.playlist(playlist_id), playlist_id=playlist_id)
    tracks = _tidal_playlist_track_records(playlist, "source_playlist_tracks")
    if not tracks:
        raise RuntimeError(f"TIDAL returned zero tracks for {getattr(playlist, 'name', playlist_id)!r}")
    LOGGER.info("tidal.playlist source_complete playlist_id=%s tracks=%d", playlist_id, len(tracks))
    return playlist, tracks


def refresh_tidal_playlist_cache(
    playlist_value: str, force: bool = False
) -> dict[str, Any]:
    """Check one indexed playlist and replace SQLite membership when needed."""
    playlist_id = _id(playlist_value)
    if not playlist_id:
        raise ValueError("TIDAL playlist ID is empty")
    session = tidal_client(interactive=False)
    playlist = _call(
        "tidal",
        "get_indexed_playlist",
        lambda: session.playlist(playlist_id),
        playlist_id=playlist_id,
    )
    last_updated = getattr(playlist, "last_updated", None)
    if not force:
        cached = cached_tidal_playlist(playlist_id, last_updated)
        if cached is not None:
            LOGGER.info(
                "tidal.playlist ui_cache_current playlist_id=%s last_updated=%s tracks=%d",
                playlist_id,
                last_updated,
                len(cached),
            )
            return {
                "changed": False,
                "tracks": len(cached),
                "last_updated": str(last_updated or ""),
            }
    items = list(
        _call(
            "tidal",
            "refresh_indexed_playlist_tracks",
            playlist.tracks,
            playlist_id=playlist_id,
            force=force,
        )
        or []
    )
    records = [tidal_track_record(track) for track in items]
    store_tidal_playlist(playlist, records)
    LOGGER.info(
        "tidal.playlist ui_cache_refreshed playlist_id=%s tracks=%d force=%s",
        playlist_id,
        len(records),
        force,
    )
    return {
        "changed": True,
        "tracks": len(records),
        "last_updated": str(last_updated or ""),
    }


def _spotify_search(
    client: Any, track: dict[str, Any], limit: int, delay_seconds: float = 0.75
) -> dict[str, Any] | None:
    queries = []
    if track["isrc"]:
        queries.append(f'isrc:{track["isrc"]}')
    queries.append(f'track:{track["title"]} artist:{track["artist"]}')
    wanted_title, wanted_artist = _normalized(track["title"]), _normalized(track["artist"])
    best, best_score = None, -1
    for query in queries:
        if delay_seconds > 0:
            LOGGER.info("spotify.search throttle sleep_seconds=%.2f", delay_seconds)
            time.sleep(delay_seconds)
        response = _call("spotify", "search", lambda query=query: client.search(q=query, type="track", limit=limit), query=query, limit=limit)
        for candidate in (response.get("tracks") or {}).get("items", []):
            candidate_isrc = (candidate.get("external_ids") or {}).get("isrc", "")
            if track["isrc"] and candidate_isrc.upper() == track["isrc"].upper():
                LOGGER.info("match.isrc provider=spotify source=%r spotify_id=%s", track["title"], candidate.get("id"))
                return candidate
            title = _normalized(candidate.get("name", ""))
            artists = _normalized(", ".join(a.get("name", "") for a in candidate.get("artists", [])))
            score = (3 if title == wanted_title else 0) + (2 if artists and artists in wanted_artist else 0)
            if score > best_score:
                best, best_score = candidate, score
        if best_score >= 5:
            break
    if best is not None and best_score >= 3:
        LOGGER.info("match.metadata provider=spotify source=%r spotify_id=%s score=%d", track["title"], best.get("id"), best_score)
        return best
    LOGGER.warning("match.unmatched provider=spotify source=%r artist=%r", track["title"], track["artist"])
    return None


def _spotify_target(client: Any, playlist_value: str, name: str) -> dict[str, Any]:
    playlist_id = _id(playlist_value)
    if playlist_id:
        return _call("spotify", "get_target_playlist", lambda: client.playlist(playlist_id, fields="id,name,owner"), playlist_id=playlist_id)
    if not name.strip():
        raise ValueError("Set either a Spotify target playlist ID or a name for a new playlist")
    return _call(
        "spotify",
        "create_playlist",
        lambda: client._post(
            "me/playlists",
            payload={"name": name.strip(), "public": False, "description": "Synced from TIDAL by Music Sync"},
        ),
        playlist_name=name.strip(),
    )


def _spotify_target_inventory(client: Any, playlist_id: str) -> tuple[set[str], set[str]]:
    page = _call("spotify", "target_playlist_items", lambda: client.playlist_items(playlist_id, limit=100), playlist_id=playlist_id, page=1)
    uris: set[str] = set()
    identities: set[str] = set()
    while page:
        for row in page.get("items", []):
            item = row.get("item") or row.get("track") or {}
            if item.get("uri"):
                uris.add(item["uri"])
            identities.update(_identity_keys(_spotify_track_data(item)))
        page = _call("spotify", "target_playlist_items_next", lambda: client.next(page), playlist_id=playlist_id) if page.get("next") else None
    return uris, identities


def sync_spotify_to_tidal(spotify: Any, tidal: Any, entry: dict[str, Any], settings: dict[str, Any]) -> SyncResult:
    result = SyncResult(entry.get("spotify", ""), entry.get("tidal", "") or entry.get("tidal_name", ""))
    source_id = _id(result.source)
    if not source_id:
        raise ValueError("Spotify source playlist is empty")
    source_playlist = _call(
        "spotify",
        "source_change_state",
        lambda: spotify.playlist(source_id, fields="id,name,owner,snapshot_id,items(total)"),
        playlist_id=source_id,
    )
    source_version = source_playlist.get("snapshot_id")
    if entry.get("last_sync") and source_version and entry.get("source_version") == source_version:
        # Even a skipped mapping participates in the local TIDAL membership
        # index, allowing a fresh database to populate without forcing a sync.
        tidal_id = _id(entry.get("tidal", ""))
        if tidal_id:
            tidal_playlist = _call(
                "tidal", "get_target_playlist", lambda: tidal.playlist(tidal_id),
                playlist_id=tidal_id,
            )
            _tidal_playlist_track_records(tidal_playlist, "playlist_tracks")
        result.target = entry.get("tidal", "") or entry.get("tidal_name", "")
        result.skipped = True
        LOGGER.info(
            "sync.mapping unchanged provider=spotify snapshot_id=%s last_sync=%s",
            source_version, entry.get("last_sync"),
        )
        return result
    source_playlist, source_tracks = spotify_tracks(spotify, result.source, source_playlist)
    target_name = entry.get("tidal_name", "") or source_playlist.get("name", "")
    target = _target_playlist(tidal, entry.get("tidal", ""), target_name)
    entry["tidal"] = str(target.id)
    result.target = f"{target.name} ({target.id})"
    target_tracks = _tidal_playlist_track_records(target, "playlist_tracks")
    existing = {str(track["id"]) for track in target_tracks}
    target_identities: set[str] = set()
    for target_track in target_tracks:
        target_identities.update(_identity_keys(target_track))
    LOGGER.info(
        "sync.playlist inventory source_tracks=%d target_tracks=%d target_id=%s",
        len(source_tracks), len(existing), target.id,
    )
    to_add: list[int] = []
    to_add_records: list[dict[str, Any]] = []
    limit = int(settings.get("search_limit", 8))
    missing, result.already_present = _playlist_diff(source_tracks, target_identities)
    unmatched_records = _unmatched_records(entry, "spotify_to_tidal")
    known_unmatched = {record.get("key") for record in unmatched_records}
    retryable = [track for track in missing if _unmatched_key(track) not in known_unmatched]
    skipped_unmatched = len(missing) - len(retryable)
    result.unmatched += skipped_unmatched
    LOGGER.info(
        "sync.diff direction=spotify_to_tidal source=%d already_present=%d known_unmatched=%d search_required=%d",
        len(source_tracks), result.already_present, skipped_unmatched, len(retryable),
    )
    for source_track in retryable:
        match = _tidal_search(tidal, source_track, limit)
        if match is None:
            result.unmatched += 1
            _remember_unmatched(unmatched_records, source_track)
        elif str(match.id) in existing:
            result.already_present += 1
            target_identities.update(_identity_keys(source_track))
        else:
            to_add.append(int(match.id))
            to_add_records.append(tidal_track_record(match))
            existing.add(str(match.id))
            target_identities.update(_identity_keys(source_track))
            target_identities.update(_identity_keys(_tidal_track_data(match)))
            result.found += 1
    for start in range(0, len(to_add), 100):
        batch = to_add[start : start + 100]
        _call(
            "tidal", "playlist_add", lambda batch=batch: target.add(batch),
            playlist_id=target.id, track_count=len(batch),
        )
        result.added += len(batch)
    if to_add_records:
        # Membership is immediately correct for reverse lookups. A null source
        # version deliberately forces provider revalidation on the next run.
        store_tidal_playlist(
            target,
            target_tracks + to_add_records,
            source_last_updated=None,
        )
    LOGGER.info(
        "sync.playlist complete target_id=%s added=%d existing=%d unmatched=%d",
        target.id, result.added, result.already_present, result.unmatched,
    )
    entry["source_version"] = source_version
    return result


def sync_tidal_to_spotify(spotify: Any, tidal: Any, entry: dict[str, Any], settings: dict[str, Any]) -> SyncResult:
    source_playlist, source_tracks = tidal_tracks(tidal, entry.get("tidal", ""))
    source_version = hashlib.sha256(
        "\n".join(_unmatched_key(track) for track in source_tracks).encode("utf-8")
    ).hexdigest()
    if entry.get("last_sync") and entry.get("source_version") == source_version:
        result = SyncResult(
            f"{getattr(source_playlist, 'name', source_playlist.id)} ({source_playlist.id})",
            entry.get("spotify", "") or entry.get("tidal_name", ""),
            skipped=True,
        )
        LOGGER.info(
            "sync.mapping unchanged provider=tidal source_fingerprint=%s last_sync=%s",
            source_version[:12], entry.get("last_sync"),
        )
        return result
    target_name = entry.get("tidal_name", "") or getattr(source_playlist, "name", "")
    target = _spotify_target(spotify, entry.get("spotify", ""), target_name)
    entry["spotify"] = str(target["id"])
    result = SyncResult(
        f"{getattr(source_playlist, 'name', source_playlist.id)} ({source_playlist.id})",
        f"{target.get('name', target['id'])} ({target['id']})",
    )
    existing, target_identities = _spotify_target_inventory(spotify, target["id"])
    to_add: list[str] = []
    limit = min(int(settings.get("search_limit", 8)), 10)
    search_delay = max(float(settings.get("spotify_search_delay_seconds", 0.75)), 0.0)
    missing, result.already_present = _playlist_diff(source_tracks, target_identities)
    unmatched_records = _unmatched_records(entry, "tidal_to_spotify")
    known_unmatched = {record.get("key") for record in unmatched_records}
    retryable = [track for track in missing if _unmatched_key(track) not in known_unmatched]
    skipped_unmatched = len(missing) - len(retryable)
    result.unmatched += skipped_unmatched
    LOGGER.info(
        "sync.diff direction=tidal_to_spotify source=%d already_present=%d known_unmatched=%d search_required=%d",
        len(source_tracks), result.already_present, skipped_unmatched, len(retryable),
    )
    for source_track in retryable:
        match = _spotify_search(spotify, source_track, limit, search_delay)
        if match is None:
            result.unmatched += 1
            _remember_unmatched(unmatched_records, source_track)
        elif match["uri"] in existing:
            result.already_present += 1
            target_identities.update(_identity_keys(source_track))
        else:
            to_add.append(match["uri"])
            existing.add(match["uri"])
            target_identities.update(_identity_keys(source_track))
            target_identities.update(_identity_keys(_spotify_track_data(match)))
            result.found += 1
    for start in range(0, len(to_add), 100):
        batch = to_add[start : start + 100]
        _call(
            "spotify",
            "playlist_add",
            lambda batch=batch: spotify._post(f"playlists/{target['id']}/items", payload={"uris": batch}),
            playlist_id=target["id"],
            track_count=len(batch),
        )
        result.added += len(batch)
    LOGGER.info("sync.playlist complete direction=tidal_to_spotify target_id=%s added=%d existing=%d unmatched=%d", target["id"], result.added, result.already_present, result.unmatched)
    entry["source_version"] = source_version
    return result


def cache_tidal_playlist(tidal: Any, entry: dict[str, Any]) -> SyncResult:
    """Index one TIDAL playlist locally without syncing to another provider."""
    source_playlist, source_tracks = tidal_tracks(tidal, entry.get("tidal", ""))
    last_updated = getattr(source_playlist, "last_updated", None)
    source_version = str(last_updated) if last_updated else hashlib.sha256(
        "\n".join(str(track.get("id", "")) for track in source_tracks).encode("utf-8")
    ).hexdigest()
    result = SyncResult(
        source=f"{getattr(source_playlist, 'name', source_playlist.id)} ({source_playlist.id})",
        target="SQLite cache",
        cached=len(source_tracks),
    )
    if entry.get("last_sync") and entry.get("source_version") == source_version:
        result.skipped = True
        LOGGER.info(
            "sync.mapping unchanged provider=tidal_cache last_updated=%s tracks=%d",
            last_updated,
            len(source_tracks),
        )
        return result
    entry["source_version"] = source_version
    LOGGER.info(
        "sync.playlist cached_only playlist_id=%s tracks=%d last_updated=%s",
        source_playlist.id,
        len(source_tracks),
        last_updated,
    )
    return result


def sync_one(spotify: Any, tidal: Any, entry: dict[str, Any], settings: dict[str, Any]) -> SyncResult:
    direction = entry.get("direction", "spotify_to_tidal")
    LOGGER.info("sync.playlist dispatch name=%r direction=%s", entry.get("name", ""), direction)
    if direction == "spotify_to_tidal":
        result = sync_spotify_to_tidal(spotify, tidal, entry, settings)
    elif direction == "tidal_to_spotify":
        result = sync_tidal_to_spotify(spotify, tidal, entry, settings)
    elif direction == "tidal_cache":
        result = cache_tidal_playlist(tidal, entry)
    else:
        raise ValueError(f"Unknown sync direction: {direction!r}")
    tidal_playlist_id = _id(entry.get("tidal", ""))
    if tidal_playlist_id:
        set_tidal_playlist_collection_type(
            tidal_playlist_id, entry.get("collection_type", "playlist")
        )
    result.label = entry.get("name", "")
    if not result.skipped:
        entry["last_sync"] = datetime.now(timezone.utc).isoformat()
        LOGGER.info("sync.mapping timestamp name=%r last_sync=%s", result.label, entry["last_sync"])
    return result


def maintain_tidal_liked_tracks(
    tidal: Any,
    settings: dict[str, Any],
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Refresh the live liked-library prefix and preserve the cached older tail."""
    from tidalapi.user import ItemOrder, OrderDirection

    progress = progress or (lambda _message: None)
    user_id = str(tidal.user.id)
    page_size = max(1, min(50, int(settings.get("liked_tracks_cache_page_size", 50))))
    max_pages = max(1, int(settings.get("liked_tracks_cache_max_pages", 10)))
    delay_seconds = max(
        0.0, float(settings.get("liked_tracks_cache_delay_seconds", 0.25))
    )
    existing_ids = tidal_liked_track_ids(user_id)
    existing_set = set(existing_ids)
    provider_total = int(
        _call(
            "tidal",
            "favorite_tracks_count",
            tidal.user.favorites.get_tracks_count,
        )
        or 0
    )
    if provider_total == 0:
        store_tidal_liked_tracks(user_id, [], offset=0)
        return {"fetched": 0, "added": 0, "cached": 0, "provider_total": 0}

    fetched: list[Any] = []
    boundary_track_id: str | None = None
    pages_to_scan = 1 if not existing_ids else max_pages
    for page_number in range(pages_to_scan):
        offset = page_number * page_size
        if offset >= provider_total:
            break
        page = list(
            _call(
                "tidal",
                "favorite_tracks_cache_maintenance",
                lambda offset=offset: tidal.user.favorites.tracks(
                    limit=page_size,
                    offset=offset,
                    order=ItemOrder.Date,
                    order_direction=OrderDirection.Descending,
                ),
                limit=page_size,
                offset=offset,
                page=page_number + 1,
            )
            or []
        )
        fetched.extend(page)
        known_page_ids = [
                str(getattr(track, "id", ""))
                for track in page
                if str(getattr(track, "id", "")) in existing_set
        ]
        boundary_track_id = known_page_ids[-1] if known_page_ids else None
        progress(
            f"Checked {min(offset + len(page), provider_total):,} newest liked tracks "
            f"(TIDAL library: {provider_total:,})"
        )
        if boundary_track_id:
            break
        if delay_seconds and page_number + 1 < pages_to_scan:
            time.sleep(delay_seconds)

    scanned_entire_library = len(fetched) >= provider_total
    result = merge_tidal_liked_tracks_prefix(
        user_id,
        fetched,
        boundary_track_id,
        preserve_unscanned_tail=not scanned_entire_library,
    )
    result["provider_total"] = provider_total
    LOGGER.info(
        "liked_cache.maintenance user_id=%s provider_total=%d fetched=%d "
        "added=%d cached=%d boundary=%s",
        user_id,
        provider_total,
        result["fetched"],
        result["added"],
        result["cached"],
        boundary_track_id or "none",
    )
    return result


def run_all_syncs(path: Path = CONFIG_PATH, progress: Callable[[str], None] | None = None) -> list[SyncResult]:
    progress = progress or (lambda _: None)
    config = load_config(path)
    enabled = [item for item in config["playlists"] if item.get("enabled", True)]
    maintain_liked = config["settings"].get("maintain_liked_tracks_cache", True)
    LOGGER.info("sync.run start config=%s enabled_playlists=%d", path, len(enabled))
    if not enabled and not maintain_liked:
        return []
    directions = {item.get("direction", "spotify_to_tidal") for item in enabled}
    spotify = None
    if directions & {"spotify_to_tidal", "tidal_to_spotify"}:
        progress("Connecting to Spotify…")
        spotify = spotify_client()
        profile = _call("spotify", "current_user", spotify.current_user)
        LOGGER.info(
            "spotify.auth connected user_id=%s display_name=%r",
            profile.get("id"),
            profile.get("display_name"),
        )
    progress("Connecting to TIDAL…")
    tidal = tidal_client(interactive=False)
    if maintain_liked:
        progress("Maintaining liked tracks cache…")
        try:
            liked_result = maintain_tidal_liked_tracks(
                tidal, config["settings"], progress
            )
            progress(
                f"Liked tracks cache: {liked_result['cached']:,} local, "
                f"{liked_result['added']:,} newly discovered"
            )
        except Exception:
            LOGGER.exception("liked_cache.maintenance_failed")
            progress("Liked tracks cache maintenance failed; continuing playlist sync")
    if not enabled:
        return []
    results: list[SyncResult] = []
    for index, entry in enumerate(enabled, start=1):
        mapping_name = entry.get("name") or f"Playlist mapping {index}"
        mapping_token = CURRENT_MAPPING.set(mapping_name)
        direction = entry.get("direction", "spotify_to_tidal")
        source_id = entry.get("spotify", "") if direction == "spotify_to_tidal" else entry.get("tidal", "")
        LOGGER.info(
            "sync.mapping start name=%r position=%d/%d direction=%s source=%s",
            mapping_name, index, len(enabled), direction, source_id,
        )
        progress(f"Syncing {mapping_name} ({index}/{len(enabled)})…")
        try:
            result = sync_one(spotify, tidal, entry, config["settings"])
            results.append(result)
            if result.skipped:
                LOGGER.info("sync.mapping skipped name=%r reason=source_unchanged", mapping_name)
            else:
                LOGGER.info(
                    "sync.mapping success name=%r added=%d already_present=%d unmatched=%d",
                    mapping_name, result.added, result.already_present, result.unmatched,
                )
        except Exception as exc:  # Continue with the other configured playlists.
            LOGGER.exception("sync.mapping failed name=%r source=%s", mapping_name, source_id)
            results.append(SyncResult(entry.get("spotify", ""), entry.get("tidal", ""), error=str(exc), label=entry.get("name", "")))
        finally:
            CURRENT_MAPPING.reset(mapping_token)
    save_config(config, path)  # Stores IDs of playlists created during this run.
    LOGGER.info("sync.run complete playlists=%d failures=%d", len(results), sum(bool(item.error) for item in results))
    return results


def create_app():
    """Build the active FastAPI application."""
    from backend.app.main import create_app as create_fastapi_app

    return create_fastapi_app()


def main() -> None:
    configure_logging()
    LOGGER.info("application.start root=%s", ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", action="store_true", help="sync without starting the web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    if args.sync:
        for result in run_all_syncs(progress=print):
            print(json.dumps(asdict(result), ensure_ascii=False))
        return
    import uvicorn
    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
