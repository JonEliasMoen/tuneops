"""Read-only profile of representative TuneOps collection requests.

The script never contacts Spotify, TIDAL, Last.fm, or YouTube. It uses the
configured database backend, so select Turso intentionally through the normal
environment variables when measuring remote latency.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import statistics
import time
from typing import Any, Callable

from backend.app.services.library import collection_page
from music_library.connection import database_backend
from music_library.telemetry import begin_database_metrics, end_database_metrics


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _measure(
    call: Callable[[], dict[str, Any]],
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    metrics, token = begin_database_metrics()
    started = time.perf_counter()
    try:
        result = call()
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, result, asdict(metrics)
    finally:
        end_database_metrics(token)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile read-only TuneOps collection queries without provider calls.",
    )
    parser.add_argument(
        "--collection",
        choices=["liked", "search", "playlist", "event", "source", "artist"],
        default="search",
    )
    parser.add_argument(
        "--id",
        default="",
        help="Collection/artist ID; defaults to liked or library where applicable.",
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--query",
        default="a",
        help="Existing-result filter used for the filtered scenario.",
    )
    args = parser.parse_args()
    limit = max(1, min(args.limit, 500))
    runs = max(1, args.runs)
    collection_id = args.id or (
        "liked" if args.collection == "liked"
        else "library" if args.collection == "search"
        else ""
    )
    if not collection_id:
        parser.error("--id is required for this collection type")

    scenarios: list[tuple[str, dict[str, Any]]] = [
        ("first_page", {"offset": 0}),
        ("next_page", {"offset": limit}),
        (
            "sorted",
            {
                "offset": 0,
                "sort_field": "date_added",
                "sort_direction": "desc",
            },
        ),
        ("filtered", {"offset": 0, "query": args.query}),
        ("empty", {"offset": 0, "query": "__tuneops_no_such_track_7f9508__"}),
    ]
    print(
        f"backend={database_backend()} collection={args.collection}/{collection_id} "
        f"limit={limit} runs={runs}"
    )
    print(
        "scenario       cold_ms   p50_ms   p95_ms   rows   total   "
        "connections statements pipelines db_ms"
    )
    for name, options in scenarios:
        call = lambda options=options: collection_page(
            args.collection,
            collection_id,
            limit=limit,
            **options,
        )
        cold_ms, page, _cold_metrics = _measure(call)
        timings: list[float] = []
        samples: list[dict[str, Any]] = []
        for _ in range(runs):
            elapsed, page, metrics = _measure(call)
            timings.append(elapsed)
            samples.append(metrics)
        median_metrics = {
            key: statistics.median([float(sample[key]) for sample in samples])
            for key in samples[0]
        }
        print(
            f"{name:<13} {cold_ms:>8.1f} {_percentile(timings, .5):>8.1f} "
            f"{_percentile(timings, .95):>8.1f} {len(page['items']):>6} "
            f"{int(page['total']):>7} {median_metrics['connections']:>11.0f} "
            f"{median_metrics['statements']:>10.0f} "
            f"{median_metrics['pipeline_calls']:>9.0f} "
            f"{median_metrics['database_ms']:>5.0f}"
        )


if __name__ == "__main__":
    main()
