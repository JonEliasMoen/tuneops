"""Declarative columns and rendering for the shared track table."""

from __future__ import annotations

from typing import Any


COLUMNS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("remix", "Remix"),
    ("album", "Album"),
    ("length", "Length"),
    ("bpm", "BPM"),
    ("key", "Key"),
    ("year", "Year"),
    ("date_added", "Date added"),
    ("playlists", "Playlists"),
]

EXTRA_COLUMNS_BY_COLLECTION = {
    "setlist": [("mix_position", "Position")],
}

DIMENSION_COLUMNS = [
    ("rating", "Rating"),
    ("energy", "Energy"),
    ("vibe", "Vibe"),
    ("movement", "Movement"),
    ("function", "Function"),
    ("structure", "Structure"),
]
DIMENSION_FIELDS = {key for key, _label in DIMENSION_COLUMNS}

KEY_HUES = [168, 145, 100, 48, 20, 350, 330, 305, 275, 230, 195, 180]


def columns_for(collection: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Return a stable schema even before a collection has loaded any rows."""
    extra = EXTRA_COLUMNS_BY_COLLECTION.get((collection or {}).get("type"), [])
    return [*extra, *COLUMNS, *DIMENSION_COLUMNS]


def default_visible_fields(collection: dict[str, Any] | None) -> list[str]:
    """Keep local classification columns opt-in while exposing them in Fields."""
    extra = EXTRA_COLUMNS_BY_COLLECTION.get((collection or {}).get("type"), [])
    return [key for key, _label in [*extra, *COLUMNS]]


def _time_seconds(value: Any) -> float:
    parts = str(value or "").split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return 0
    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return total


def _sort_value(row: dict[str, Any], field: str) -> tuple[bool, Any]:
    value = (
        (row.get("dimensions") or {}).get(field)
        if field in DIMENSION_FIELDS
        else row.get(field)
    )
    missing = value in (None, "", [], {})
    if field in {"length", "mix_position"}:
        normalized: Any = _time_seconds(value)
    elif field in {"bpm", "year", "rating", "energy"}:
        try:
            normalized = float(value[0] if isinstance(value, list) and value else value)
        except (TypeError, ValueError):
            normalized = 0.0
    elif field == "playlists":
        normalized = ", ".join(
            str(item.get("name") or item.get("id") or "")
            for item in (value or [])
        ).casefold()
    else:
        normalized = str(value or "").casefold()
    return missing, normalized


def sort_rows(
    rows: list[dict[str, Any]], sort: dict[str, str] | None
) -> list[dict[str, Any]]:
    """Sort rows predictably; no active sort restores their source order."""
    field = str((sort or {}).get("field") or "")
    direction = str((sort or {}).get("direction") or "")
    if not field or direction not in {"asc", "desc"}:
        return sorted(rows, key=lambda row: int(row.get("_source_order", 0)))
    present = [row for row in rows if not _sort_value(row, field)[0]]
    missing = [row for row in rows if _sort_value(row, field)[0]]
    present.sort(
        key=lambda row: _sort_value(row, field)[1],
        reverse=direction == "desc",
    )
    return [*present, *missing]


def render_track_table(
    html: Any,
    rows: list[dict[str, Any]],
    has_more: bool,
    collection: dict[str, Any] | None = None,
    visible_fields: list[str] | None = None,
    sort: dict[str, str] | None = None,
):
    """Render the table exclusively from its backing store and collection schema."""
    available_columns = columns_for(collection)
    visible = set(
        visible_fields
        if visible_fields is not None
        else default_visible_fields(collection)
    )
    columns = [column for column in available_columns if column[0] in visible]

    def cell_style(key: str, value: str) -> dict[str, str] | None:
        if key != "key" or len(value) != 3 or not value[:2].isdigit():
            return None
        position = int(value[:2])
        is_minor = value.endswith("A")
        return {
            "color": f"hsl({KEY_HUES[position - 1]}, {'68%' if is_minor else '82%'}, {'76%' if is_minor else '66%'})",
            "fontWeight": "700",
        }

    def cell_content(key: str, row: dict[str, Any]):
        if key in DIMENSION_FIELDS:
            values = (row.get("dimensions") or {}).get(key) or []
            if not values:
                return "—"
            if key == "rating":
                return "★" * int(values[0])
            return ", ".join(str(value) for value in values)
        if key != "playlists":
            return row.get(key) or "—"
        playlists = row.get("playlists") or []
        if not playlists:
            return "—"
        return html.Div(
            [
                html.Span(
                    playlist.get("name") or playlist.get("id"),
                    className="playlist-tag",
                    title=playlist.get("id", ""),
                )
                for playlist in playlists
            ],
            className="playlist-tags table-playlist-tags",
        )

    sort_field = (sort or {}).get("field")
    sort_direction = (sort or {}).get("direction")
    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    [
                        html.Span(label),
                        html.Span(
                            "▲" if sort_field == key and sort_direction == "asc"
                            else "▼" if sort_field == key and sort_direction == "desc"
                            else "",
                            className="sort-indicator",
                        ),
                    ],
                    className=f"sortable-column track-column-{key}",
                    **{"data-track-sort-key": key},
                )
                for key, label in columns
            ]
        )
    )
    body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(
                        cell_content(key, row),
                        className=" ".join(
                            part for part in [
                                f"track-column-{key}",
                                "numeric" if key in {"length", "bpm", "year", "date_added"} else "",
                            ] if part
                        ),
                        style=cell_style(key, row.get(key, "")),
                    )
                    for key, _ in columns
                ],
                className="liked-track-row",
                **{"data-liked-index": str(index)},
            )
            for index, row in enumerate(rows)
        ]
    )
    return html.Div(
        [
            html.Table([header, body], className="track-table"),
            html.Div(
                "Loading more…" if has_more else "End of tracks",
                id="liked-scroll-sentinel",
                className="scroll-sentinel",
            ),
        ],
        className="track-table-wrap",
    )
