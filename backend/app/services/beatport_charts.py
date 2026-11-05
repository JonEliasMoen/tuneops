"""Shared, cache-backed Beatport chart reads for HTTP and MCP."""

from __future__ import annotations

from typing import Any

import main as engine
from backend.music_tools.beatport.beatport import client

from .library import matched_tidal_tracks_by_isrc


SETTING_KEY = "beatport_followed_charts"
SEARCHABLE_TYPES = frozenset({"genres", "labels", "artists"})
CHART_TYPES = frozenset({*SEARCHABLE_TYPES, "tracks"})


def valid_chart_reference(row: dict[str, object]) -> bool:
    kind = row.get("type")
    identifier = row.get("id")
    return bool(
        kind in CHART_TYPES
        and identifier
        and (kind != "tracks" or identifier == "top")
    )


def followed_chart_references() -> list[dict[str, str]]:
    rows = engine.load_runtime_settings().get(SETTING_KEY) or []
    return [
        {
            "type": str(row.get("type")),
            "id": str(row.get("id")),
            "name": str(row.get("name")),
        }
        for row in rows
        if isinstance(row, dict) and valid_chart_reference(row) and row.get("name")
    ][:50]


def chart_page(
    chart_type: str,
    chart_id: str,
    *,
    mode: str = "top",
    offset: int = 0,
    limit: int = 25,
    reference: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return one bounded chart page through the shared Beatport/Turso cache."""
    normalized_type = str(chart_type or "").strip()
    normalized_id = str(chart_id or "").strip()
    normalized_mode = str(mode or "").strip()
    if normalized_type not in CHART_TYPES:
        raise ValueError("Chart type is invalid")
    if not normalized_id or (normalized_type == "tracks" and normalized_id != "top"):
        raise ValueError("Chart ID is invalid")
    if normalized_mode not in {"top", "recent"}:
        raise ValueError("Chart mode is invalid")
    if normalized_type == "tracks" and normalized_mode != "top":
        raise ValueError("Top Beatport only supports Top mode")

    page_offset = max(0, int(offset))
    page_limit = max(1, min(50, int(limit)))
    if reference is None:
        reference = next(
            (
                row
                for row in followed_chart_references()
                if row["type"] == normalized_type and row["id"] == normalized_id
            ),
            None,
        )
    if normalized_mode == "top":
        provider_page_size = 10
        page = client.top_tracks(
            normalized_type,
            normalized_id,
            page=page_offset // provider_page_size + 1,
            chart_size=100,
        )
        items = page["items"]
        effective_limit = int(page["per_page"])
    else:
        page = client.recent_tracks(
            normalized_type,
            normalized_id,
            page=page_offset // page_limit + 1,
            per_page=page_limit,
        )
        items = page["items"]
        effective_limit = page_limit

    for position, item in enumerate(items, start=page_offset + 1):
        item["position"] = position
    matches = matched_tidal_tracks_by_isrc(
        [str(item.get("isrc") or "") for item in items]
    )
    for item in items:
        normalized_isrc = str(item.get("isrc") or "").strip().upper().replace("-", "")
        item["tidal_track"] = matches.get(normalized_isrc)
    return {
        "chart": reference or {
            "type": normalized_type,
            "id": normalized_id,
            "name": normalized_id,
        },
        "mode": normalized_mode,
        "items": items,
        "offset": page_offset,
        "limit": effective_limit,
        "total": int(page["total"]),
        "has_more": bool(page["has_more"]),
    }
