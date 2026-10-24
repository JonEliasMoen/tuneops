"""Import Last.fm scrobbles and conservatively match them to local TIDAL tracks."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections import defaultdict
from typing import Any, Callable

import pylast

from music_library.database import (
    lastfm_latest_scrobble,
    lastfm_unmatched_identities,
    rebuild_lastfm_history_cache,
    set_lastfm_track_matches,
    store_lastfm_scrobbles,
    tidal_artists_for_tracks,
    tidal_library_tracks_page,
)


IMPORT_PAGE_SIZE = 200
LOGGER = logging.getLogger("musicsync")


class _MusicSyncLastFMNetwork(pylast.LastFMNetwork):
    """Use pyLast's normal client with the app's configurable request delay."""

    def __init__(self, *, api_key: str, delay_seconds: float) -> None:
        super().__init__(api_key=api_key)
        self._musicsync_delay_seconds = max(0.0, float(delay_seconds))
        self.enable_rate_limit()

    def _delay_call(self) -> None:
        elapsed = time.time() - self.last_call_time
        if elapsed < self._musicsync_delay_seconds:
            time.sleep(self._musicsync_delay_seconds - elapsed)
        self.last_call_time = time.time()


def _pylast_error(exc: Exception) -> RuntimeError:
    """Translate pyLast's exception chain without leaking request credentials."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, pylast.WSError):
            status = int(current.status)
            if status == pylast.STATUS_LOGIN_REQUIRED:
                return RuntimeError(
                    "Last.fm has hidden this account's recent listening history. "
                    "Make recent listening public in Last.fm Settings > Privacy, "
                    "then retry the import."
                )
            if status == pylast.STATUS_INVALID_API_KEY:
                return RuntimeError(
                    "Last.fm rejected LASTFM_API_KEY. Create or copy a valid API key, "
                    "update .env, and restart the app."
                )
            if status == pylast.STATUS_API_KEY_SUSPENDED:
                return RuntimeError("Last.fm reports that this API key is suspended.")
            if status == pylast.STATUS_RATE_LIMIT_EXCEEDED:
                return RuntimeError("Last.fm rate limit exceeded. Wait and retry later.")
            details = str(current.details or "").strip()
            return RuntimeError(
                f"Last.fm API error {status}: {details or 'request failed'}"
            )
        current = current.__cause__ or current.__context__
    return RuntimeError(
        "Could not retrieve Last.fm listening history. Check the connection and retry."
    )


def _played_track_record(played: pylast.PlayedTrack) -> dict[str, Any] | None:
    if not played.timestamp:
        return None
    artist_object = played.track.get_artist()
    artist = artist_object.get_name() if artist_object is not None else ""
    title = played.track.get_name()
    artist = str(artist or "").strip()
    title = str(title or "").strip()
    if not artist or not title:
        return None
    return {
        "played_at": int(played.timestamp),
        "artist": artist,
        "title": title,
        "album": str(played.album or "").strip(),
        "mbid": "",
        "normalized_artist": normalize(artist),
        "normalized_title": normalize(title),
    }


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _title_variants(title: str, remix: str = "") -> tuple[set[str], set[str]]:
    exact = {normalize(title)}
    if remix:
        exact.add(normalize(f"{title} {remix}"))
        exact.add(normalize(f"{title} ({remix})"))
    exact.discard("")
    base = {
        normalize(
            re.sub(
                r"\s*[\[(][^\])]*(?:mix|remix|edit|version|remaster|live)[^\])]*[\])]\s*$",
                "",
                title,
                flags=re.IGNORECASE,
            )
        )
    }
    base.discard("")
    return exact, base


def _artist_variants(value: str) -> set[str]:
    variants = {normalize(value)}
    for part in re.split(r"\s*(?:,|&|\+|\bfeat\.?\b|\bft\.?\b)\s*", value, flags=re.I):
        normalized = normalize(part)
        if normalized:
            variants.add(normalized)
    variants.discard("")
    return variants


def reconcile_track_matches(username: str) -> dict[str, int]:
    """Match only identities that resolve unambiguously to one local track."""
    records = tidal_library_tracks_page(limit=1_000_000)
    LOGGER.info(
        "lastfm.match start username=%r tidal_tracks=%d", username, len(records)
    )
    artist_map = tidal_artists_for_tracks([str(row.get("id") or "") for row in records])
    exact_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    base_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        track_id = str(record.get("id") or "")
        artists = {
            normalize(artist.get("name"))
            for artist in artist_map.get(track_id, [])
            if normalize(artist.get("name"))
        }
        artists.update(_artist_variants(str(record.get("artist") or "")))
        exact_titles, base_titles = _title_variants(
            str(record.get("title") or ""), str(record.get("remix") or "")
        )
        for artist in artists:
            for title in exact_titles:
                exact_index[(artist, title)].add(track_id)
            for title in base_titles:
                base_index[(artist, title)].add(track_id)

    identities = lastfm_unmatched_identities(username)
    matches: list[dict[str, str]] = []
    for identity in identities:
        artist_values = _artist_variants(identity.get("artist") or "")
        exact_titles, base_titles = _title_variants(identity.get("title") or "")
        exact_candidates = {
            track_id
            for artist in artist_values
            for title in exact_titles
            for track_id in exact_index.get((artist, title), set())
        }
        candidates = exact_candidates
        confidence = "exact"
        if not candidates:
            candidates = {
                track_id
                for artist in artist_values
                for title in base_titles
                for track_id in base_index.get((artist, title), set())
            }
            confidence = "base"
        if len(candidates) == 1:
            matches.append(
                {
                    "normalized_artist": identity["normalized_artist"],
                    "normalized_title": identity["normalized_title"],
                    "track_id": next(iter(candidates)),
                    "confidence": confidence,
                }
            )
    updated = set_lastfm_track_matches(username, matches)
    history_cache = rebuild_lastfm_history_cache(username)
    LOGGER.info(
        "lastfm.match complete username=%r identities_checked=%d "
        "identities_matched=%d scrobbles_matched=%d",
        username,
        len(identities),
        len(matches),
        updated,
    )
    return {
        "identities_checked": len(identities),
        "identities_matched": len(matches),
        "scrobbles_matched": updated,
        "history_months_cached": history_cache["months"],
        "history_track_months_cached": history_cache["tracks"],
    }


def import_scrobbles(
    username: str,
    api_key: str,
    delay_seconds: float = 0.5,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Import complete history once, then only plays newer than the local cache."""
    username = str(username or "").strip()
    api_key = str(api_key or "").strip()
    if not username:
        raise ValueError("Set your Last.fm username first.")
    if not api_key:
        raise ValueError("Set LASTFM_API_KEY in .env and restart the app.")
    progress = progress or (lambda _message: None)
    latest = lastfm_latest_scrobble(username)
    fetched = 0
    added = 0
    started_at = time.monotonic()
    mode = "incremental" if latest is not None else "full"
    LOGGER.info(
        "lastfm.import start username=%r mode=%s latest_timestamp=%s "
        "request_delay_seconds=%.3f",
        username,
        mode,
        latest if latest is not None else "none",
        max(0.0, float(delay_seconds)),
    )
    try:
        network = _MusicSyncLastFMNetwork(
            api_key=api_key, delay_seconds=delay_seconds
        )
        recent_tracks = network.get_user(username).get_recent_tracks(
            limit=None,
            cacheable=False,
            time_from=(latest + 1) if latest is not None else None,
            stream=True,
        )

        # pyLast streams newest-to-oldest. On the first import, collect and
        # reverse before committing so an interrupted retry cannot mistake a
        # partial newest page for a completed history. Incremental imports can
        # safely commit each chunk as it arrives because the old tail exists.
        if latest is None:
            played_items: list[pylast.PlayedTrack] = []
            for played in recent_tracks:
                played_items.append(played)
                if len(played_items) % IMPORT_PAGE_SIZE == 0:
                    message = (
                        f"Fetched {len(played_items):,} Last.fm plays; "
                        "still reading full history"
                    )
                    LOGGER.info(
                        "lastfm.import fetched username=%r mode=full plays=%d",
                        username,
                        len(played_items),
                    )
                    progress(message)
            LOGGER.info(
                "lastfm.import fetch_complete username=%r mode=full plays=%d",
                username,
                len(played_items),
            )
            played_items.reverse()
            batches = (
                played_items[index : index + IMPORT_PAGE_SIZE]
                for index in range(0, len(played_items), IMPORT_PAGE_SIZE)
            )
        else:
            def streamed_batches():
                batch: list[pylast.PlayedTrack] = []
                received = 0
                for played in recent_tracks:
                    batch.append(played)
                    received += 1
                    if len(batch) >= IMPORT_PAGE_SIZE:
                        LOGGER.info(
                            "lastfm.import fetched username=%r mode=incremental "
                            "plays=%d",
                            username,
                            received,
                        )
                        yield batch
                        batch = []
                if batch:
                    yield batch
                LOGGER.info(
                    "lastfm.import fetch_complete username=%r mode=incremental "
                    "plays=%d",
                    username,
                    received,
                )

            batches = streamed_batches()

        for batch_number, played_batch in enumerate(batches, start=1):
            records = [
                record
                for played in played_batch
                if (record := _played_track_record(played)) is not None
            ]
            fetched += len(records)
            batch_added = store_lastfm_scrobbles(username, records)
            added += batch_added
            message = (
                f"Imported {fetched:,} Last.fm plays "
                f"({batch_number:,} local batches)"
            )
            LOGGER.info(
                "lastfm.import stored username=%r batch=%d batch_fetched=%d "
                "batch_added=%d total_fetched=%d total_added=%d",
                username,
                batch_number,
                len(records),
                batch_added,
                fetched,
                added,
            )
            progress(message)
    except Exception as exc:
        safe_error = _pylast_error(exc)
        LOGGER.warning(
            "lastfm.import failed username=%r mode=%s duration_seconds=%.3f "
            "error=%s",
            username,
            mode,
            time.monotonic() - started_at,
            safe_error,
        )
        raise safe_error from exc

    matching = reconcile_track_matches(username)
    progress(
        f"History cache ready: {matching['history_months_cached']:,} months"
    )
    result = {
        "fetched": fetched,
        "added": added,
        **matching,
    }
    LOGGER.info(
        "lastfm.import complete username=%r mode=%s duration_seconds=%.3f "
        "fetched=%d added=%d identities_checked=%d identities_matched=%d "
        "scrobbles_matched=%d",
        username,
        mode,
        time.monotonic() - started_at,
        result["fetched"],
        result["added"],
        result["identities_checked"],
        result["identities_matched"],
        result["scrobbles_matched"],
    )
    return result
