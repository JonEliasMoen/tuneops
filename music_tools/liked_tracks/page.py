"""Dash presentation for the TIDAL liked-tracks browser."""

from __future__ import annotations

from typing import Any

from .service import fetch_liked_tracks


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
]


def content(html: Any, dcc: Any):
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.H1("TIDAL liked tracks"),
                        html.P("Your 10 most recently liked TIDAL tracks."),
                    ]
                ),
                html.Button("Refresh", id="liked-refresh", className="primary"),
            ],
            className="tool-heading",
        ),
        dcc.Interval(id="liked-initial-load", interval=250, max_intervals=1, n_intervals=0),
        dcc.Store(id="liked-rows", data=[]),
        dcc.Store(id="liked-selected", data=None),
        html.Div(id="liked-keyboard-ready", style={"display": "none"}),
        dcc.Loading(
            [
                html.Div("Loading liked tracks…", id="liked-status", className="track-status"),
                html.Div(
                    [
                        html.Div(id="liked-table"),
                        html.Aside(
                            html.Div("Select a track", className="detail-empty"),
                            id="liked-details",
                            className="track-details",
                        ),
                    ],
                    className="library-layout",
                ),
            ],
            type="circle",
        ),
    ]


def register_callbacks(app: Any, callback: Any, Input: Any, Output: Any, html: Any, engine: Any) -> None:
    @callback(
        Output("liked-table", "children"),
        Output("liked-status", "children"),
        Output("liked-rows", "data"),
        Output("liked-selected", "data"),
        Input("liked-initial-load", "n_intervals"),
        Input("liked-refresh", "n_clicks"),
    )
    def load_tracks(_initial: int, _refresh: int | None):
        try:
            rows = fetch_liked_tracks(engine)
        except Exception as exc:
            engine.LOGGER.exception("ui.liked_tracks load_failed")
            return html.Div(), f"Could not load liked tracks: {exc}", [], None

        def cell_style(key: str, value: str) -> dict[str, str] | None:
            if key != "key" or len(value) != 3 or not value[:2].isdigit():
                return None
            position = int(value[:2])
            # Camelot wheel palette: turquoise at 1, clockwise through green,
            # yellow, orange, pink, purple and blue, then cyan at 12.
            hues = [168, 145, 100, 48, 20, 350, 330, 305, 275, 230, 195, 180]
            is_minor = value.endswith("A")
            return {
                "color": f"hsl({hues[position - 1]}, {'68%' if is_minor else '82%'}, {'76%' if is_minor else '66%'})",
                "fontWeight": "700",
            }

        header = html.Thead(html.Tr([html.Th(label) for _, label in COLUMNS]))
        body = html.Tbody(
            [
                html.Tr(
                    [
                        html.Td(
                            row.get(key) or "—",
                            className="numeric" if key in {"length", "bpm", "year", "date_added"} else "",
                            style=cell_style(key, row.get(key, "")),
                        )
                        for key, _ in COLUMNS
                    ],
                    className="liked-track-row",
                    **{"data-liked-index": str(index)},
                )
                for index, row in enumerate(rows)
            ]
        )
        table = html.Div(
            html.Table([header, body], className="track-table"),
            className="track-table-wrap",
        )
        selected = 0 if rows else None
        return table, f"{len(rows):,} liked track{'s' if len(rows) != 1 else ''}", rows, selected

    @callback(
        Output("liked-details", "children"),
        Input("liked-selected", "data"),
        Input("liked-rows", "data"),
    )
    def show_details(selected: int | None, rows: list[dict[str, str]] | None):
        rows = rows or []
        if selected is None or not 0 <= selected < len(rows):
            return html.Div("Select a track", className="detail-empty")
        row = rows[selected]
        return [
            html.Div("Selected track", className="detail-eyebrow"),
            html.H2(row.get("title") or "—", className="detail-title"),
            html.Div(row.get("artist") or "—", className="detail-artist"),
            html.Div(
                [
                    html.Div(
                        [html.Span(label), html.Strong(row.get(key) or "—")],
                        className="detail-field",
                    )
                    for key, label in COLUMNS[2:]
                ],
                className="detail-fields",
            ),
        ]

    app.clientside_callback(
        """
        function(selected, rows) {
            window.__likedTracksCount = (rows || []).length;
            window.__likedTracksSelected = selected;

            function paintSelection() {
                document.querySelectorAll('[data-liked-index]').forEach(function(row) {
                    row.classList.toggle(
                        'selected',
                        Number(row.dataset.likedIndex) === window.__likedTracksSelected
                    );
                });
            }

            if (!window.__likedTracksNavigationInstalled) {
                window.__likedTracksNavigationInstalled = true;
                document.addEventListener('click', function(event) {
                    var row = event.target.closest('[data-liked-index]');
                    if (!row || window.location.pathname !== '/liked-tracks') return;
                    window.dash_clientside.set_props('liked-selected', {
                        data: Number(row.dataset.likedIndex)
                    });
                });
                document.addEventListener('keydown', function(event) {
                    if (window.location.pathname !== '/liked-tracks') return;
                    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
                    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
                    if (!window.__likedTracksCount) return;
                    event.preventDefault();
                    var current = Number.isInteger(window.__likedTracksSelected)
                        ? window.__likedTracksSelected : 0;
                    var delta = event.key === 'ArrowDown' ? 1 : -1;
                    var next = Math.max(0, Math.min(window.__likedTracksCount - 1, current + delta));
                    window.dash_clientside.set_props('liked-selected', {data: next});
                });
            }
            window.setTimeout(paintSelection, 0);
            return '';
        }
        """,
        Output("liked-keyboard-ready", "children"),
        Input("liked-selected", "data"),
        Input("liked-rows", "data"),
    )
