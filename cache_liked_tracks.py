"""Cache the connected user's complete TIDAL liked-track catalogue locally."""

from __future__ import annotations

import argparse
import sys
import time

import musicsync
from music_library.database import DATABASE_PATH, store_tidal_liked_tracks


def cache_all_liked_tracks(page_size: int = 100, delay_seconds: float = 0.5) -> int:
    """Fetch every liked-track page newest-first and persist it in SQLite."""
    from tidalapi.user import ItemOrder, OrderDirection

    session = musicsync.tidal_client(interactive=False)
    user_id = str(session.user.id)
    total_items = musicsync._call(
        "tidal",
        "favorite_tracks_count",
        session.user.favorites.get_tracks_count,
    )
    request_offset = 0
    cached_total = 0
    page_number = 0

    musicsync.LOGGER.info(
        "liked_cache.start user_id=%s provider_total=%d page_size=%d "
        "delay_seconds=%.2f database=%s",
        user_id,
        total_items,
        page_size,
        delay_seconds,
        DATABASE_PATH,
    )

    if total_items == 0:
        store_tidal_liked_tracks(user_id, [], offset=0)

    while request_offset < total_items:
        page_number += 1
        tracks = musicsync._call(
            "tidal",
            "favorite_tracks_full_cache",
            lambda: session.user.favorites.tracks(
                limit=page_size,
                offset=request_offset,
                order=ItemOrder.Date,
                order_direction=OrderDirection.Descending,
            ),
            limit=page_size,
            offset=request_offset,
            page=page_number,
            order="date_descending",
        )
        tracks = list(tracks or [])

        # Writing an empty final page also removes stale rows left by a formerly
        # larger catalogue when the previous page happened to be exactly full.
        store_tidal_liked_tracks(user_id, tracks, offset=request_offset)
        received = len(tracks)
        cached_total += received
        musicsync.LOGGER.info(
            "liked_cache.page page=%d offset=%d received=%d cached_total=%d "
            "provider_total=%d",
            page_number,
            request_offset,
            received,
            cached_total,
            total_items,
        )
        print(
            f"Cached {cached_total:,} available tracks "
            f"({min(request_offset + page_size, total_items):,}/{total_items:,} scanned)",
            flush=True,
        )

        # Advance by the requested slice, not the parsed result count. TIDAL's
        # total includes unavailable tracks, so a page can legitimately return
        # fewer objects before the catalogue has ended.
        request_offset += page_size
        if delay_seconds:
            time.sleep(delay_seconds)

    musicsync.LOGGER.info(
        "liked_cache.complete user_id=%s cached_tracks=%d provider_total=%d "
        "unavailable=%d pages=%d database=%s",
        user_id,
        cached_total,
        total_items,
        max(0, total_items - cached_total),
        page_number,
        DATABASE_PATH,
    )
    return cached_total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache the complete TIDAL liked-track catalogue in SQLite."
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Tracks requested per TIDAL call (default: 100).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between page requests (default: 0.5).",
    )
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size must be between 1 and 100")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    musicsync.configure_logging()
    try:
        total = cache_all_liked_tracks(args.page_size, args.delay)
    except Exception:
        musicsync.LOGGER.exception("liked_cache.failed")
        print("Liked-track cache failed. See music_sync.log for details.", file=sys.stderr)
        return 1
    print(f"Complete: {total:,} liked tracks cached in {DATABASE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
