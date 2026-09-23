"""Presentation entry point for searching the complete local music library."""

from __future__ import annotations

from typing import Any

from music_tools.track_browser import content as track_browser_content


def content(
    html: Any,
    dcc: Any,
    quick_views: list[dict[str, Any]] | None = None,
    view_state: dict[str, Any] | None = None,
):
    """Embed the shared browser with a global SQLite collection descriptor."""
    return track_browser_content(
        html,
        dcc,
        collection={"type": "search", "id": "global", "name": "Global search"},
        quick_views=quick_views,
        view_state=view_state,
    )
