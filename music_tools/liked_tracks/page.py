"""Dash presentation for the TIDAL liked-tracks browser."""

from __future__ import annotations

from typing import Any

from music_library.database import (
    add_tidal_playlist_membership,
    remove_tidal_playlist_membership,
    tidal_dimensions_for_tracks,
    tidal_indexed_playlists,
    tidal_playlists_for_track,
    tidal_playlists_for_tracks,
    toggle_tidal_track_dimension,
)
from music_tools.track_browser.table import (
    columns_for,
    default_visible_fields,
    render_track_table,
    sort_rows,
)

from .service import (
    fetch_indexed_playlist_tracks,
    fetch_indexed_setlist_tracks,
    fetch_liked_tracks,
)

DIMENSION_VALUES = {
    "rating": ["1", "2", "3", "4", "5"],
    "energy": ["1", "2", "3", "4", "5"],
    "vibe": ["Dreamy", "Dark", "Hypnotic", "Emotional", "Euphoric", "Atmospheric", "Warm", "Sexy"],
    "movement": ["Rolling", "Groovy", "Driving", "Bouncy", "Pumping", "Flowing", "Minimal"],
    "function": ["Opener", "Builder", "Peak", "Breather", "Bridge", "Closer", "Vibe Flip"],
    "structure": ["Groove-led", "Progressive", "Drop", "Big Drop", "Breakdown-heavy", "Vocal-led", "Tool"],
}
MULTI_VALUE_DIMENSIONS = {"vibe", "movement", "function", "structure"}


def content(html: Any, dcc: Any, collection: dict[str, Any] | None = None):
    collection = collection or {"type": "liked", "name": "TIDAL liked tracks"}
    is_liked = collection.get("type") == "liked"
    available_columns = columns_for(collection)
    visible_fields = default_visible_fields(collection)
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.H1(collection.get("name") or "TIDAL playlist"),
                        html.P(
                            "Your liked TIDAL tracks, newest first."
                            if is_liked
                            else "Tracks from the local TIDAL playlist index."
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Button("Refresh", id="liked-refresh", className="primary"),
                        html.Div(
                            [
                                html.Button("Fields", id="track-fields-toggle"),
                                html.Div(
                                    dcc.Checklist(
                                        id="track-visible-fields-control",
                                        options=[
                                            {"label": label, "value": key}
                                            for key, label in available_columns
                                        ],
                                        value=visible_fields,
                                        className="field-picker-options",
                                    ),
                                    id="track-fields-menu",
                                    className="field-picker-menu",
                                    style={"display": "none"},
                                ),
                            ],
                            className="field-picker",
                        ),
                    ],
                    className="track-toolbar",
                ),
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
        dcc.Store(id="track-sort", data={}),
        dcc.Store(id="track-sort-request", data=None),
        dcc.Store(id="track-visible-fields", data=visible_fields),
        dcc.Store(id="track-collection", data=collection),
        html.Div(
            id="track-browser-keyboard-ready",
            style={"display": "none"},
            **{"data-track-browser-root": "true"},
        ),
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
        Output("track-fields-menu", "style"),
        Input("track-fields-toggle", "n_clicks"),
        State("track-fields-menu", "style"),
        prevent_initial_call=True,
    )
    def toggle_field_menu(_clicks: int, style: dict[str, str] | None):
        is_open = (style or {}).get("display") != "none"
        return {"display": "none" if is_open else "block"}

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
        State("track-collection", "data"),
        State("track-sort", "data"),
        State("track-visible-fields", "data"),
    )
    def load_tracks(
        _initial: int,
        _refresh: int | None,
        _load_next: int,
        existing_rows: list[dict[str, str]] | None,
        current_selection: int | None,
        collection: dict[str, Any] | None,
        sort: dict[str, str] | None,
        visible_fields: list[str] | None,
    ):
        existing_rows = existing_rows or []
        append = ctx.triggered_id == "liked-load-next" and bool(existing_rows)
        offset = len(existing_rows) if append else 0
        try:
            if (collection or {}).get("type") == "setlist":
                page, has_more = fetch_indexed_setlist_tracks(
                    (collection or {}).get("id", ""), offset=offset
                )
            elif (collection or {}).get("type") == "playlist":
                page, has_more = fetch_indexed_playlist_tracks(
                    (collection or {}).get("id", ""), offset=offset
                )
            else:
                page, has_more = fetch_liked_tracks(
                    engine,
                    offset=offset,
                    force_refresh=ctx.triggered_id == "liked-refresh",
                )
        except Exception as exc:
            engine.LOGGER.exception("ui.liked_tracks load_failed")
            return html.Div(), f"Could not load liked tracks: {exc}", [], None, False

        memberships = tidal_playlists_for_tracks([row.get("id", "") for row in page])
        dimensions = tidal_dimensions_for_tracks([row.get("id", "") for row in page])
        for index, row in enumerate(page):
            row["playlists"] = memberships.get(row.get("id", ""), [])
            row["dimensions"] = dimensions.get(row.get("id", ""), {})
            row["_source_order"] = offset + index
        selected_order = None
        if append and current_selection is not None and 0 <= current_selection < len(existing_rows):
            selected_order = existing_rows[current_selection].get("_source_order")
        rows = sort_rows(existing_rows + page if append else page, sort)

        table = render_track_table(
            html, rows, has_more, collection, visible_fields, sort
        )
        selected = (
            next(
                (index for index, row in enumerate(rows) if row.get("_source_order") == selected_order),
                0 if rows else None,
            )
            if append
            else (0 if rows else None)
        )
        return (
            table,
            f"{len(rows):,} track{'s' if len(rows) != 1 else ''} loaded",
            rows,
            selected,
            has_more,
        )

    @callback(
        Output("track-sort", "data"),
        Output("track-visible-fields", "data"),
        Output("liked-rows", "data", allow_duplicate=True),
        Output("liked-table", "children", allow_duplicate=True),
        Output("liked-selected", "data", allow_duplicate=True),
        Input("track-sort-request", "data"),
        Input("track-visible-fields-control", "value"),
        State("track-sort", "data"),
        State("liked-rows", "data"),
        State("liked-selected", "data"),
        State("liked-has-more", "data"),
        State("track-collection", "data"),
        prevent_initial_call=True,
    )
    def change_table_view(
        sort_request: dict[str, Any] | None,
        visible_fields: list[str] | None,
        current_sort: dict[str, str] | None,
        current_rows: list[dict[str, Any]] | None,
        selected: int | None,
        has_more: bool,
        collection: dict[str, Any] | None,
    ):
        rows = current_rows or []
        sort = dict(current_sort or {})
        selected_order = (
            rows[selected].get("_source_order")
            if selected is not None and 0 <= selected < len(rows)
            else None
        )
        if ctx.triggered_id == "track-sort-request" and sort_request:
            field = str(sort_request.get("field") or "")
            if field:
                if sort.get("field") != field or not sort.get("direction"):
                    sort = {"field": field, "direction": "asc"}
                elif sort.get("direction") == "asc":
                    sort = {"field": field, "direction": "desc"}
                else:
                    sort = {}
                rows = sort_rows(rows, sort)
        visible = list(visible_fields or [])
        updated_selected = next(
            (
                index
                for index, row in enumerate(rows)
                if row.get("_source_order") == selected_order
            ),
            0 if rows else None,
        )
        return (
            sort,
            visible,
            rows,
            render_track_table(html, rows, has_more, collection, visible, sort),
            updated_selected,
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
        dimensions = row.get("dimensions") or {}
        dimension_fields = []
        for dimension, options in DIMENSION_VALUES.items():
            selected_values = set(dimensions.get(dimension) or [])
            dimension_fields.append(
                html.Div(
                    [
                        html.Span(dimension.title()),
                        html.Div(
                            [
                                html.Span(
                                    "★" * int(value) if dimension == "rating" else value,
                                    className=(
                                        "dimension-tag editable selected"
                                        if value in selected_values
                                        else "dimension-tag editable"
                                    ),
                                    **{
                                        "data-detail-dimension": dimension,
                                        "data-detail-value": value,
                                    },
                                )
                                for value in options
                            ],
                            className="dimension-tags",
                        ),
                    ],
                    className="detail-field detail-dimension",
                )
            )
        return [
            *(
                [
                    html.Img(
                        src=row["album_art_url"],
                        alt=f"{row.get('album') or row.get('title') or 'Album'} cover",
                        className="selected-album-art",
                    )
                ]
                if row.get("album_art_url")
                else []
            ),
            html.Div("Selected track", className="detail-eyebrow"),
            html.H2(row.get("title") or "—", className="detail-title"),
            html.Div(row.get("artist") or "—", className="detail-artist"),
            *dimension_fields,
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
        Input("track-collection", "data"),
    )
    def show_actions(
        selected: int | None,
        rows: list[dict[str, Any]] | None,
        focus: str,
        mode: str | None,
        action_selected: int,
        collection: dict[str, str] | None,
    ):
        rows = rows or []
        if selected is None or not 0 <= selected < len(rows):
            return html.Div("Select a track first", className="detail-empty")

        if mode is None:
            options = [
                ("add", "Add to playlist"),
                ("remove", "Remove from playlist"),
            ]
            if (collection or {}).get("type") == "playlist":
                options.append(("move", "Move to playlist"))
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
        if mode == "add":
            playlists = tidal_indexed_playlists()
            heading = "Choose a playlist to add to"
        elif mode == "move":
            source_id = str((collection or {}).get("id") or "")
            playlists = [
                playlist for playlist in tidal_indexed_playlists()
                if str(playlist.get("id")) != source_id
            ]
            heading = "Choose a destination playlist"
        else:
            playlists = tidal_playlists_for_track(track.get("id", ""))
            heading = "Choose a playlist to remove from"
        if not playlists:
            empty = (
                "No other indexed playlists"
                if mode == "move"
                else "No indexed playlists"
                if mode == "add"
                else "Track is not in an indexed playlist"
            )
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
        Output("liked-table", "children", allow_duplicate=True),
        Output("liked-focus", "data"),
        Output("liked-action-mode", "data"),
        Output("liked-action-selected", "data"),
        Output("liked-selected", "data", allow_duplicate=True),
        Input("liked-action-request", "data"),
        State("liked-rows", "data"),
        State("liked-selected", "data"),
        State("liked-has-more", "data"),
        State("track-collection", "data"),
        State("liked-action-selected", "data"),
        State("track-visible-fields", "data"),
        State("track-sort", "data"),
        prevent_initial_call=True,
    )
    def execute_action(
        request: dict[str, Any] | None,
        rows: list[dict[str, Any]] | None,
        selected: int | None,
        has_more: bool,
        collection: dict[str, Any] | None,
        current_action_selected: int,
        visible_fields: list[str] | None,
        sort: dict[str, str] | None,
    ):
        rows = rows or []
        render_rows = lambda current: render_track_table(
            html, current, has_more, collection, visible_fields, sort
        )
        if not request or selected is None or not 0 <= selected < len(rows):
            return "", rows, render_rows(rows), "tracks", None, 0, selected
        action = request.get("action")
        playlist_id = str(request.get("playlist_id") or "")
        track_id = str(rows[selected].get("id") or "")
        if action in DIMENSION_VALUES:
            value = str(request.get("value") or "")
            from_details = request.get("source") == "details"
            if value not in DIMENSION_VALUES[action] or not track_id:
                return "Invalid dimension value.", rows, render_rows(rows), "tracks" if from_details else "actions", None if from_details else action, current_action_selected, selected
            try:
                values = toggle_tidal_track_dimension(
                    track_id,
                    action,
                    value,
                    multiple=action in MULTI_VALUE_DIMENSIONS,
                )
                updated_rows = [dict(row) for row in rows]
                updated_dimensions = dict(updated_rows[selected].get("dimensions") or {})
                updated_dimensions[action] = values
                updated_rows[selected]["dimensions"] = updated_dimensions
                return (
                    "" if from_details else f"Updated {action}.",
                    updated_rows,
                    render_rows(updated_rows),
                    "tracks" if from_details else "actions",
                    None if from_details else action,
                    current_action_selected,
                    selected,
                )
            except Exception as exc:
                engine.LOGGER.exception(
                    "ui.liked_tracks dimension_failed dimension=%s track_id=%s",
                    action,
                    track_id,
                )
                return (
                    f"Action failed: {exc}", rows,
                    render_rows(rows),
                    "tracks" if from_details else "actions",
                    None if from_details else action,
                    current_action_selected,
                    selected,
                )
        if action not in {"add", "remove", "move"} or not playlist_id or not track_id:
            return "Invalid playlist action.", rows, render_rows(rows), "actions", action, 0, selected

        try:
            session = engine.tidal_client(interactive=False)
            playlist = engine._call(
                "tidal",
                "get_writable_playlist",
                lambda: session.playlist(playlist_id),
                playlist_id=playlist_id,
            )
            required_method = "add" if action in {"add", "move"} else "remove_by_id"
            if not hasattr(playlist, required_method):
                raise RuntimeError("That playlist is not writable by the connected TIDAL account")
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
            elif action == "remove":
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
            else:
                source_id = str((collection or {}).get("id") or "")
                if (collection or {}).get("type") != "playlist" or not source_id:
                    raise RuntimeError("Move is only available while viewing an indexed playlist")
                added_items = engine._call(
                    "tidal",
                    "playlist_move_add_destination",
                    lambda: playlist.add([track_id], allow_duplicates=False),
                    playlist_id=playlist_id,
                    track_id=track_id,
                )
                try:
                    source_playlist = engine._call(
                        "tidal",
                        "get_move_source_playlist",
                        lambda: session.playlist(source_id),
                        playlist_id=source_id,
                    )
                    if not hasattr(source_playlist, "remove_by_id"):
                        raise RuntimeError("The source playlist is not writable by the connected TIDAL account")
                    removed = engine._call(
                        "tidal",
                        "playlist_move_remove_source",
                        lambda: source_playlist.remove_by_id(track_id),
                        playlist_id=source_id,
                        track_id=track_id,
                    )
                    if not removed:
                        raise RuntimeError("TIDAL did not find that track in the source playlist")
                except Exception:
                    if added_items:
                        try:
                            engine._call(
                                "tidal",
                                "playlist_move_rollback_destination",
                                lambda: playlist.remove_by_id(track_id),
                                playlist_id=playlist_id,
                                track_id=track_id,
                            )
                        except Exception:
                            engine.LOGGER.exception(
                                "ui.liked_tracks move_rollback_failed track_id=%s playlist_id=%s",
                                track_id,
                                playlist_id,
                            )
                    raise
                add_tidal_playlist_membership(playlist_id, track_id)
                remove_tidal_playlist_membership(source_id, track_id)
                message = f"Moved to {playlist.name}."

            updated_rows = [dict(row) for row in rows]
            memberships = tidal_playlists_for_track(track_id)
            updated_rows[selected]["playlists"] = memberships
            updated_selection = selected
            viewing_modified_playlist = (
                (collection or {}).get("type") == "playlist"
                and (
                    str((collection or {}).get("id")) == playlist_id
                    or action == "move"
                )
            )
            current_playlist_id = str((collection or {}).get("id") or "")
            still_in_playlist = any(
                str(item.get("id")) == current_playlist_id for item in memberships
            )
            if action in {"remove", "move"} and viewing_modified_playlist and not still_in_playlist:
                updated_rows.pop(selected)
                updated_selection = min(selected, len(updated_rows) - 1) if updated_rows else None
            engine.LOGGER.info(
                "ui.liked_tracks action_ok action=%s track_id=%s playlist_id=%s",
                action,
                track_id,
                playlist_id,
            )
            return (
                message,
                updated_rows,
                render_rows(updated_rows),
                "tracks",
                None,
                0,
                updated_selection,
            )
        except Exception as exc:
            engine.LOGGER.exception(
                "ui.liked_tracks action_failed action=%s track_id=%s playlist_id=%s",
                action,
                track_id,
                playlist_id,
            )
            return (
                f"Action failed: {exc}",
                rows,
                render_rows(rows),
                "actions",
                action,
                0,
                selected,
            )

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
                document.querySelectorAll('[data-sidebar-index]').forEach(function(item) {
                    item.classList.toggle(
                        'keyboard-selected',
                        window.__likedTracksFocus === 'sidebar' &&
                        Number(item.dataset.sidebarIndex) === window.__likedSidebarSelected
                    );
                });
            }

            function isTrackBrowserMounted() {
                return Boolean(document.querySelector('[data-track-browser-root="true"]'));
            }

            if (!window.__likedTracksNavigationInstalled) {
                window.__likedTracksNavigationInstalled = true;
                document.addEventListener('click', function(event) {
                    var header = event.target.closest('[data-track-sort-key]');
                    if (!header || !isTrackBrowserMounted()) return;
                    window.dash_clientside.set_props('track-sort-request', {
                        data: {
                            token: Date.now(),
                            field: header.dataset.trackSortKey
                        }
                    });
                });
                document.addEventListener('click', function(event) {
                    var row = event.target.closest('[data-liked-index]');
                    if (!row || !isTrackBrowserMounted()) return;
                    window.dash_clientside.set_props('liked-selected', {
                        data: Number(row.dataset.likedIndex)
                    });
                    window.dash_clientside.set_props('liked-focus', {data: 'tracks'});
                });
                document.addEventListener('click', function(event) {
                    var option = event.target.closest('[data-action-option]');
                    if (!option || !isTrackBrowserMounted()) return;
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
                    } else if (option.dataset.actionValue && window.__likedActionMode) {
                        window.dash_clientside.set_props('liked-action-request', {
                            data: {
                                token: Date.now(),
                                action: window.__likedActionMode,
                                value: option.dataset.actionValue
                            }
                        });
                    }
                });
                document.addEventListener('click', function(event) {
                    var option = event.target.closest('[data-detail-dimension]');
                    if (!option || !isTrackBrowserMounted()) return;
                    window.dash_clientside.set_props('liked-action-request', {
                        data: {
                            token: Date.now(),
                            action: option.dataset.detailDimension,
                            value: option.dataset.detailValue,
                            source: 'details'
                        }
                    });
                });
                document.addEventListener('keydown', function(event) {
                    if (!isTrackBrowserMounted()) return;
                    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
                    if (window.__likedTracksFocus === 'sidebar') {
                        var navItems = Array.from(
                            document.querySelectorAll('[data-sidebar-index]')
                        ).filter(function(item) { return item.offsetParent !== null; });
                        if (!navItems.length) return;
                        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                            event.preventDefault();
                            var navDelta = event.key === 'ArrowDown' ? 1 : -1;
                            var currentNavPosition = navItems.findIndex(function(item) {
                                return Number(item.dataset.sidebarIndex) === window.__likedSidebarSelected;
                            });
                            if (currentNavPosition < 0) currentNavPosition = 0;
                            var nextNavPosition = Math.max(
                                0,
                                Math.min(navItems.length - 1, currentNavPosition + navDelta)
                            );
                            window.__likedSidebarSelected = Number(
                                navItems[nextNavPosition].dataset.sidebarIndex
                            );
                            paintSelection();
                            navItems[nextNavPosition].scrollIntoView({block: 'nearest'});
                            return;
                        }
                        if (event.key === 'ArrowRight' || event.key === 'Enter') {
                            event.preventDefault();
                            var navItem = navItems.find(function(item) {
                                return Number(item.dataset.sidebarIndex) === window.__likedSidebarSelected;
                            }) || navItems[0];
                            if (navItem.dataset.sidebarToggle) {
                                var group = navItem.closest('details');
                                if (group) group.open = !group.open;
                                window.setTimeout(paintSelection, 0);
                                return;
                            }
                            var href = navItem && navItem.dataset.sidebarHref;
                            if (!href) return;
                            if (window.location.pathname === href) {
                                window.dash_clientside.set_props('liked-focus', {data: 'tracks'});
                            } else {
                                window.location.assign(href);
                            }
                        }
                        return;
                    }
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
                            if (!playlistOption) return;
                            event.preventDefault();
                            var request = {
                                token: Date.now(),
                                action: window.__likedActionMode
                            };
                            if (playlistOption.dataset.playlistId) {
                                request.playlist_id = playlistOption.dataset.playlistId;
                            } else if (playlistOption.dataset.actionValue) {
                                request.value = playlistOption.dataset.actionValue;
                            } else {
                                return;
                            }
                            window.dash_clientside.set_props('liked-action-request', {data: request});
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
                    if (event.key === 'ArrowLeft') {
                        event.preventDefault();
                        var activeNav = document.querySelector('[data-sidebar-index].active');
                        window.__likedSidebarSelected = activeNav
                            ? Number(activeNav.dataset.sidebarIndex) : 0;
                        window.dash_clientside.set_props('liked-focus', {data: 'sidebar'});
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
        Output("track-browser-keyboard-ready", "children"),
        Input("liked-selected", "data"),
        Input("liked-rows", "data"),
        Input("liked-has-more", "data"),
        Input("liked-focus", "data"),
        Input("liked-action-mode", "data"),
        Input("liked-action-selected", "data"),
        Input("liked-actions", "children"),
    )
