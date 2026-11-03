"""Import Last.fm scrobbles and conservatively match them to local TIDAL tracks."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections import defaultdict
from typing import Any, Callable

import pylast

from backend.music_library.database import (
    lastfm_history_navigation,
    lastfm_latest_scrobble,
    mark_lastfm_track_backfill_error,
    pending_lastfm_track_backfills,
    store_lastfm_aggregate_import,
    store_lastfm_track_playcount_snapshots,
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


def _is_missing_track_error(exc: BaseException) -> bool:
    """Recognize Last.fm's inconsistent missing-track responses only."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, pylast.WSError):
            status = int(current.status)
            details = str(current.details or "").strip().casefold()
            return status == 7 or (status == 6 and details == "track not found")
        current = current.__cause__ or current.__context__
    return False


def backfill_new_track_playcounts(
    username: str,
    api_key: str,
    *,
    delay_seconds: float = 0.5,
    limit: int = 10,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Resolve all-time counts for a bounded batch of newly indexed tracks.

    Last.fm exposes an authoritative user playcount per artist/title, but no
    historical monthly buckets through this endpoint. The snapshot therefore
    updates only ``lastfm_track_totals``; existing monthly aggregates remain
    untouched.
    """
    username = str(username or "").strip()
    api_key = str(api_key or "").strip()
    if not username or not api_key:
        return {"queued": 0, "checked": 0, "updated": 0, "plays_added": 0}
    # Without a committed recent-tracks watermark, a later first/full import
    # would replay the same historical plays and double-count this snapshot.
    # Keep the queue intact until that baseline import has committed.
    if lastfm_latest_scrobble(username) is None:
        return {"queued": 0, "checked": 0, "updated": 0, "plays_added": 0}
    rows = pending_lastfm_track_backfills(limit=max(1, min(100, int(limit))))
    if not rows:
        return {"queued": 0, "checked": 0, "updated": 0, "plays_added": 0}
    report = progress or (lambda _message: None)
    network = _MusicSyncLastFMNetwork(
        api_key=api_key, delay_seconds=delay_seconds,
    )
    snapshots: list[dict[str, Any]] = []
    checked: list[str] = []
    for index, row in enumerate(rows, start=1):
        track_id = str(row.get("id") or "")
        artist = str(row.get("artist") or "").strip()
        title = str(row.get("title") or "").strip()
        remix = str(row.get("remix") or "").strip()
        lookup_title = f"{title} ({remix})" if remix else title
        if not track_id or not artist or not lookup_title:
            checked.append(track_id)
            continue
        report(f"Checking Last.fm history: {index}/{len(rows)}")
        try:
            play_count = pylast.Track(
                artist, lookup_title, network, username=username,
            ).get_userplaycount()
        except Exception as exc:
            # A genuinely unknown artist/title is a successful zero-play
            # lookup. Authentication, quota and transport failures remain in
            # the queue and abort this bounded batch so we do not hammer Last.fm.
            if _is_missing_track_error(exc):
                play_count = 0
            else:
                safe_error = _pylast_error(exc)
                if snapshots or checked:
                    store_lastfm_track_playcount_snapshots(
                        username, snapshots, checked_track_ids=checked,
                    )
                mark_lastfm_track_backfill_error(track_id, str(safe_error))
                raise safe_error from exc
        snapshots.append({"track_id": track_id, "play_count": int(play_count or 0)})
        checked.append(track_id)
    stored = store_lastfm_track_playcount_snapshots(
        username, snapshots, checked_track_ids=checked,
    )
    return {"queued": len(rows), **stored}


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


def _indexed_matcher() -> tuple[
    dict[tuple[str, str], set[str]], dict[tuple[str, str], set[str]],
]:
    """Build an in-memory matcher from already indexed TuneOps tracks only."""
    records = tidal_library_tracks_page(limit=1_000_000)
    LOGGER.info(
        "lastfm.matcher indexed_tidal_tracks=%d", len(records)
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
    return exact_index, base_index


def _match_records_to_indexed_tracks(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    exact_index, base_index = _indexed_matcher()
    matched: list[dict[str, Any]] = []
    matched_identities: set[tuple[str, str]] = set()
    for record in records:
        artist_values = _artist_variants(str(record.get("artist") or ""))
        exact_titles, base_titles = _title_variants(str(record.get("title") or ""))
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
            matched.append(
                {
                    **record,
                    "track_id": next(iter(candidates)),
                    "confidence": confidence,
                }
            )
            matched_identities.add(
                (
                    str(record.get("normalized_artist") or ""),
                    str(record.get("normalized_title") or ""),
                )
            )
    return matched, len(matched_identities)


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

        # pyLast streams newest-to-oldest. Collect the bounded import before
        # committing so the aggregate watermark advances atomically; a failed
        # import cannot leave partially incremented totals.
        records: list[dict[str, Any]] = []
        for played in recent_tracks:
            record = _played_track_record(played)
            if record is not None:
                records.append(record)
            if len(records) and len(records) % IMPORT_PAGE_SIZE == 0:
                progress(f"Fetched {len(records):,} Last.fm plays")
        fetched = len(records)
        LOGGER.info(
            "lastfm.import fetch_complete username=%r mode=%s plays=%d",
            username, mode, fetched,
        )
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

    progress(f"Matching {fetched:,} plays against indexed TuneOps tracks")
    matched, identities_matched = _match_records_to_indexed_tracks(records)
    latest_fetched = max(
        (int(record["played_at"]) for record in records), default=latest
    )
    added = store_lastfm_aggregate_import(
        username,
        matched,
        latest_scrobble_at=latest_fetched,
        expected_previous_latest=latest,
    )
    backfill = backfill_new_track_playcounts(
        username,
        api_key,
        delay_seconds=delay_seconds,
        progress=progress,
    )
    history = lastfm_history_navigation(username, minimum_tracks=1)
    progress(f"History cache ready: {len(history['months']):,} months")
    result = {
        "fetched": fetched,
        "added": added,
        "identities_checked": len({
            (
                str(record.get("normalized_artist") or ""),
                str(record.get("normalized_title") or ""),
            )
            for record in records
        }),
        "identities_matched": identities_matched,
        "scrobbles_matched": added,
        "history_months_cached": len(history["months"]),
        "history_track_months_cached": sum(
            int(item["track_count"]) for item in history["months"]
        ),
        "new_tracks_checked": backfill["checked"],
        "historical_plays_added": backfill["plays_added"],
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
