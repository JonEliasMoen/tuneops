"""Best-effort conversion from 1001Tracklists to TuneOps staging rows."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from backend.music_tools.watched_mixes.tracklist import parse_tracklist

from .tracklists import Tracklist


LOGGER = logging.getLogger("musicsync")
CUE_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def _track_line(track: Any) -> str:
    name = str(getattr(track, "full_title", "") or "").strip()
    cue = str(getattr(track, "cue", "") or "").strip()
    if cue and not CUE_RE.fullmatch(cue):
        cue = ""
    return " ".join(part for part in (cue, name) if part)


def fetch_staging_tracklist(
    video_url: str,
    *,
    tracklist_factory: Callable[[str], Any] = Tracklist,
) -> dict[str, Any]:
    """Search 1001Tracklists and convert Track cue/name data to staging rows.

    Network and parsing errors intentionally propagate. The Add Mix API owns
    the best-effort boundary so a failed third-party lookup never prevents the
    watched mix itself from being saved.
    """
    LOGGER.info("tracklist.import start")
    tracklist = tracklist_factory(video_url)
    lines = [line for track in tracklist.tracks if (line := _track_line(track))]
    rows = parse_tracklist("\n".join(lines), "artist_title")
    searchable = sum(
        row.get("status") not in {"invalid", "unresolved"} for row in rows
    )
    cues = sum(bool(row.get("timestamp")) for row in rows)
    LOGGER.info(
        "tracklist.import complete tracklist_id=%s track_objects=%d lines=%d "
        "staging_rows=%d searchable=%d cues=%d",
        str(getattr(tracklist, "tracklist_id", "") or ""),
        len(tracklist.tracks),
        len(lines),
        len(rows),
        searchable,
        cues,
    )
    return {
        "source_url": str(getattr(tracklist, "url", "") or ""),
        "rows": rows,
        "tracks_found": len(lines),
        "searchable": searchable,
    }
