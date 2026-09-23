"""Dash presentation for the TIDAL liked-tracks browser."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from music_library.dimensions import DIMENSION_MAX_VALUES, DIMENSION_VALUES
from music_library.database import (
    associate_tidal_tracks_with_watched_mix,
    add_tidal_playlist_membership,
    replace_tidal_track_dimensions,
    remove_tidal_playlist_membership,
    tidal_dimensions_for_tracks,
    tidal_artists_for_tracks,
    tidal_indexed_playlists,
    tidal_playlists_for_track,
    tidal_playlists_for_tracks,
    tidal_setlists_for_tracks,
    tidal_watched_mixes_for_tracks,
    toggle_tidal_track_dimension,
    watched_mixes,
)
from music_tools.auto_tagging import auto_tag_tracks
from music_tools.track_browser.table import (
    columns_for,
    default_visible_fields,
    render_track_table,
    sort_rows,
)
from music_tools.track_browser.stopwatch import content as stopwatch_content

from .service import (
    collection_artist_summary,
    fetch_artist_tracks,
    fetch_indexed_playlist_tracks,
    fetch_indexed_setlist_tracks,
    fetch_library_tracks,
    fetch_liked_tracks,
    fetch_watched_mix_tracks,
)


def _collection_state_key(collection: dict[str, Any] | None) -> str:
    collection = collection or {"type": "liked"}
    return f"{collection.get('type', 'liked')}:{collection.get('id', '')}"


def _tidal_track_uri(track_id: Any) -> str:
    return f"tidal://track/{quote(str(track_id or ''), safe='')}"


def _attach_memberships(
    rows: list[dict[str, Any]],
    playlist_memberships: dict[str, list[dict[str, str]]],
    setlist_memberships: dict[str, list[dict[str, str]]],
    watched_mix_memberships: dict[str, list[dict[str, str]]],
    collection: dict[str, Any] | None = None,
) -> None:
    """Split reverse memberships into their dedicated table/inspector fields."""
    current_type = str((collection or {}).get("type") or "")
    current_id = str((collection or {}).get("id") or "")
    for row in rows:
        track_id = str(row.get("id") or "")
        grouped = {"playlist": [], "event": [], "source": []}
        for membership in playlist_memberships.get(track_id, []):
            if current_type == "playlist" and str(membership.get("id") or "") == current_id:
                continue
            kind = str(membership.get("collection_type") or "playlist")
            grouped.setdefault(kind, []).append(membership)
        row["playlists"] = grouped["playlist"]
        row["events"] = grouped["event"]
        row["sources"] = grouped["source"]
        row["mixes"] = [
            membership
            for membership in setlist_memberships.get(track_id, [])
            if not (
                current_type == "setlist"
                and str(membership.get("id") or "") == current_id
            )
        ]
        row["djmi"] = [
            membership
            for membership in watched_mix_memberships.get(track_id, [])
            if not (
                current_type == "watched_mix"
                and str(membership.get("id") or "") == current_id
            )
        ]


def content(
    html: Any,
    dcc: Any,
    collection: dict[str, Any] | None = None,
    quick_views: list[dict[str, Any]] | None = None,
    view_state: dict[str, Any] | None = None,
):
    collection = collection or {"type": "liked", "name": "TIDAL liked tracks"}
    is_liked = collection.get("type") == "liked"
    is_playlist = collection.get("type") == "playlist"
    is_setlist = collection.get("type") == "setlist"
    is_search = collection.get("type") == "search"
    available_columns = columns_for(collection)
    available_keys = {key for key, _label in available_columns}
    default_quick_view = next(
        (view for view in (quick_views or []) if view.get("default")), None
    )
    default_fields = (
        [
            field for field in default_quick_view.get("fields") or []
            if field in available_keys
        ]
        if default_quick_view
        else default_visible_fields(collection)
    )
    remembered_fields = (view_state or {}).get("visible_fields")
    visible_fields = (
        [field for field in remembered_fields if field in available_keys]
        if isinstance(remembered_fields, list)
        else default_fields
    )
    remembered_sort = dict((view_state or {}).get("sort") or {})
    initial_sort = (
        remembered_sort
        if remembered_sort.get("field") in available_keys
        and remembered_sort.get("direction") in {"asc", "desc"}
        else {}
    )
    collection_key = _collection_state_key(collection)
    restore_state = dict(
        ((view_state or {}).get("collections") or {}).get(collection_key) or {}
    )
    return [
        stopwatch_content(html) if is_setlist else None,
        html.Div(
            [
                html.Div(
                    [
                        html.H1(collection.get("name") or "TIDAL playlist"),
                        html.P(
                            "Your liked TIDAL tracks, newest first."
                            if is_liked
                            else "All locally indexed tracks credited to this artist."
                            if collection.get("type") == "artist"
                            else "Tracks associated with this watched mix."
                            if collection.get("type") == "watched_mix"
                            else "Search liked tracks, playlists, events, sources, and My Mixes."
                            if is_search
                            else "Tracks from the local TIDAL playlist index."
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Button(
                            "Refresh from TIDAL"
                            if is_liked or is_playlist
                            else "Reload SQLite",
                            id="liked-refresh",
                            className="primary",
                        ),
                        html.Div(
                            [
                                html.Button(
                                    str(view.get("name") or "Quick View"),
                                    id={
                                        "type": "quick-view-button",
                                        "id": str(view.get("id") or index),
                                    },
                                    className=(
                                        "quick-view-button default"
                                        if view.get("default")
                                        else "quick-view-button"
                                    ),
                                    title=(
                                        "Default Quick View"
                                        if view.get("default")
                                        else None
                                    ),
                                )
                                for index, view in enumerate(quick_views or [])
                            ],
                            id="quick-view-buttons",
                            className="quick-view-buttons",
                        ),
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
                                        persistence=not bool(default_quick_view),
                                        persistence_type="local",
                                        persisted_props=["value"],
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
        html.Div(id="track-top-artists", className="top-artists"),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Search" if is_search else "Track"),
                        dcc.Input(
                            id="track-filter-title",
                            type="search",
                            debounce=0.35,
                            persistence=True,
                            persistence_type="local",
                            placeholder=(
                                "Title, artist, remix, or album"
                                if is_search else "Title or remix"
                            ),
                        ),
                    ],
                    className="quick-filter quick-filter-title",
                ),
                html.Div(
                    [
                        html.Label("Artist"),
                        dcc.Dropdown(
                            id="track-filter-artists", multi=True, options=[],
                            persistence=True, persistence_type="local",
                            placeholder="Any artist",
                        ),
                    ],
                    className="quick-filter quick-filter-artist",
                ),
                html.Div(
                    [
                        html.Label("Key"),
                        dcc.Dropdown(
                            id="track-filter-keys",
                            multi=True,
                            options=[
                                {"label": f"{number:02d}{mode}", "value": f"{number:02d}{mode}"}
                                for number in range(1, 13) for mode in ("A", "B")
                            ],
                            persistence=True,
                            persistence_type="local",
                            placeholder="Any key",
                        ),
                    ],
                    className="quick-filter",
                ),
                html.Div(
                    [
                        html.Label("BPM"),
                        html.Div(
                            [
                                dcc.Input(
                                    id="track-filter-bpm-min", type="number", placeholder="Min",
                                    persistence=True, persistence_type="local",
                                ),
                                dcc.Input(
                                    id="track-filter-bpm-max", type="number", placeholder="Max",
                                    persistence=True, persistence_type="local",
                                ),
                            ],
                            className="bpm-filter-inputs",
                        ),
                    ],
                    className="quick-filter",
                ),
                html.Div(
                    [
                        html.Label("Rating"),
                        dcc.Dropdown(
                            id="track-filter-ratings", multi=True,
                            options=[{"label": "★" * value, "value": str(value)} for value in range(1, 6)],
                            persistence=True, persistence_type="local",
                            placeholder="Any rating",
                        ),
                    ],
                    className="quick-filter",
                ),
                html.Div(
                    [
                        html.Label("Energy"),
                        dcc.Dropdown(
                            id="track-filter-energy", multi=True,
                            options=[{"label": str(value), "value": str(value)} for value in range(1, 6)],
                            persistence=True, persistence_type="local",
                            placeholder="Any energy",
                        ),
                    ],
                    className="quick-filter",
                ),
                html.Div(
                    [
                        html.Label("Tags"),
                        dcc.Dropdown(
                            id="track-filter-tags", multi=True,
                            options=[
                                {
                                    "label": f"{dimension.title()}: {value}",
                                    "value": f"{dimension}:{value}",
                                }
                                for dimension, values in DIMENSION_VALUES.items()
                                if dimension not in {"rating", "energy"}
                                for value in values
                            ],
                            persistence=True, persistence_type="local",
                            placeholder="Any tag",
                        ),
                    ],
                    className="quick-filter quick-filter-tags",
                ),
                html.Button("Clear filters", id="track-filter-clear"),
            ],
            className="track-quick-filters",
        ),
        dcc.Interval(id="liked-initial-load", interval=250, max_intervals=1, n_intervals=0),
        dcc.Store(id="liked-rows", data=[]),
        dcc.Store(id="liked-selected", data=None),
        dcc.Store(id="liked-selected-indices", data=[]),
        dcc.Store(id="liked-has-more", data=True),
        dcc.Store(id="liked-load-next", data=0),
        dcc.Store(id="liked-focus", data="tracks"),
        dcc.Store(id="liked-action-mode", data=None),
        dcc.Store(id="liked-action-selected", data=0),
        dcc.Store(id="liked-action-request", data=None),
        dcc.Store(id="track-sort", data=initial_sort),
        dcc.Store(id="track-sort-request", data=None),
        dcc.Store(id="track-visible-fields", data=visible_fields),
        dcc.Store(id="track-collection", data=collection),
        dcc.Store(id="track-view-restore", data=restore_state),
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
    app: Any, callback: Any, Input: Any, Output: Any, State: Any, ALL: Any,
    html: Any, ctx: Any, engine: Any
) -> None:
    @callback(
        Output("track-visible-fields-control", "value"),
        Input({"type": "quick-view-button", "id": ALL}, "n_clicks"),
        State("quick-views", "data"),
        State("track-collection", "data"),
        State("track-visible-fields-control", "value"),
        prevent_initial_call=True,
    )
    def apply_quick_view(
        clicks, rows, collection, current_fields
    ):
        views = rows or []
        if not isinstance(ctx.triggered_id, dict) or not any(clicks or []):
            return current_fields or default_visible_fields(collection)
        selected_id = str(ctx.triggered_id.get("id") or "")
        selected = next(
            (row for row in views if str(row.get("id") or "") == selected_id), None
        )
        if selected is None:
            return current_fields or default_visible_fields(collection)
        available = {key for key, _label in columns_for(collection)}
        return [field for field in selected.get("fields") or [] if field in available]

    @callback(
        Output("track-view-state", "data"),
        Input("track-sort", "data"),
        Input("track-visible-fields", "data"),
        Input("liked-rows", "data"),
        Input("liked-selected", "data"),
        Input("track-collection", "data"),
        State("track-view-state", "data"),
        prevent_initial_call=True,
    )
    def persist_track_view(
        sort, visible_fields, rows, selected, collection, current_state
    ):
        state = dict(current_state or {})
        if not collection:
            return state
        available = {key for key, _label in columns_for(collection)}
        remembered_sort = dict(state.get("sort") or {})
        if (
            (sort or {}).get("field") in available
            or remembered_sort.get("field") in available
            or not remembered_sort.get("field")
        ):
            state["sort"] = dict(sort or {})
        if isinstance(visible_fields, list):
            unavailable_remembered = [
                field for field in (state.get("visible_fields") or [])
                if field not in available
            ]
            state["visible_fields"] = [
                *unavailable_remembered,
                *[field for field in visible_fields if field in available],
            ]
        rows = rows or []
        collections = {
            str(key): dict(value or {})
            for key, value in (state.get("collections") or {}).items()
        }
        key = _collection_state_key(collection)
        saved = dict(collections.get(key) or {})
        if rows:
            saved["loaded_count"] = len(rows)
            if selected is not None and 0 <= int(selected) < len(rows):
                saved["selected_track_id"] = str(rows[int(selected)].get("id") or "")
            collections[key] = saved
            state["collections"] = collections
        else:
            state.setdefault("collections", collections)
        return state

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
        Output("liked-selected-indices", "data"),
        Output("liked-has-more", "data"),
        Output("track-top-artists", "children"),
        Output("track-filter-artists", "options"),
        Input("liked-initial-load", "n_intervals"),
        Input("liked-refresh", "n_clicks"),
        Input("liked-load-next", "data"),
        Input("track-filter-title", "value"),
        Input("track-filter-artists", "value"),
        Input("track-filter-keys", "value"),
        Input("track-filter-bpm-min", "value"),
        Input("track-filter-bpm-max", "value"),
        Input("track-filter-ratings", "value"),
        Input("track-filter-energy", "value"),
        Input("track-filter-tags", "value"),
        Input("track-sort", "data"),
        State("liked-rows", "data"),
        State("liked-selected", "data"),
        State("track-collection", "data"),
        State("track-visible-fields", "data"),
        State("track-view-restore", "data"),
        prevent_initial_call=True,
    )
    def load_tracks(
        _initial: int,
        _refresh: int | None,
        _load_next: int,
        filter_title: str | None,
        filter_artists: list[str] | None,
        filter_keys: list[str] | None,
        bpm_min: float | None,
        bpm_max: float | None,
        filter_ratings: list[str] | None,
        filter_energy: list[str] | None,
        filter_tags: list[str] | None,
        sort: dict[str, str] | None,
        existing_rows: list[dict[str, str]] | None,
        current_selection: int | None,
        collection: dict[str, Any] | None,
        visible_fields: list[str] | None,
        restore_state: dict[str, Any] | None,
    ):
        existing_rows = existing_rows or []
        append = ctx.triggered_id == "liked-load-next" and bool(existing_rows)
        offset = len(existing_rows) if append else 0
        selected_track_id = ""
        if current_selection is not None and 0 <= current_selection < len(existing_rows):
            selected_track_id = str(existing_rows[current_selection].get("id") or "")
        if not selected_track_id and ctx.triggered_id == "liked-initial-load":
            selected_track_id = str(
                (restore_state or {}).get("selected_track_id") or ""
            )
        page_limit = 30
        if ctx.triggered_id == "liked-initial-load" and not append:
            try:
                page_limit = max(
                    30, min(1000, int((restore_state or {}).get("loaded_count") or 30))
                )
            except (TypeError, ValueError):
                page_limit = 30
        filters = {
            "title": filter_title or "",
            "artists": filter_artists or [],
            "keys": filter_keys or [],
            "bpm_min": bpm_min,
            "bpm_max": bpm_max,
            "ratings": filter_ratings or [],
            "energy": filter_energy or [],
            "tags": filter_tags or [],
        }
        active_filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
        refresh_note = ""
        try:
            if (
                (collection or {}).get("type", "liked") == "liked"
                and ctx.triggered_id in {"liked-initial-load", "liked-refresh"}
            ):
                try:
                    session = engine.tidal_client(interactive=False)
                    refresh_result = engine.maintain_tidal_liked_tracks(
                        session,
                        engine.load_config().get("settings", {}),
                    )
                    refresh_note = (
                        f" TIDAL refreshed: {refresh_result['fetched']:,} checked, "
                        f"{refresh_result['added']:,} new."
                    )
                except Exception as exc:
                    engine.LOGGER.exception("ui.liked_tracks tidal_refresh_failed")
                    refresh_note = f" TIDAL refresh failed; showing cache: {exc}"
            elif (
                (collection or {}).get("type") == "playlist"
                and ctx.triggered_id in {"liked-initial-load", "liked-refresh"}
            ):
                try:
                    refresh_result = engine.refresh_tidal_playlist_cache(
                        (collection or {}).get("id", ""),
                        force=ctx.triggered_id == "liked-refresh",
                    )
                    refresh_note = (
                        f" TIDAL refreshed: {refresh_result['tracks']:,} tracks."
                        if refresh_result["changed"]
                        else " TIDAL checked: playlist unchanged."
                    )
                except Exception as exc:
                    engine.LOGGER.exception("ui.playlist tidal_refresh_failed")
                    refresh_note = f" TIDAL refresh failed; showing cache: {exc}"
            if (collection or {}).get("type") == "setlist":
                page, has_more = fetch_indexed_setlist_tracks(
                    (collection or {}).get("id", ""), limit=page_limit, offset=offset,
                    filters=active_filters, sort=sort,
                )
            elif (collection or {}).get("type") == "watched_mix":
                page, has_more = fetch_watched_mix_tracks(
                    (collection or {}).get("id", ""), limit=page_limit, offset=offset,
                    filters=active_filters, sort=sort,
                )
            elif (collection or {}).get("type") == "playlist":
                page, has_more = fetch_indexed_playlist_tracks(
                    (collection or {}).get("id", ""), limit=page_limit, offset=offset,
                    filters=active_filters, sort=sort,
                )
            elif (collection or {}).get("type") == "artist":
                page, has_more = fetch_artist_tracks(
                    (collection or {}).get("id", ""), limit=page_limit, offset=offset,
                    filters=active_filters, sort=sort,
                )
            elif (collection or {}).get("type") == "search":
                page, has_more = fetch_library_tracks(
                    limit=page_limit, offset=offset,
                    filters=active_filters, sort=sort,
                )
            else:
                page, has_more = fetch_liked_tracks(
                    engine,
                    limit=page_limit,
                    offset=offset,
                    force_refresh=ctx.triggered_id == "liked-refresh",
                    filters=active_filters,
                    sort=sort,
                )
            top_artists, artist_options, collection_stats = collection_artist_summary(
                engine, collection or {}
            )
        except Exception as exc:
            engine.LOGGER.exception("ui.liked_tracks load_failed")
            return html.Div(), f"Could not load liked tracks: {exc}", [], None, [], False, [], []

        track_ids = [row.get("id", "") for row in page]
        memberships = tidal_playlists_for_tracks(track_ids)
        setlists = tidal_setlists_for_tracks(track_ids)
        watched_mix_memberships = tidal_watched_mixes_for_tracks(track_ids)
        dimensions = tidal_dimensions_for_tracks(track_ids)
        artists = tidal_artists_for_tracks(track_ids)
        _attach_memberships(
            page, memberships, setlists, watched_mix_memberships, collection
        )
        for index, row in enumerate(page):
            row["dimensions"] = dimensions.get(row.get("id", ""), {})
            row["artists"] = artists.get(row.get("id", ""), [])
            row["_source_order"] = offset + index
        rows = sort_rows(existing_rows + page if append else page, sort)

        table = render_track_table(
            html, rows, has_more, collection, visible_fields, sort
        )
        selected = next(
            (
                index for index, row in enumerate(rows)
                if str(row.get("id") or "") == selected_track_id
            ),
            0 if rows else None,
        )
        status = (
            f"{len(rows):,} track{'s' if len(rows) != 1 else ''} loaded from SQLite.{refresh_note}"
            if rows
            else (
                "No tracks match the current filters."
                if active_filters
                else (
                    f"No liked tracks cached. Run cache_liked_tracks.py first.{refresh_note}"
                    if (collection or {}).get("type", "liked") == "liked"
                    else "No tracks cached for this collection."
                )
            )
        )
        return (
            table,
            status,
            rows,
            selected,
            [selected] if selected is not None else [],
            has_more,
            [
                html.A(
                    [html.Strong(artist["name"]), html.Span(f" {artist['count']} tracks")],
                    href=f"/artists/{quote(str(artist['id']), safe='')}",
                    className="top-artist",
                )
                for artist in top_artists
            ]
            + (
                [
                    html.Span(
                        [
                            html.Strong("BPM"),
                            html.Span(
                                f" {collection_stats['bpm_min']:g}–{collection_stats['bpm_max']:g}"
                            ),
                        ],
                        className="collection-stat bpm-stat",
                    )
                ]
                if collection_stats.get("bpm_min") is not None
                else []
            )
            + (
                [
                    html.Span(
                        [
                            html.Strong("Top vibe"),
                            html.Span(
                                f" {collection_stats['vibe']} · {collection_stats['vibe_count']} tracks"
                            ),
                        ],
                        className="collection-stat vibe-stat",
                    )
                ]
                if collection_stats.get("vibe")
                else []
            ),
            artist_options,
        )

    @callback(
        Output("track-filter-title", "value"),
        Output("track-filter-artists", "value"),
        Output("track-filter-keys", "value"),
        Output("track-filter-bpm-min", "value"),
        Output("track-filter-bpm-max", "value"),
        Output("track-filter-ratings", "value"),
        Output("track-filter-energy", "value"),
        Output("track-filter-tags", "value"),
        Input("track-filter-clear", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_filters(_clicks: int):
        return "", [], [], None, None, [], [], []

    @callback(
        Output("track-sort", "data"),
        Output("track-visible-fields", "data"),
        Output("liked-rows", "data", allow_duplicate=True),
        Output("liked-table", "children", allow_duplicate=True),
        Output("liked-selected", "data", allow_duplicate=True),
        Output("liked-selected-indices", "data", allow_duplicate=True),
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
            [updated_selected] if updated_selected is not None else [],
        )

    @callback(
        Output("liked-details", "children"),
        Input("liked-selected", "data"),
        Input("liked-selected-indices", "data"),
        Input("liked-rows", "data"),
        Input("ui-preferences", "data"),
    )
    def show_details(
        selected: int | None,
        selected_indices: list[int] | None,
        rows: list[dict[str, str]] | None,
        ui_preferences: dict[str, Any] | None,
    ):
        rows = rows or []
        if selected is None or not 0 <= selected < len(rows):
            return html.Div("Select a track", className="detail-empty")
        row = rows[selected]
        membership_blobs = []
        for key, label, route_prefix in (
            ("playlists", "Playlist", "/playlists/"),
            ("events", "Event", "/events/"),
            ("sources", "Source", "/sources/"),
            ("mixes", "Mix", "/mixes/"),
            ("djmi", "Dj Mix", "/watched-mixes/"),
        ):
            for item in row.get(key) or []:
                item_id = str(item.get("id") or "")
                name = str(item.get("name") or item_id)
                membership_blobs.append(
                    html.A(
                        name,
                        href=route_prefix + quote(item_id, safe=""),
                        className=f"playlist-tag membership-link membership-{key}",
                        title=f"{label}: {name}",
                    )
                )
        dimensions = row.get("dimensions") or {}
        dimension_fields = []
        for dimension, options in DIMENSION_VALUES.items():
            selected_order = dimensions.get(dimension) or []
            selected_values = set(selected_order)
            dimension_fields.append(
                html.Div(
                    [
                        html.Span(dimension.title()),
                        html.Div(
                            [
                                html.Span(
                                    "★" * int(value) if dimension == "rating" else value,
                                    className=(
                                        "dimension-tag editable selected primary"
                                        if value in selected_values
                                        and dimension in {"driver", "scale"}
                                        and selected_order.index(value) == 0
                                        else "dimension-tag editable selected"
                                        if value in selected_values
                                        else "dimension-tag editable"
                                    ),
                                    title=(
                                        "Primary selection"
                                        if dimension in {"driver", "scale"}
                                        and selected_order
                                        and value == selected_order[0]
                                        else None
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
            html.Div(
                f"{len(selected_indices or [selected])} selected"
                if len(selected_indices or []) > 1
                else "Selected track",
                className="detail-eyebrow",
            ),
            html.H2(row.get("title") or "—", className="detail-title"),
            html.Div(row.get("artist") or "—", className="detail-artist"),
            (
                html.Div(
                    membership_blobs,
                    className="playlist-tags detail-membership-blobs",
                )
                if membership_blobs else None
            ),
            (
                html.A(
                    "Open in TIDAL",
                    href=_tidal_track_uri(row.get("id")),
                    className="tidal-app-link",
                    title="Open this track in the native TIDAL app",
                )
                if row.get("id") else None
            ),
            html.Details(
                [
                    html.Summary("Tags & ratings", className="detail-tags-summary"),
                    html.Div(dimension_fields, className="detail-tags-content"),
                ],
                open=not bool(
                    (ui_preferences or {}).get("tags_collapsed", True)
                ),
                className="detail-tags-panel",
                **{"data-tags-panel": "true"},
            ),
        ]

    @callback(
        Output("liked-actions", "children"),
        Input("liked-selected", "data"),
        Input("liked-selected-indices", "data"),
        Input("liked-rows", "data"),
        Input("liked-focus", "data"),
        Input("liked-action-mode", "data"),
        Input("liked-action-selected", "data"),
        Input("track-collection", "data"),
    )
    def show_actions(
        selected: int | None,
        selected_indices: list[int] | None,
        rows: list[dict[str, Any]] | None,
        focus: str,
        mode: str | None,
        action_selected: int,
        collection: dict[str, str] | None,
    ):
        rows = rows or []
        if selected is None or not 0 <= selected < len(rows):
            return html.Div("Select a track first", className="detail-empty")

        selection_count = len(selected_indices or [selected])
        if mode is None:
            options = [
                ("add", "Add to playlist"),
                ("remove", "Remove from playlist"),
            ]
            if (collection or {}).get("type") == "playlist":
                options.append(("move", "Move to playlist"))
            options.append(("associate_watched", "Associate with watched mix"))
            options.append(("auto_tag", "Auto tag with Qwen3"))
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
        if mode == "auto_tag":
            return [
                html.Div(
                    f"Qwen3 will classify {selection_count} selected track{'s' if selection_count != 1 else ''} using local metadata.",
                    className="action-prompt",
                ),
                html.Div(
                    "Run auto tagging",
                    className="action-option selected" if focus == "actions" else "action-option",
                    **{"data-action-option": "0", "data-action-value": "run"},
                ),
            ]
        if mode == "associate_watched":
            playlists = [
                {"id": item["video_id"], "name": item.get("title") or item["video_id"]}
                for item in watched_mixes()
            ]
            heading = f"Choose a watched mix for {selection_count} track{'s' if selection_count != 1 else ''}"
        elif mode == "add":
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
                else "No watched mixes saved"
                if mode == "associate_watched"
                else "Track is not in an indexed playlist"
            )
            return [html.Div(heading, className="action-prompt"), html.Div(empty, className="detail-empty")]

        def action_option(playlist: dict[str, Any], index: int):
            return html.Div(
                playlist.get("name") or playlist.get("id"),
                className="action-option selected"
                if focus == "actions" and index == action_selected
                else "action-option",
                title=playlist.get("id", ""),
                **{
                    "data-action-option": str(index),
                    (
                        "data-watched-mix-id"
                        if mode == "associate_watched"
                        else "data-playlist-id"
                    ): playlist.get("id", ""),
                },
            )

        if mode == "associate_watched":
            option_children = [
                action_option(playlist, index)
                for index, playlist in enumerate(playlists)
            ]
        else:
            option_children = []
            option_index = 0
            for collection_type, label in (
                ("playlist", "Playlists"),
                ("event", "Events"),
                ("source", "Sources"),
            ):
                group = [
                    playlist
                    for playlist in playlists
                    if str(playlist.get("collection_type") or "playlist").lower()
                    == collection_type
                ]
                if not group:
                    continue
                option_children.append(
                    html.Div(label, className="action-section-heading")
                )
                for playlist in group:
                    option_children.append(action_option(playlist, option_index))
                    option_index += 1
        return [
            html.Div(heading, className="action-prompt"),
            *option_children,
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
        State("liked-selected-indices", "data"),
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
        selected_indices: list[int] | None,
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
        selected_positions = sorted(
            {
                int(index)
                for index in (selected_indices or [selected])
                if isinstance(index, int) and 0 <= index < len(rows)
            }
        )
        if selected not in selected_positions:
            selected_positions = [selected]
        action = request.get("action")
        playlist_id = str(request.get("playlist_id") or "")
        track_id = str(rows[selected].get("id") or "")
        track_ids = [str(rows[index].get("id") or "") for index in selected_positions]
        track_ids = [value for value in dict.fromkeys(track_ids) if value]
        if action == "auto_tag":
            if request.get("value") != "run" or not track_ids:
                return "Invalid auto-tag action.", rows, render_rows(rows), "actions", action, 0, selected
            try:
                settings = engine.load_config().get("settings", {})
                selected_tracks = [rows[index] for index in selected_positions]
                suggestions = auto_tag_tracks(
                    selected_tracks,
                    model=str(settings.get("ollama_model", "qwen3:4b")),
                    base_url=str(settings.get("ollama_url", "http://127.0.0.1:11434")),
                    timeout_seconds=float(settings.get("ollama_timeout_seconds", 300)),
                )
                updated_rows = [dict(row) for row in rows]
                tagged_count = 0
                for index in selected_positions:
                    current_track_id = str(updated_rows[index].get("id") or "")
                    dimensions = suggestions.get(current_track_id)
                    if not dimensions:
                        continue
                    stored = replace_tidal_track_dimensions(
                        current_track_id, dimensions
                    )
                    updated_dimensions = dict(
                        updated_rows[index].get("dimensions") or {}
                    )
                    updated_dimensions.update(stored)
                    updated_rows[index]["dimensions"] = updated_dimensions
                    tagged_count += 1
                engine.LOGGER.info(
                    "ui.auto_tag complete model=%s requested=%d tagged=%d",
                    settings.get("ollama_model", "qwen3:4b"),
                    len(track_ids),
                    tagged_count,
                )
                return (
                    f"Qwen3 tagged {tagged_count}/{len(track_ids)} selected track{'s' if len(track_ids) != 1 else ''}.",
                    updated_rows,
                    render_rows(updated_rows),
                    "tracks",
                    None,
                    0,
                    selected,
                )
            except Exception as exc:
                engine.LOGGER.exception("ui.auto_tag failed tracks=%d", len(track_ids))
                return (
                    f"Auto tagging failed: {exc}", rows, render_rows(rows),
                    "actions", action, 0, selected,
                )
        if action == "associate_watched":
            video_id = str(request.get("watched_mix_id") or "")
            if not video_id or not track_ids:
                return "Invalid watched mix action.", rows, render_rows(rows), "actions", action, 0, selected
            try:
                added = associate_tidal_tracks_with_watched_mix(video_id, track_ids)
                updated_rows = [dict(row) for row in rows]
                watched_memberships = tidal_watched_mixes_for_tracks(track_ids)
                for index in selected_positions:
                    current_track_id = str(updated_rows[index].get("id") or "")
                    updated_rows[index]["djmi"] = watched_memberships.get(
                        current_track_id, []
                    )
                return (
                    f"Associated {added} new track{'s' if added != 1 else ''} with the watched mix.",
                    updated_rows, render_rows(updated_rows), "tracks", None, 0, selected,
                )
            except Exception as exc:
                engine.LOGGER.exception("ui.liked_tracks watched_mix_association_failed")
                return f"Action failed: {exc}", rows, render_rows(rows), "actions", action, 0, selected
        if action in DIMENSION_VALUES:
            value = str(request.get("value") or "")
            from_details = request.get("source") == "details"
            if value not in DIMENSION_VALUES[action] or not track_id:
                return "Invalid dimension value.", rows, render_rows(rows), "tracks" if from_details else "actions", None if from_details else action, current_action_selected, selected
            try:
                updated_rows = [dict(row) for row in rows]
                primary_values = set((rows[selected].get("dimensions") or {}).get(action) or [])
                enable = value not in primary_values
                for index in selected_positions:
                    current = set((rows[index].get("dimensions") or {}).get(action) or [])
                    should_toggle = (
                        (enable and value not in current)
                        or (not enable and value in current)
                    )
                    if not should_toggle:
                        continue
                    values = toggle_tidal_track_dimension(
                        str(rows[index].get("id") or ""),
                        action,
                        value,
                        multiple=DIMENSION_MAX_VALUES.get(action, 999) != 1,
                    )
                    updated_dimensions = dict(updated_rows[index].get("dimensions") or {})
                    updated_dimensions[action] = values
                    updated_rows[index]["dimensions"] = updated_dimensions
                return (
                    "" if from_details else f"Updated {action} on {len(selected_positions)} track{'s' if len(selected_positions) != 1 else ''}.",
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

        if len(selected_positions) > 1:
            try:
                session = engine.tidal_client(interactive=False)
                playlist = engine._call(
                    "tidal", "get_writable_playlist",
                    lambda: session.playlist(playlist_id), playlist_id=playlist_id,
                )
                required_method = "add" if action in {"add", "move"} else "remove_by_id"
                if not hasattr(playlist, required_method):
                    raise RuntimeError("That playlist is not writable by the connected TIDAL account")
                source_id = str((collection or {}).get("id") or "")
                source_playlist = None
                if action == "move":
                    if (collection or {}).get("type") != "playlist" or not source_id:
                        raise RuntimeError("Move is only available while viewing an indexed playlist")
                    source_playlist = engine._call(
                        "tidal", "get_move_source_playlist",
                        lambda: session.playlist(source_id), playlist_id=source_id,
                    )
                    if not hasattr(source_playlist, "remove_by_id"):
                        raise RuntimeError("The source playlist is not writable by the connected TIDAL account")
                for current_track_id in track_ids:
                    if action == "add":
                        engine._call(
                            "tidal", "playlist_add_bulk_selection",
                            lambda track_id=current_track_id: playlist.add([track_id], allow_duplicates=False),
                            playlist_id=playlist_id, track_id=current_track_id,
                        )
                        add_tidal_playlist_membership(playlist_id, current_track_id)
                    elif action == "remove":
                        removed = engine._call(
                            "tidal", "playlist_remove_bulk_selection",
                            lambda track_id=current_track_id: playlist.remove_by_id(track_id),
                            playlist_id=playlist_id, track_id=current_track_id,
                        )
                        if removed:
                            remove_tidal_playlist_membership(playlist_id, current_track_id)
                    else:
                        added_items = engine._call(
                            "tidal", "playlist_move_bulk_add",
                            lambda track_id=current_track_id: playlist.add([track_id], allow_duplicates=False),
                            playlist_id=playlist_id, track_id=current_track_id,
                        )
                        try:
                            removed = engine._call(
                                "tidal", "playlist_move_bulk_remove",
                                lambda track_id=current_track_id: source_playlist.remove_by_id(track_id),
                                playlist_id=source_id, track_id=current_track_id,
                            )
                            if not removed:
                                raise RuntimeError("TIDAL did not find a selected track in the source playlist")
                        except Exception:
                            if added_items:
                                playlist.remove_by_id(current_track_id)
                            raise
                        add_tidal_playlist_membership(playlist_id, current_track_id)
                        remove_tidal_playlist_membership(source_id, current_track_id)
                updated_rows = [dict(row) for row in rows]
                viewing_removed_collection = (
                    (collection or {}).get("type") == "playlist"
                    and action in {"remove", "move"}
                    and (action == "move" or str((collection or {}).get("id")) == playlist_id)
                )
                if viewing_removed_collection:
                    selected_set = set(selected_positions)
                    updated_rows = [row for index, row in enumerate(updated_rows) if index not in selected_set]
                else:
                    for index in selected_positions:
                        memberships = tidal_playlists_for_track(str(updated_rows[index].get("id") or ""))
                        _attach_memberships(
                            [updated_rows[index]],
                            {str(updated_rows[index].get("id") or ""): memberships},
                            {str(updated_rows[index].get("id") or ""): updated_rows[index].get("mixes") or []},
                            {str(updated_rows[index].get("id") or ""): updated_rows[index].get("djmi") or []},
                            collection,
                        )
                updated_selection = min(selected, len(updated_rows) - 1) if updated_rows else None
                return (
                    f"Updated {len(track_ids)} tracks.", updated_rows,
                    render_rows(updated_rows), "tracks", None, 0, updated_selection,
                )
            except Exception as exc:
                engine.LOGGER.exception("ui.liked_tracks bulk_action_failed action=%s", action)
                return f"Bulk action failed: {exc}", rows, render_rows(rows), "actions", action, 0, selected

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
            _attach_memberships(
                [updated_rows[selected]],
                {track_id: memberships},
                {track_id: updated_rows[selected].get("mixes") or []},
                {track_id: updated_rows[selected].get("djmi") or []},
                collection,
            )
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
        function(selected, selectedIndices, rows, hasMore, focus, actionMode, actionSelected, actionsChildren, collection, restoreState) {
            var collectionKey = String((collection || {}).type || 'liked') + ':' +
                String((collection || {}).id || '');
            var scrollStorageKey = 'musicsync.track-scroll.' + collectionKey;
            if (window.__likedCollectionKey !== collectionKey) {
                window.__likedCollectionKey = collectionKey;
                window.__likedTracksCount = 0;
                window.__likedTracksSelected = null;
                window.__likedSelectionAnchor = null;
                window.__likedTracksPendingScrollTop = null;
                window.__likedTracksRestoringScroll = false;
                var rememberedScroll = Number(sessionStorage.getItem(scrollStorageKey));
                window.__likedTracksScrollTop = Number.isFinite(rememberedScroll)
                    ? rememberedScroll : 0;
            }
            var previousCount = window.__likedTracksCount || 0;
            var previousSelected = window.__likedTracksSelected;
            window.__likedTracksCount = (rows || []).length;
            window.__likedTracksSelected = selected;
            window.__likedSelectedIndices = Array.isArray(selectedIndices) && selectedIndices.length
                ? selectedIndices : (Number.isInteger(selected) ? [selected] : []);
            window.__likedTracksFocus = focus || 'tracks';
            window.__likedActionMode = actionMode;
            window.__likedActionSelected = actionSelected || 0;
            var rowsChanged = previousCount !== window.__likedTracksCount;
            var selectionChanged = previousSelected !== selected;

            function paintSelection() {
                document.querySelectorAll('[data-liked-index]').forEach(function(row) {
                    var rowIndex = Number(row.dataset.likedIndex);
                    row.classList.toggle(
                        'selected',
                        rowIndex === window.__likedTracksSelected
                    );
                    row.classList.toggle(
                        'multi-selected',
                        window.__likedSelectedIndices.includes(rowIndex)
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
                    var clicked = Number(row.dataset.likedIndex);
                    var selection;
                    if (event.shiftKey && Number.isInteger(window.__likedSelectionAnchor)) {
                        var start = Math.min(window.__likedSelectionAnchor, clicked);
                        var end = Math.max(window.__likedSelectionAnchor, clicked);
                        selection = Array.from({length: end - start + 1}, function(_, offset) {
                            return start + offset;
                        });
                    } else {
                        window.__likedSelectionAnchor = clicked;
                        selection = [clicked];
                    }
                    window.dash_clientside.set_props('liked-selected', {
                        data: clicked
                    });
                    window.dash_clientside.set_props('liked-selected-indices', {data: selection});
                    window.dash_clientside.set_props('liked-focus', {data: 'tracks'});
                });
                document.addEventListener('scroll', function(event) {
                    var viewport = event.target;
                    if (!viewport || !viewport.classList ||
                        !viewport.classList.contains('track-table-wrap') ||
                        !viewport.closest('.track-list-pane')) return;
                    // Dash replaces the complete table when another page is appended.
                    // The replacement viewport starts at zero and may emit a scroll
                    // event before our render callback can restore the old position.
                    // Do not let that synthetic event destroy the pre-load snapshot.
                    if (window.__likedTracksRestoringScroll) return;
                    window.__likedTracksScrollTop = viewport.scrollTop;
                    if (window.__likedCollectionKey) {
                        sessionStorage.setItem(
                            'musicsync.track-scroll.' + window.__likedCollectionKey,
                            String(viewport.scrollTop)
                        );
                    }
                }, true);
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
                    } else if (option.dataset.watchedMixId && window.__likedActionMode) {
                        window.dash_clientside.set_props('liked-action-request', {
                            data: {
                                token: Date.now(),
                                action: window.__likedActionMode,
                                watched_mix_id: option.dataset.watchedMixId
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
                            } else if (playlistOption.dataset.watchedMixId) {
                                request.watched_mix_id = playlistOption.dataset.watchedMixId;
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
                    var selection;
                    if (event.shiftKey) {
                        if (!Number.isInteger(window.__likedSelectionAnchor)) {
                            window.__likedSelectionAnchor = current;
                        }
                        var start = Math.min(window.__likedSelectionAnchor, next);
                        var end = Math.max(window.__likedSelectionAnchor, next);
                        selection = Array.from({length: end - start + 1}, function(_, offset) {
                            return start + offset;
                        });
                    } else {
                        window.__likedSelectionAnchor = next;
                        selection = [next];
                    }
                    window.dash_clientside.set_props('liked-selected', {data: next});
                    window.dash_clientside.set_props('liked-selected-indices', {data: selection});
                });
            }
            function restoreViewportScroll(attempt) {
                var viewport = document.querySelector(
                    '.track-list-pane .track-table-wrap'
                );
                var pendingScrollTop = window.__likedTracksPendingScrollTop;
                var restoreTarget = Number.isFinite(pendingScrollTop)
                    ? pendingScrollTop : window.__likedTracksScrollTop;
                if (rowsChanged && viewport && Number.isFinite(restoreTarget)) {
                    window.__likedTracksRestoringScroll = true;
                    viewport.scrollTop = restoreTarget;
                    if (
                        attempt < 8 &&
                        Math.abs(viewport.scrollTop - restoreTarget) > 1
                    ) {
                        window.setTimeout(function() {
                            restoreViewportScroll(attempt + 1);
                        }, 35 * (attempt + 1));
                    } else {
                        window.__likedTracksScrollTop = viewport.scrollTop;
                        window.__likedTracksPendingScrollTop = null;
                        sessionStorage.setItem(scrollStorageKey, String(viewport.scrollTop));
                        window.setTimeout(function() {
                            window.__likedTracksRestoringScroll = false;
                        }, 80);
                    }
                } else if (
                    !rowsChanged && !hasMore && viewport &&
                    Number.isFinite(pendingScrollTop)
                ) {
                    // A collection whose size is an exact page multiple needs one
                    // final empty request to discover the end. That response does
                    // not change the row count, but it must still release the lock.
                    viewport.scrollTop = pendingScrollTop;
                    window.__likedTracksScrollTop = viewport.scrollTop;
                    window.__likedTracksPendingScrollTop = null;
                    sessionStorage.setItem(scrollStorageKey, String(viewport.scrollTop));
                    window.setTimeout(function() {
                        window.__likedTracksRestoringScroll = false;
                    }, 80);
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
            }
            window.setTimeout(function() { restoreViewportScroll(0); }, 0);

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
                        var requestedScrollTop = viewport.scrollTop;
                        window.__likedTracksScrollTop = requestedScrollTop;
                        window.__likedTracksPendingScrollTop = requestedScrollTop;
                        window.__likedTracksRestoringScroll = true;
                        sessionStorage.setItem(
                            'musicsync.track-scroll.' + window.__likedCollectionKey,
                            String(requestedScrollTop)
                        );
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
        Input("liked-selected-indices", "data"),
        Input("liked-rows", "data"),
        Input("liked-has-more", "data"),
        Input("liked-focus", "data"),
        Input("liked-action-mode", "data"),
        Input("liked-action-selected", "data"),
        Input("liked-actions", "children"),
        Input("track-collection", "data"),
        Input("track-view-restore", "data"),
    )
