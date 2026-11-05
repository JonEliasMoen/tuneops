"""Shared TIDAL catalogue search and candidate ranking."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.music_library.database import tidal_track_record


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def find_tidal_matches(
    engine: Any,
    session: Any,
    row: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search TIDAL and return serializable candidates ranked by title and artist."""
    import tidalapi

    query = f"{row.get('artist', '')} {row.get('title', '')}".strip()
    response = engine._call(
        "tidal",
        "track_search",
        lambda: session.search(query, models=[tidalapi.Track], limit=limit),
        query=query,
        limit=limit,
    )
    wanted_title = _normalized(row.get("title", ""))
    wanted_artist = _normalized(row.get("artist", ""))
    candidates = []
    for track in (response or {}).get("tracks", []):
        record = tidal_track_record(track)
        title = _normalized(record.get("title", ""))
        artist = _normalized(record.get("artist", ""))
        score = 0
        if title == wanted_title:
            score += 6
        elif title in wanted_title or wanted_title in title:
            score += 3
        if artist == wanted_artist:
            score += 4
        elif artist and wanted_artist and (artist in wanted_artist or wanted_artist in artist):
            score += 2
        record["score"] = score
        record["label"] = (
            f"{record.get('artist') or 'Unknown'} — {record.get('title') or 'Unknown'}"
            + (f" ({record['remix']})" if record.get("remix") else "")
        )
        candidates.append(record)
    candidates.sort(key=lambda item: (-int(item.get("score", 0)), item.get("label", "")))
    return candidates
