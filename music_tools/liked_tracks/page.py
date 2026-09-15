"""Dash presentation for the TIDAL liked-tracks browser."""

from __future__ import annotations

from typing import Any

from music_library.database import (
    add_tidal_playlist_membership,
    remove_tidal_playlist_membership,
    tidal_indexed_playlists,
    tidal_playlists_for_track,
    tidal_playlists_for_tracks,
)

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
    ("playlists", "Playlists"),
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
        dcc.Store(id="liked-focus", data="tracks"),
        dcc.Store(id="liked-action-mode", data=None),
        dcc.Store(id="liked-action-selected", data=0),
        dcc.Store(id="liked-action-request", data=None),
        html.Div(id="liked-keyboard-ready", style={"display": "none"}),
        html.Div("Loading liked tracks…", id="liked-status", className="track-status"),
        html.Div(
            [
                html.Div(
                    dcc.Loading(html.Div(id="liked-table"), type="circle"),
                    className="track-list-pane",
                ),
                html.Div(
                    [
                        html.Aside(
                            html.Div("Select a track", className="detail-empty"),
                            id="liked-details",
                            className="track-details",
                        ),
                        html.Aside(
                            [
                                html.H2("Actions"),
                                html.Div(id="liked-actions"),
                                html.Div(id="liked-action-feedback", className="action-feedback"),
                            ],
                            className="track-actions",
                        ),
                    ],
                    className="inspector-column",
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

        memberships = tidal_playlists_for_tracks([row.get("id", "") for row in page])
        for row in page:
            row["playlists"] = memberships.get(row.get("id", ""), [])

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

        def cell_content(key: str, row: dict[str, Any]):
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

        body = html.Tbody(
            [
                html.Tr(
                    [
                        html.Td(
                            cell_content(key, row),
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
                    if key != "playlists"
                ],
                className="detail-fields",
            ),
            html.Div(
                [html.Span("Playlists"), html.Div(playlist_tags, className="playlist-tags")],
                className="detail-field detail-playlists",
            ),
        ]

    @callback(
        Output("liked-actions", "children"),
        Input("liked-selected", "data"),
        Input("liked-rows", "data"),
        Input("liked-focus", "data"),
        Input("liked-action-mode", "data"),
        Input("liked-action-selected", "data"),
    )
    def show_actions(
        selected: int | None,
        rows: list[dict[str, Any]] | None,
        focus: str,
        mode: str | None,
        action_selected: int,
    ):
        rows = rows or []
        if selected is None or not 0 <= selected < len(rows):
            return html.Div("Select a track first", className="detail-empty")

        if mode is None:
            options = [
                ("add", "Add to playlist"),
                ("remove", "Remove from playlist"),
            ]
            return [
                html.Div(
                    label,
                    className="action-option selected" if focus == "actions" and index == action_selected else "action-option",
                    **{
                        "data-action-option": str(index),
                        "data-action-kind": action,
                    },
                )
                for index, (action, label) in enumerate(options)
            ]

        track = rows[selected]
        playlists = (
            tidal_indexed_playlists()
            if mode == "add"
            else tidal_playlists_for_track(track.get("id", ""))
        )
        heading = "Choose a playlist to add to" if mode == "add" else "Choose a playlist to remove from"
        if not playlists:
            empty = "No indexed playlists" if mode == "add" else "Track is not in an indexed playlist"
            return [html.Div(heading, className="action-prompt"), html.Div(empty, className="detail-empty")]
        return [
            html.Div(heading, className="action-prompt"),
            *[
                html.Div(
                    playlist.get("name") or playlist.get("id"),
                    className="action-option selected" if focus == "actions" and index == action_selected else "action-option",
                    title=playlist.get("id", ""),
                    **{
                        "data-action-option": str(index),
                        "data-playlist-id": playlist.get("id", ""),
                    },
                )
                for index, playlist in enumerate(playlists)
            ],
        ]

    @callback(
        Output("liked-action-feedback", "children"),
        Output("liked-rows", "data", allow_duplicate=True),
        Output("liked-focus", "data"),
        Output("liked-action-mode", "data"),
        Output("liked-action-selected", "data"),
        Input("liked-action-request", "data"),
        State("liked-rows", "data"),
        State("liked-selected", "data"),
        prevent_initial_call=True,
    )
    def execute_action(
        request: dict[str, Any] | None,
        rows: list[dict[str, Any]] | None,
        selected: int | None,
    ):
        rows = rows or []
        if not request or selected is None or not 0 <= selected < len(rows):
            return "", rows, "tracks", None, 0
        action = request.get("action")
        playlist_id = str(request.get("playlist_id") or "")
        track_id = str(rows[selected].get("id") or "")
        if action not in {"add", "remove"} or not playlist_id or not track_id:
            return "Invalid playlist action.", rows, "actions", action, 0

        try:
            session = engine.tidal_client(interactive=False)
            playlist = engine._target_playlist(session, playlist_id, "")
            if action == "add":
                engine._call(
                    "tidal",
                    "playlist_add_from_liked_tracks",
                    lambda: playlist.add([track_id], allow_duplicates=False),
                    playlist_id=playlist_id,
                    track_id=track_id,
                )
                add_tidal_playlist_membership(playlist_id, track_id)
                message = f"Added to {playlist.name}."
            else:
                removed = engine._call(
                    "tidal",
                    "playlist_remove_from_liked_tracks",
                    lambda: playlist.remove_by_id(track_id),
                    playlist_id=playlist_id,
                    track_id=track_id,
                )
                if not removed:
                    raise RuntimeError("TIDAL did not find that track in the playlist")
                remove_tidal_playlist_membership(playlist_id, track_id)
                message = f"Removed from {playlist.name}."

            updated_rows = [dict(row) for row in rows]
            memberships = tidal_playlists_for_track(track_id)
            updated_rows[selected]["playlists"] = memberships
            engine.LOGGER.info(
                "ui.liked_tracks action_ok action=%s track_id=%s playlist_id=%s",
                action,
                track_id,
                playlist_id,
            )
            return message, updated_rows, "tracks", None, 0
        except Exception as exc:
            engine.LOGGER.exception(
                "ui.liked_tracks action_failed action=%s track_id=%s playlist_id=%s",
                action,
                track_id,
                playlist_id,
            )
            return f"Action failed: {exc}", rows, "actions", action, 0

    app.clientside_callback(
        """
        function(selected, rows, hasMore, focus, actionMode, actionSelected, actionsChildren) {
            var previousCount = window.__likedTracksCount || 0;
            var previousSelected = window.__likedTracksSelected;
            window.__likedTracksCount = (rows || []).length;
            window.__likedTracksSelected = selected;
            window.__likedTracksFocus = focus || 'tracks';
            window.__likedActionMode = actionMode;
            window.__likedActionSelected = actionSelected || 0;
            var rowsChanged = previousCount !== window.__likedTracksCount;
            var selectionChanged = previousSelected !== selected;

            function paintSelection() {
                document.querySelectorAll('[data-liked-index]').forEach(function(row) {
                    row.classList.toggle(
                        'selected',
                        Number(row.dataset.likedIndex) === window.__likedTracksSelected
                    );
                });
                document.querySelectorAll('[data-action-option]').forEach(function(option) {
                    option.classList.toggle(
                        'selected',
                        window.__likedTracksFocus === 'actions' &&
                        Number(option.dataset.actionOption) === window.__likedActionSelected
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
                    window.dash_clientside.set_props('liked-focus', {data: 'tracks'});
                });
                document.addEventListener('click', function(event) {
                    var option = event.target.closest('[data-action-option]');
                    if (!option || window.location.pathname !== '/liked-tracks') return;
                    var index = Number(option.dataset.actionOption);
                    window.dash_clientside.set_props('liked-focus', {data: 'actions'});
                    window.dash_clientside.set_props('liked-action-selected', {data: index});
                    if (option.dataset.actionKind) {
                        window.dash_clientside.set_props('liked-action-mode', {
                            data: option.dataset.actionKind
                        });
                        window.dash_clientside.set_props('liked-action-selected', {data: 0});
                    } else if (option.dataset.playlistId && window.__likedActionMode) {
                        window.dash_clientside.set_props('liked-action-request', {
                            data: {
                                token: Date.now(),
                                action: window.__likedActionMode,
                                playlist_id: option.dataset.playlistId
                            }
                        });
                    }
                });
                document.addEventListener('keydown', function(event) {
                    if (window.location.pathname !== '/liked-tracks') return;
                    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
                    if (window.__likedTracksFocus === 'actions') {
                        var options = document.querySelectorAll('[data-action-option]');
                        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                            if (!options.length) return;
                            event.preventDefault();
                            var actionDelta = event.key === 'ArrowDown' ? 1 : -1;
                            var actionNext = Math.max(
                                0,
                                Math.min(options.length - 1, window.__likedActionSelected + actionDelta)
                            );
                            window.dash_clientside.set_props('liked-action-selected', {data: actionNext});
                            return;
                        }
                        if (event.key === 'ArrowLeft') {
                            event.preventDefault();
                            if (window.__likedActionMode) {
                                window.dash_clientside.set_props('liked-action-mode', {data: null});
                                window.dash_clientside.set_props('liked-action-selected', {data: 0});
                            } else {
                                window.dash_clientside.set_props('liked-focus', {data: 'tracks'});
                            }
                            return;
                        }
                        if ((event.key === 'ArrowRight' || event.key === 'Enter') && !window.__likedActionMode) {
                            var activeOption = options[window.__likedActionSelected];
                            if (!activeOption || !activeOption.dataset.actionKind) return;
                            event.preventDefault();
                            window.dash_clientside.set_props('liked-action-mode', {
                                data: activeOption.dataset.actionKind
                            });
                            window.dash_clientside.set_props('liked-action-selected', {data: 0});
                            return;
                        }
                        if ((event.key === 'ArrowRight' || event.key === 'Enter') && window.__likedActionMode) {
                            var playlistOption = options[window.__likedActionSelected];
                            if (!playlistOption || !playlistOption.dataset.playlistId) return;
                            event.preventDefault();
                            window.dash_clientside.set_props('liked-action-request', {
                                data: {
                                    token: Date.now(),
                                    action: window.__likedActionMode,
                                    playlist_id: playlistOption.dataset.playlistId
                                }
                            });
                        }
                        return;
                    }

                    if (event.key === 'ArrowRight' && Number.isInteger(window.__likedTracksSelected)) {
                        event.preventDefault();
                        window.dash_clientside.set_props('liked-focus', {data: 'actions'});
                        window.dash_clientside.set_props('liked-action-mode', {data: null});
                        window.dash_clientside.set_props('liked-action-selected', {data: 0});
                        return;
                    }
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
                if (selectionChanged && !rowsChanged && Number.isInteger(selected)) {
                    var selectedRow = document.querySelector(
                        '[data-liked-index="' + selected + '"]'
                    );
                    if (selectedRow) {
                        selectedRow.scrollIntoView({block: 'nearest', inline: 'nearest'});
                    }
                }
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
        Input("liked-focus", "data"),
        Input("liked-action-mode", "data"),
        Input("liked-action-selected", "data"),
        Input("liked-actions", "children"),
    )
