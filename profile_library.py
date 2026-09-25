"""Read-only timing probe for the React/FastAPI SQLite collection path.

Run this before deciding whether the React table needs virtualization:

    python profile_library.py --collection search --limit 5000
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

from backend.app.services.library import collection_page


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure one local MusicSync collection query.")
    parser.add_argument(
        "--collection",
        choices=["liked", "search"],
        default="search",
        help="SQLite collection to measure (default: search).",
    )
    parser.add_argument("--limit", type=int, default=5000, help="Rows requested per timing pass.")
    parser.add_argument("--runs", type=int, default=3, help="Timing passes after a warm-up pass.")
    args = parser.parse_args()
    limit = max(1, min(args.limit, 1_000_000))
    collection_id = "liked" if args.collection == "liked" else "library"

    # Warm SQLite's OS cache without changing provider or library state.
    collection_page(args.collection, collection_id, offset=0, limit=limit)
    timings: list[float] = []
    page = None
    for _ in range(max(1, args.runs)):
        started = time.perf_counter()
        page = collection_page(args.collection, collection_id, offset=0, limit=limit)
        timings.append((time.perf_counter() - started) * 1000)

    assert page is not None
    print(json.dumps({
        "collection": args.collection,
        "requested_rows": limit,
        "available_rows": page["total"],
        "returned_rows": len(page["items"]),
        "runs": len(timings),
        "median_ms": round(statistics.median(timings), 1),
        "min_ms": round(min(timings), 1),
        "max_ms": round(max(timings), 1),
        "note": "SQLite and Python collection preparation only; browser DOM rendering is measured separately.",
    }, indent=2))


if __name__ == "__main__":
    main()
