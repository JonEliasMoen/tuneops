"""Temporary parsing and TIDAL matching for watched-mix tracklists."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from music_library.database import tidal_track_record


TIMESTAMP_RE = re.compile(
    r"^\s*(?:\[(?P<bracketed>\d{1,2}:\d{2}(?::\d{2})?)\]"
    r"|(?P<plain>\d{1,2}:\d{2}(?::\d{2})?))\s*(?P<body>.+?)\s*$"
)
SEPARATOR_RE = re.compile(r"\s+[\-–—]\s+")
TRAILING_MARKER_RE = re.compile(r"\s+(?:\\?\*)+\s*$")
VERSUS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
MASHUP_SUFFIX_RE = re.compile(r"\s*\([^)]*\bmashup\b[^)]*\)\s*$", re.IGNORECASE)


def _track_parts(artist: str, title: str) -> list[tuple[str, str]]:
    """Expand an ``Artist A vs Artist B - Song A vs Song B`` mashup line."""
    artists = [part.strip() for part in VERSUS_RE.split(artist)]
    clean_title = MASHUP_SUFFIX_RE.sub("", title).strip()
    titles = [part.strip() for part in VERSUS_RE.split(clean_title)]
    if len(artists) > 1 and len(artists) == len(titles) and all(artists + titles):
        return list(zip(artists, titles))
    return [(artist, title)]


def parse_tracklist(text: str, order: str = "artist_title") -> list[dict[str, Any]]:
    """Parse timestamped lines without creating canonical library records."""
    rows = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        timestamp_match = TIMESTAMP_RE.match(line)
        timestamp = ""
        body = line
        if timestamp_match:
            timestamp = timestamp_match.group("bracketed") or timestamp_match.group("plain")
            body = timestamp_match.group("body").strip()
        body = TRAILING_MARKER_RE.sub("", body).strip()
        parts = SEPARATOR_RE.split(body, maxsplit=1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            rows.append(
                {
                    "row_id": line_number,
                    "raw_line": raw_line,
                    "timestamp": timestamp,
                    "artist": "",
                    "title": body,
                    "status": "invalid",
                    "matches": [],
                    "selected_id": "",
                }
            )
            continue
        left, right = (part.strip() for part in parts)
        artist, title = (right, left) if order == "title_artist" else (left, right)
        for part_index, (part_artist, part_title) in enumerate(_track_parts(artist, title)):
            unresolved = part_title.casefold() in {"id", "unknown", "?"}
            rows.append(
                {
                    # Mashup components need separate stable staging identities.
                    "row_id": line_number * 1000 + part_index,
                    "raw_line": raw_line,
                    "timestamp": timestamp,
                    "artist": part_artist,
                    "title": part_title,
                    "status": "unresolved" if unresolved else "unsearched",
                    "matches": [],
                    "selected_id": "",
                }
            )
    return rows


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def find_tidal_matches(engine: Any, session: Any, row: dict[str, Any], limit: int = 5):
    """Return serializable, ranked candidates for one parsed staging row."""
    import tidalapi

    query = f"{row.get('artist', '')} {row.get('title', '')}".strip()
    response = engine._call(
        "tidal",
        "watched_mix_track_search",
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
