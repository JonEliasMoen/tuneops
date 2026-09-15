"""Dash app and sync engine for copying Spotify playlists to TIDAL.

Run the UI with ``python musicsync.py``.  The same ``run_all_syncs`` function is
used by startup_sync.py, so scheduled and manual syncs behave identically.
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
    store_tidal_playlist,
    tidal_track_record,
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
        file_handler = RotatingFileHandler(
            LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        LOGGER.addHandler(file_handler)
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
        },
        "playlists": [
            {
                "enabled": True,
                "name": "My playlist sync",
                "direction": "spotify_to_tidal",
                "spotify": "https://open.spotify.com/playlist/PASTE_ID_HERE",
                "tidal": "",
                "tidal_name": "",
            }
        ],
    }


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return default_config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("playlists"), list):
        raise ValueError("The config must contain a 'playlists' list")
    data.setdefault("settings", {})
    return data


def save_config(data: dict[str, Any], path: Path = CONFIG_PATH) -> None:
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
    if cache.exists() and label:
        return f"● {provider.title()} connected: {label}", "connection connected"
    if cache.exists():
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

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
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
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect,
        scope="playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public",
        cache_path=str(SPOTIFY_CACHE),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def spotify_auth_manager():
    """Build the OAuth manager without starting Spotipy's temporary web server."""
    try:
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    redirect = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8080/callback")
    if not client_id or not client_secret:
        raise RuntimeError("Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET")
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect,
        scope="playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public",
        cache_path=str(SPOTIFY_CACHE),
        open_browser=False,
    )


def _save_tidal_session(session: Any) -> None:
    expiry = session.expiry_time
    TIDAL_CACHE.write_text(
        json.dumps(
            {
                "token_type": session.token_type,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expiry_time": expiry.isoformat() if expiry else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    LOGGER.info("tidal.auth session_saved expiry=%s", expiry.isoformat() if expiry else "unknown")


def tidal_client(interactive: bool = False, message: Callable[[str], None] = print):
    try:
        import tidalapi
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    session = tidalapi.Session()
    LOGGER.info("tidal.auth initialize cache_exists=%s interactive=%s", TIDAL_CACHE.exists(), interactive)
    if TIDAL_CACHE.exists():
        try:
            saved = json.loads(TIDAL_CACHE.read_text(encoding="utf-8"))
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
    result.label = entry.get("name", "")
    if not result.skipped:
        entry["last_sync"] = datetime.now(timezone.utc).isoformat()
        LOGGER.info("sync.mapping timestamp name=%r last_sync=%s", result.label, entry["last_sync"])
    return result


def run_all_syncs(path: Path = CONFIG_PATH, progress: Callable[[str], None] | None = None) -> list[SyncResult]:
    progress = progress or (lambda _: None)
    config = load_config(path)
    enabled = [item for item in config["playlists"] if item.get("enabled", True)]
    LOGGER.info("sync.run start config=%s enabled_playlists=%d", path, len(enabled))
    if not enabled:
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


def _legacy_create_app():
    try:
        from dash import ALL, Dash, Input, Output, State, callback, ctx, dcc, html, no_update
        from flask import redirect, request
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    app = Dash(__name__, title="Spotify → TIDAL Sync")

    @app.server.get("/spotify/login")
    def spotify_login_route():
        try:
            url = spotify_auth_manager().get_authorize_url()
            LOGGER.info("spotify.auth redirect_to_authorize")
            return redirect(url)
        except Exception:
            LOGGER.exception("spotify.auth could_not_start")
            return redirect("/?spotify_error=start")

    @app.server.get("/callback")
    def spotify_callback_route():
        error = request.args.get("error")
        code = request.args.get("code")
        if error or not code:
            LOGGER.error("spotify.auth callback_rejected error=%s code_present=%s", error, bool(code))
            return redirect("/?spotify_error=denied")
        try:
            auth = spotify_auth_manager()
            _call("spotify", "exchange_authorization_code", lambda: auth.get_access_token(code, check_cache=False))
            user = _call("spotify", "current_user", spotify_client().current_user)
            label = str(user.get("display_name") or user.get("id"))
            _remember_connection("spotify", label)
            LOGGER.info("spotify.auth callback_complete user_id=%s", user.get("id"))
            return redirect("/?spotify=connected")
        except Exception:
            LOGGER.exception("spotify.auth callback_failed")
            return redirect("/?spotify_error=callback")
    initial = load_config()
    for row in initial["playlists"]:
        row.setdefault("name", "")
        row.setdefault("direction", "spotify_to_tidal")
    spotify_badge = _connection_badge("spotify", SPOTIFY_CACHE)
    tidal_badge = _connection_badge("tidal", TIDAL_CACHE)
    def mapping_card(row: dict[str, Any], index: int):
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Mapping name"),
                                dcc.Input(
                                    value=row.get("name", ""),
                                    placeholder=f"Playlist sync {index + 1}",
                                    type="text",
                                    id={"type": "mapping-label", "index": index},
                                    className="mapping-name",
                                ),
                            ],
                            className="mapping-title",
                        ),
                        html.Button("Remove", id={"type": "mapping-delete", "index": index}, className="danger"),
                    ],
                    className="mapping-head",
                ),
                dcc.Checklist(
                    options=[{"label": " Enabled", "value": "enabled"}],
                    value=["enabled"] if row.get("enabled", True) else [],
                    id={"type": "mapping-enabled", "index": index},
                ),
                html.Label("Sync direction"),
                dcc.Dropdown(
                    options=[
                        {"label": "Spotify → TIDAL", "value": "spotify_to_tidal"},
                        {"label": "TIDAL → Spotify", "value": "tidal_to_spotify"},
                    ],
                    value=row.get("direction", "spotify_to_tidal"),
                    clearable=False,
                    id={"type": "mapping-direction", "index": index},
                    className="direction-select",
                ),
                html.Div(
                    [
                        html.Div([html.Label("Spotify playlist URL or ID"), dcc.Input(value=row.get("spotify", ""), type="text", id={"type": "mapping-spotify", "index": index})], className="field"),
                        html.Div([html.Label("TIDAL playlist URL or ID"), dcc.Input(value=row.get("tidal", ""), type="text", id={"type": "mapping-tidal", "index": index})], className="field"),
                    ],
                    className="field-grid",
                ),
                html.Div(
                    [
                        html.Label("Target name override (optional — defaults to the source playlist name)"),
                        dcc.Input(value=row.get("tidal_name", ""), placeholder="Use source playlist name", type="text", id={"type": "mapping-name", "index": index}),
                    ],
                    className="field",
                ),
            ],
            className="mapping-card",
        )

    def rows_from_form(labels, enabled, directions, spotify_values, tidal_values, names, stored_rows=None) -> list[dict[str, Any]]:
        stored_rows = stored_rows or []
        rows = []
        for index in range(len(directions)):
            # Start with the stored object so hidden state such as unmatched
            # track records survives edits to the visible form fields.
            row = dict(stored_rows[index]) if index < len(stored_rows) else {}
            row.update(
                {
                    "enabled": "enabled" in (enabled[index] or []),
                    "name": labels[index] or "",
                    "direction": directions[index] or "spotify_to_tidal",
                    "spotify": spotify_values[index] or "",
                    "tidal": tidal_values[index] or "",
                    "tidal_name": names[index] or "",
                }
            )
            rows.append(row)
        return rows
    app.layout = html.Div(
        [
            html.Aside(
                [
                    html.Div(
                        [html.Span("♪", className="brand-mark"), html.Span("Music tools")],
                        className="brand",
                    ),
                    html.Nav(
                        [
                            html.A(
                                [html.Span("⇄", className="nav-icon"), html.Span("Playlist sync")],
                                href="/",
                                className="nav-item active",
                            ),
                        ],
                        className="side-nav",
                        **{"aria-label": "Main navigation"},
                    ),
                ],
                className="sidebar",
            ),
            html.Main(
                [
            html.H1("Spotify → TIDAL"),
            html.P("Configure playlist pairs, connect both accounts once, then sync on demand."),
            html.Div(
                [
                    html.Span(spotify_badge[0], id="spotify-state", className=spotify_badge[1]),
                    html.Span(tidal_badge[0], id="tidal-state", className=tidal_badge[1]),
                ],
                className="connections",
            ),
            html.Div(
                [
                    html.Button("Connect Spotify", id="spotify-login"),
                    html.Button("Connect TIDAL", id="tidal-login"),
                    html.Button("Sync now", id="sync", className="primary"),
                ],
                className="actions",
            ),
            dcc.Loading(html.Pre("Ready", id="status"), type="circle"),
            # One delayed check updates badges after an OAuth redirect without
            # continuously POSTing to Dash while the table is being edited.
            dcc.Interval(id="connection-refresh", interval=500, max_intervals=1, n_intervals=0),
            dcc.Store(id="mapping-store", data=initial["playlists"]),
            html.H2("Playlist mappings"),
            html.Div(id="mapping-list"),
            html.Div(
                [html.Button("Add row", id="add"), html.Button("Save configuration", id="save")],
                className="actions",
            ),
                    html.P(f"Configuration: {CONFIG_PATH}", className="hint"),
                ],
                className="page-content",
            ),
        ],
        className="app-shell",
    )

    @callback(Output("mapping-list", "children"), Input("mapping-store", "data"))
    def render_mappings(rows: list[dict[str, Any]]):
        return [mapping_card(row, index) for index, row in enumerate(rows)]

    @callback(
        Output("mapping-store", "data"),
        Input("add", "n_clicks"),
        Input({"type": "mapping-delete", "index": ALL}, "n_clicks"),
        State({"type": "mapping-label", "index": ALL}, "value"),
        State({"type": "mapping-enabled", "index": ALL}, "value"),
        State({"type": "mapping-direction", "index": ALL}, "value"),
        State({"type": "mapping-spotify", "index": ALL}, "value"),
        State({"type": "mapping-tidal", "index": ALL}, "value"),
        State({"type": "mapping-name", "index": ALL}, "value"),
        State("mapping-store", "data"),
        prevent_initial_call=True,
    )
    def change_rows(_, delete_clicks, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows):
        rows = rows_from_form(labels, enabled, directions, spotify_values, tidal_values, names, stored_rows)
        trigger = ctx.triggered_id
        if trigger == "add":
            rows.append({"enabled": True, "name": "", "direction": "spotify_to_tidal", "spotify": "", "tidal": "", "tidal_name": ""})
        elif isinstance(trigger, dict) and trigger.get("type") == "mapping-delete":
            index = int(trigger["index"])
            if index >= len(delete_clicks) or not delete_clicks[index]:
                return no_update
            if 0 <= index < len(rows):
                rows.pop(index)
        return rows

    @callback(
        Output("status", "children", allow_duplicate=True),
        Input("save", "n_clicks"),
        State({"type": "mapping-label", "index": ALL}, "value"),
        State({"type": "mapping-enabled", "index": ALL}, "value"),
        State({"type": "mapping-direction", "index": ALL}, "value"),
        State({"type": "mapping-spotify", "index": ALL}, "value"),
        State({"type": "mapping-tidal", "index": ALL}, "value"),
        State({"type": "mapping-name", "index": ALL}, "value"),
        State("mapping-store", "data"),
        prevent_initial_call=True,
    )
    def save_rows(_, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows):
        rows = rows_from_form(labels, enabled, directions, spotify_values, tidal_values, names, stored_rows)
        config = load_config()
        config["playlists"] = rows
        save_config(config)
        return f"Saved {len(rows)} mapping(s)."

    app.clientside_callback(
        "function(n) { if (n) { window.location.assign('/spotify/login'); } return window.dash_clientside.no_update; }",
        Output("spotify-login", "title"),
        Input("spotify-login", "n_clicks"),
        prevent_initial_call=True,
    )

    @callback(
        Output("spotify-state", "children"),
        Output("spotify-state", "className"),
        Output("tidal-state", "children"),
        Output("tidal-state", "className"),
        Input("connection-refresh", "n_intervals"),
        prevent_initial_call=True,
    )
    def refresh_connections(_: int):
        spotify = _connection_badge("spotify", SPOTIFY_CACHE)
        tidal = _connection_badge("tidal", TIDAL_CACHE)
        return spotify[0], spotify[1], tidal[0], tidal[1]

    @callback(
        Output("status", "children", allow_duplicate=True),
        Output("tidal-state", "children", allow_duplicate=True),
        Output("tidal-state", "className", allow_duplicate=True),
        Input("tidal-login", "n_clicks"),
        prevent_initial_call=True,
    )
    def connect_tidal(_: int):
        messages: list[str] = []
        try:
            LOGGER.info("ui.tidal_connect clicked")
            session = tidal_client(interactive=True, message=messages.append)
            label = str(getattr(session.user, "name", "") or session.user.id)
            _remember_connection("tidal", label)
            return f"TIDAL connected as {label}.", f"● TIDAL connected: {label}", "connection connected"
        except Exception as exc:
            LOGGER.exception("ui.tidal_connect failed")
            badge = _connection_badge("tidal", TIDAL_CACHE)
            return f"TIDAL connection failed: {exc}. " + " ".join(messages), badge[0], badge[1]

    @callback(
        Output("status", "children", allow_duplicate=True),
        Output("mapping-store", "data", allow_duplicate=True),
        Input("sync", "n_clicks"),
        State({"type": "mapping-label", "index": ALL}, "value"),
        State({"type": "mapping-enabled", "index": ALL}, "value"),
        State({"type": "mapping-direction", "index": ALL}, "value"),
        State({"type": "mapping-spotify", "index": ALL}, "value"),
        State({"type": "mapping-tidal", "index": ALL}, "value"),
        State({"type": "mapping-name", "index": ALL}, "value"),
        State("mapping-store", "data"),
        prevent_initial_call=True,
        running=[(Output("sync", "disabled"), True, False)],
    )
    def sync_now(_, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows):
        rows = rows_from_form(labels, enabled, directions, spotify_values, tidal_values, names, stored_rows)
        config = load_config()
        config["playlists"] = rows
        save_config(config)
        try:
            LOGGER.info("ui.sync clicked mappings=%d", len(rows))
            results = run_all_syncs()
            lines = []
            for result in results:
                prefix = f"{result.label}: " if result.label else ""
                if result.skipped:
                    lines.append(f"{prefix}skipped — source playlist has not changed since the last sync")
                elif result.error:
                    lines.append(f"{prefix}FAILED {result.source}: {result.error}")
                else:
                    lines.append(
                        f"{prefix}{result.target}: added {result.added}, already present "
                        f"{result.already_present}, unmatched {result.unmatched}"
                    )
            return "\n".join(lines) or "No enabled playlists.", load_config()["playlists"]
        except Exception as exc:
            LOGGER.exception("ui.sync failed")
            return f"Sync failed: {exc}", no_update

    app.index_string = """<!DOCTYPE html><html><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>body{margin:0;background:#0c1117;color:#e8edf2;font:16px system-ui}.app-shell{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;box-sizing:border-box;padding:26px 18px;background:#0a0f15;border-right:1px solid #26313d}.brand{display:flex;align-items:center;gap:10px;padding:0 10px 24px;font-size:19px;font-weight:700}.brand-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:#35e0a1;color:#07110d}.side-nav{display:flex;flex-direction:column;gap:6px}.nav-item{display:flex;align-items:center;gap:11px;padding:11px 13px;border-radius:9px;color:#aebbc7;text-decoration:none;font-weight:600}.nav-item:hover{background:#141e28;color:#fff}.nav-item.active{background:#17372c;color:#6be8ae}.nav-icon{font-size:20px}.page-content{box-sizing:border-box;width:calc(100% - 48px);max-width:1100px;margin:40px auto;padding:28px;background:#121a23;border-radius:18px}h1{color:#35e0a1}button{padding:10px 16px;margin:5px;border:0;border-radius:8px;cursor:pointer}.primary{background:#35e0a1}.danger{background:#48232a;color:#ffbdc5}.mapping-card{background:#18222d;border:1px solid #344252;border-radius:12px;padding:18px;margin:14px 0}.mapping-head{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:12px}.mapping-title{display:flex;flex-direction:column;gap:5px;flex:1}.mapping-name{box-sizing:border-box;width:min(430px,100%);padding:10px 12px;border:1px solid #46586b;border-radius:7px;background:#101923;color:#fff;font-size:18px;font-weight:600}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.field{display:flex;flex-direction:column;gap:6px;margin-top:14px}.field input{box-sizing:border-box;width:100%;padding:11px 12px;border:1px solid #46586b;border-radius:7px;background:#0d151e;color:#e8edf2;font:inherit}.field input:focus,.mapping-name:focus{outline:2px solid #35e0a1;border-color:transparent}label{color:#bdc8d2;font-size:14px}.direction-select{max-width:320px;color:#111}pre{background:#091016;padding:14px;border-radius:8px;white-space:pre-wrap}.actions,.connections{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.connection{padding:8px 12px;border-radius:999px;font-size:14px}.connected{color:#69e6a3;background:#123525}.disconnected{color:#aab5c0;background:#26313d}.hint{color:#91a0af;font-size:13px}@media(max-width:800px){.app-shell{display:block}.sidebar{position:static;width:100%;height:auto;padding:12px 16px;border-right:0;border-bottom:1px solid #26313d}.brand{padding:0 4px 10px}.side-nav{flex-direction:row}.nav-item{padding:8px 11px}.page-content{width:100%;margin:0;border-radius:0;padding:18px}.field-grid{grid-template-columns:1fr}}</style>
</head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""
    return app


def create_app():
    """Build the web UI from the playlist-sync feature package."""
    import sys

    from music_tools.playlist_sync import create_app as create_playlist_sync_app

    return create_playlist_sync_app(sys.modules[__name__])


def main() -> None:
    configure_logging()
    LOGGER.info("application.start root=%s", ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", action="store_true", help="sync without starting the web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.sync:
        for result in run_all_syncs(progress=print):
            print(json.dumps(asdict(result), ensure_ascii=False))
        return
    create_app().run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
