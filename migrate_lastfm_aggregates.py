"""Explicitly migrate legacy Last.fm events to aggregate-only storage."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from music_library.database import (
    finalize_lastfm_aggregate_cutover,
    legacy_lastfm_usernames,
    rebuild_lastfm_aggregates_from_legacy,
)


def _verify_aggregate_database(database: Path) -> dict[str, int | str | bool]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        raw_present = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='lastfm_scrobbles'"
        ).fetchone() is not None
        totals = connection.execute(
            """SELECT COUNT(*) AS rows, COALESCE(SUM(play_count), 0) AS plays
               FROM lastfm_track_totals"""
        ).fetchone()
        monthly = connection.execute(
            """SELECT COUNT(*) AS rows, COALESCE(SUM(play_count), 0) AS plays
               FROM lastfm_monthly_track_counts"""
        ).fetchone()
        state = connection.execute(
            "SELECT COALESCE(SUM(matched_play_count), 0) FROM lastfm_import_state"
        ).fetchone()[0]
    finally:
        connection.close()
    result: dict[str, int | str | bool] = {
        "integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "raw_table_present": raw_present,
        "track_total_rows": int(totals["rows"]),
        "monthly_rows": int(monthly["rows"]),
        "total_plays": int(totals["plays"]),
        "monthly_plays": int(monthly["plays"]),
        "state_plays": int(state),
    }
    if (
        integrity != "ok"
        or foreign_keys
        or raw_present
        or result["total_plays"] != result["monthly_plays"]
        or result["total_plays"] != result["state_plays"]
    ):
        raise RuntimeError(f"Post-cutover verification failed: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Build, verify, and promote aggregate-only Last.fm storage.",
    )
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"Database does not exist: {database}")

    users = legacy_lastfm_usernames(database)
    if not users:
        result = _verify_aggregate_database(database)
        print("No legacy Last.fm event table/users were found.")
        print(
            f"Aggregate database verified: {result['total_plays']:,} plays, "
            f"{result['track_total_rows']:,} tracks, "
            f"{result['monthly_rows']:,} track-months."
        )
        return
    print(f"Database: {database}")
    print(f"Legacy Last.fm users: {len(users)}")
    if not args.apply:
        print("Dry run only. Stop TuneOps, confirm a backup, then rerun with --apply.")
        return

    for username in users:
        result = rebuild_lastfm_aggregates_from_legacy(username, path=database)
        print(
            f"{username}: {result['matched_plays']:,} matched plays, "
            f"{result['tracks']:,} tracks, {result['months']:,} months"
        )
    removed = finalize_lastfm_aggregate_cutover(database)
    print(
        f"Cutover complete: {removed['matched_plays']:,} matched plays retained; "
        f"{removed['raw_rows_removed']:,} legacy event rows removed."
    )
    verified = _verify_aggregate_database(database)
    print(
        f"Integrity verified: {verified['track_total_rows']:,} tracks and "
        f"{verified['monthly_rows']:,} track-months."
    )


if __name__ == "__main__":
    main()
