"""Dash presentation for the TIDAL liked-tracks browser."""

from __future__ import annotations

from typing import Any

from music_library.database import tidal_playlists_for_track

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
                        html.P("Your liked TIDAL tracks, newest first."),
                    ]
                ),
                html.Button("Refresh", id="liked-refresh", className="primary"),
            ],
            className="tool-heading",
        ),
        dcc.Interval(id="liked-initial-load", interval=250, max_intervals=1, n_intervals=0),
        dcc.Store(id="liked-rows", data=[]),
        dcc.Store(id="liked-selected", data=None),
        dcc.Store(id="liked-has-more", data=True),
        dcc.Store(id="liked-load-next", data=0),
        html.Div(id="liked-keyboard-ready", style={"display": "none"}),
        html.Div("Loading liked tracks…", id="liked-status", className="track-status"),
        html.Div(
            [
                html.Div(
                    dcc.Loading(html.Div(id="liked-table"), type="circle"),
                    className="track-list-pane",
                ),
                html.Aside(
                    html.Div("Select a track", className="detail-empty"),
                    id="liked-details",
                    className="track-details",
                ),
            ],
            className="library-layout",
        ),
    ]


def register_callbacks(
    app: Any, callback: Any, Input: Any, Output: Any, State: Any,
    html: Any, ctx: Any, engine: Any
) -> None:
    @callback(
        Output("liked-table", "children"),
        Output("liked-status", "children"),
        Output("liked-rows", "data"),
        Output("liked-selected", "data"),
        Output("liked-has-more", "data"),
        Input("liked-initial-load", "n_intervals"),
        Input("liked-refresh", "n_clicks"),
        Input("liked-load-next", "data"),
        State("liked-rows", "data"),
        State("liked-selected", "data"),
    )
    def load_tracks(
        _initial: int,
        _refresh: int | None,
        _load_next: int,
        existing_rows: list[dict[str, str]] | None,
        current_selection: int | None,
    ):
        existing_rows = existing_rows or []
        append = ctx.triggered_id == "liked-load-next" and bool(existing_rows)
        offset = len(existing_rows) if append else 0
        try:
            page, has_more = fetch_liked_tracks(
                engine,
                offset=offset,
                force_refresh=ctx.triggered_id == "liked-refresh",
            )
        except Exception as exc:
            engine.LOGGER.exception("ui.liked_tracks load_failed")
            return html.Div(), f"Could not load liked tracks: {exc}", [], None, False

        rows = existing_rows + page if append else page

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
            [
                html.Table([header, body], className="track-table"),
                html.Div(
                    "Loading more…" if has_more else "End of liked tracks",
                    id="liked-scroll-sentinel",
                    className="scroll-sentinel",
                ),
            ],
            className="track-table-wrap",
        )
        selected = current_selection if append else (0 if rows else None)
        return (
            table,
            f"{len(rows):,} liked track{'s' if len(rows) != 1 else ''} loaded",
            rows,
            selected,
            has_more,
        )

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
        playlists = tidal_playlists_for_track(row.get("id", "")) if row.get("id") else []
        playlist_tags = (
            [
                html.Span(
                    playlist.get("name") or playlist.get("id"),
                    className="playlist-tag",
                    title=playlist.get("id", ""),
                )
                for playlist in playlists
            ]
            or [html.Span("Not in an indexed playlist", className="detail-empty")]
        )
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
            html.Div(
                [html.Span("Playlists"), html.Div(playlist_tags, className="playlist-tags")],
                className="detail-field detail-playlists",
            ),
        ]

    app.clientside_callback(
        """
        function(selected, rows, hasMore) {
            var previousCount = window.__likedTracksCount || 0;
            window.__likedTracksCount = (rows || []).length;
            window.__likedTracksSelected = selected;
            var rowsChanged = previousCount !== window.__likedTracksCount;

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
            window.setTimeout(function() {
                var viewport = document.querySelector('.track-table-wrap');
                if (rowsChanged && viewport && Number.isFinite(window.__likedTracksScrollTop)) {
                    viewport.scrollTop = window.__likedTracksScrollTop;
                }
                paintSelection();
            }, 0);

            if (window.__likedTracksObserver) {
                window.__likedTracksObserver.disconnect();
            }
            if (hasMore) {
                window.setTimeout(function() {
                    var sentinel = document.getElementById('liked-scroll-sentinel');
                    var viewport = sentinel && sentinel.closest('.track-table-wrap');
                    if (!sentinel || !viewport) return;
                    window.__likedTracksObserver = new IntersectionObserver(function(entries) {
                        if (!entries.some(function(entry) { return entry.isIntersecting; })) return;
                        window.__likedTracksObserver.disconnect();
                        window.__likedTracksScrollTop = viewport.scrollTop;
                        window.__likedTracksLoadToken = (window.__likedTracksLoadToken || 0) + 1;
                        window.dash_clientside.set_props('liked-load-next', {
                            data: window.__likedTracksLoadToken
                        });
                    }, {root: viewport, rootMargin: '120px 0px'});
                    window.__likedTracksObserver.observe(sentinel);
                }, 0);
            }
            return '';
        }
        """,
        Output("liked-keyboard-ready", "children"),
        Input("liked-selected", "data"),
        Input("liked-rows", "data"),
        Input("liked-has-more", "data"),
    )
