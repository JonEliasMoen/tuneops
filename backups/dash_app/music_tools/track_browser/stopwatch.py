"""Shared client-side stopwatch controls for timestamped track tables."""

from __future__ import annotations

from typing import Any


def content(html: Any):
    """Render controls driven entirely by the global browser-side timer."""
    return html.Div(
        [
            html.Span("00:00.0", className="mix-stopwatch-time"),
            html.Button(
                "Start",
                className="mix-stopwatch-toggle primary",
                **{"data-stopwatch-action": "toggle"},
            ),
            html.Button(
                "Stop",
                className="mix-stopwatch-stop",
                **{"data-stopwatch-action": "stop"},
            ),
            html.Span(
                "Rows with Time/Position are highlighted while they play.",
                className="hint",
            ),
        ],
        className="mix-stopwatch",
        **{"data-mix-stopwatch": "true"},
    )


__all__ = ["content"]
