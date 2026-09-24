"""Dash page and callbacks for the playlist synchronization tool."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from music_library.database import (
    set_tidal_playlist_collection_type,
    tidal_artist,
    tidal_indexed_playlists,
)
from music_tools.track_browser import content as track_browser_content
from music_tools.track_browser import register_callbacks as register_track_browser_callbacks
from music_tools.mixes import content as mixes_content
from music_tools.mixes import register_callbacks as register_mixes_callbacks
from music_tools.mixes import register_routes as register_mixes_routes
from music_tools.watched_mixes import content as watched_mixes_content
from music_tools.watched_mixes import pending_content
from music_tools.watched_mixes import register_pending_callbacks
from music_tools.watched_mixes import register_callbacks as register_watched_mixes_callbacks
from music_tools.settings import DEFAULT_QUICK_VIEWS
from music_tools.settings import content as settings_content
from music_tools.settings import register_callbacks as register_settings_callbacks
from music_tools.global_search import content as global_search_content
from music_tools.events import links_panel as event_links_panel
from music_tools.events import register_callbacks as register_event_callbacks
from music_tools.ui import INDEX_STRING, shell, sidebar


def create_app(engine):
    """Build the web app without coupling the headless sync runner to Dash."""
    try:
        from dash import ALL, Dash, Input, Output, State, callback, ctx, dcc, html, no_update
        from flask import redirect, request
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    app = Dash(__name__, title="Music tools", suppress_callback_exceptions=True)
    register_mixes_routes(app.server)

    @app.server.get("/spotify/login")
    def spotify_login_route():
        try:
            url = engine.spotify_auth_manager().get_authorize_url()
            engine.LOGGER.info("spotify.auth redirect_to_authorize")
            return redirect(url)
        except Exception:
            engine.LOGGER.exception("spotify.auth could_not_start")
            return redirect("/?spotify_error=start")

    @app.server.get("/callback")
    def spotify_callback_route():
        error = request.args.get("error")
        code = request.args.get("code")
        if error or not code:
            engine.LOGGER.error(
                "spotify.auth callback_rejected error=%s code_present=%s", error, bool(code)
            )
            return redirect("/?spotify_error=denied")
        try:
            auth = engine.spotify_auth_manager()
            engine._call(
                "spotify",
                "exchange_authorization_code",
                lambda: auth.get_access_token(code, check_cache=False),
            )
            user = engine._call("spotify", "current_user", engine.spotify_client().current_user)
            label = str(user.get("display_name") or user.get("id"))
            engine._remember_connection("spotify", label)
            engine.LOGGER.info("spotify.auth callback_complete user_id=%s", user.get("id"))
            return redirect("/?spotify=connected")
        except Exception:
            engine.LOGGER.exception("spotify.auth callback_failed")
            return redirect("/?spotify_error=callback")

    def mapping_card(row: dict[str, Any], index: int):
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Mapping name"),
                                dcc.Input(
                                    value=row.get("name", ""),
                                    placeholder=f"Playlist sync {index + 1}",
                                    type="text",
                                    id={"type": "mapping-label", "index": index},
                                    className="mapping-name",
                                ),
                            ],
                            className="mapping-title",
                        ),
                        html.Button(
                            "Remove",
                            id={"type": "mapping-delete", "index": index},
                            className="danger",
                        ),
                    ],
                    className="mapping-head",
                ),
                dcc.Checklist(
                    options=[{"label": " Enabled", "value": "enabled"}],
                    value=["enabled"] if row.get("enabled", True) else [],
                    id={"type": "mapping-enabled", "index": index},
                ),
                html.Label("Sync direction"),
                dcc.Dropdown(
                    options=[
                        {"label": "Spotify → TIDAL", "value": "spotify_to_tidal"},
                        {"label": "TIDAL → Spotify", "value": "tidal_to_spotify"},
                        {"label": "TIDAL cache", "value": "tidal_cache"},
                    ],
                    value=row.get("direction", "spotify_to_tidal"),
                    clearable=False,
                    id={"type": "mapping-direction", "index": index},
                    className="direction-select",
                ),
                html.Label("Library section"),
                dcc.Dropdown(
                    options=[
                        {"label": "Playlist", "value": "playlist"},
                        {"label": "Event", "value": "event"},
                        {"label": "Source", "value": "source"},
                    ],
                    value=row.get("collection_type", "playlist"),
                    clearable=False,
                    id={"type": "mapping-collection-type", "index": index},
                    className="direction-select",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label("Spotify playlist URL or ID"),
                                dcc.Input(
                                    value=row.get("spotify", ""),
                                    type="text",
                                    id={"type": "mapping-spotify", "index": index},
                                ),
                            ],
                            className="field",
                        ),
                        html.Div(
                            [
                                html.Label("TIDAL playlist URL or ID"),
                                dcc.Input(
                                    value=row.get("tidal", ""),
                                    type="text",
                                    id={"type": "mapping-tidal", "index": index},
                                ),
                            ],
                            className="field",
                        ),
                    ],
                    className="field-grid",
                ),
                html.Div(
                    [
                        html.Label(
                            "Target name override (optional — defaults to the source playlist name)"
                        ),
                        dcc.Input(
                            value=row.get("tidal_name", ""),
                            placeholder="Use source playlist name",
                            type="text",
                            id={"type": "mapping-name", "index": index},
                        ),
                    ],
                    className="field",
                ),
            ],
            className="mapping-card",
        )

    def rows_from_form(
        labels, enabled, directions, collection_types,
        spotify_values, tidal_values, names, stored_rows=None
    ) -> list[dict[str, Any]]:
        stored_rows = stored_rows or []
        rows = []
        for index in range(len(directions)):
            # Preserve hidden state such as unmatched tracks and sync timestamps.
            row = dict(stored_rows[index]) if index < len(stored_rows) else {}
            row.update(
                {
                    "enabled": "enabled" in (enabled[index] or []),
                    "name": labels[index] or "",
                    "direction": directions[index] or "spotify_to_tidal",
                    "collection_type": collection_types[index] or "playlist",
                    "spotify": spotify_values[index] or "",
                    "tidal": tidal_values[index] or "",
                    "tidal_name": names[index] or "",
                }
            )
            rows.append(row)
        return rows

    def playlist_sync_layout():
        current = engine.load_config()
        for row in current["playlists"]:
            row.setdefault("name", "")
            row.setdefault("direction", "spotify_to_tidal")
            row.setdefault("collection_type", "playlist")
            playlist_id = engine._id(row.get("tidal", ""))
            if playlist_id:
                set_tidal_playlist_collection_type(
                    playlist_id, row["collection_type"]
                )
        spotify_badge = engine._connection_badge("spotify", engine.SPOTIFY_CACHE)
        tidal_badge = engine._connection_badge("tidal", engine.TIDAL_CACHE)
        return shell(
            html,
            "playlist-sync",
            [
            html.H1("Spotify ↔ TIDAL"),
            html.P("Configure playlist pairs, connect both accounts once, then sync on demand."),
            html.Div(
                [
                    html.Span(spotify_badge[0], id="spotify-state", className=spotify_badge[1]),
                    html.Span(tidal_badge[0], id="tidal-state", className=tidal_badge[1]),
                ],
                className="connections",
            ),
            html.Div(
                [
                    html.Button("Connect Spotify", id="spotify-login"),
                    html.Button("Connect TIDAL", id="tidal-login"),
                    html.Button("Sync now", id="sync", className="primary"),
                ],
                className="actions",
            ),
            dcc.Loading(html.Pre("Ready", id="status"), type="circle"),
            dcc.Interval(id="connection-refresh", interval=500, max_intervals=1, n_intervals=0),
            dcc.Store(id="mapping-store", data=current["playlists"]),
            html.H2("Playlist mappings"),
            html.Div(id="mapping-list"),
            html.Div(
                [html.Button("Add row", id="add"), html.Button("Save configuration", id="save")],
                className="actions",
            ),
            html.P(f"Configuration: {engine.CONFIG_PATH}", className="hint"),
            ],
        )

    app_config = engine.load_config()
    initial_dark_mode = bool(app_config.get("settings", {}).get("dark_mode", True))
    initial_tags_collapsed = bool(
        app_config.get("settings", {}).get("tags_collapsed_by_default", True)
    )
    app.layout = html.Div(
        [
            dcc.Location(id="app-url"),
            dcc.Store(
                id="quick-views",
                data=app_config.get("quick_views", DEFAULT_QUICK_VIEWS),
            ),
            dcc.Store(
                id="theme-settings",
                data={"dark_mode": initial_dark_mode},
            ),
            dcc.Store(
                id="ui-preferences",
                data={"tags_collapsed": initial_tags_collapsed},
            ),
            dcc.Store(
                id="track-view-state",
                data={"sort": {}, "visible_fields": None, "collections": {}},
                storage_type="session",
            ),
            html.Div(id="page-root"),
        ],
        id="app-root",
        className="theme-dark" if initial_dark_mode else "theme-light",
    )

    @callback(Output("app-root", "className"), Input("theme-settings", "data"))
    def apply_theme(theme):
        return "theme-dark" if (theme or {}).get("dark_mode", True) else "theme-light"

    @callback(
        Output("page-root", "children"),
        Input("app-url", "pathname"),
        State("track-view-state", "data"),
    )
    def route_page(pathname: str | None, view_state: dict[str, Any] | None):
        quick_views = engine.load_config().get("quick_views", DEFAULT_QUICK_VIEWS)
        if pathname == "/liked-tracks":
            return shell(
                html,
                "liked-tracks",
                track_browser_content(
                    html, dcc, quick_views=quick_views, view_state=view_state
                ),
            )
        if pathname == "/search":
            return shell(
                html,
                "global-search",
                global_search_content(
                    html, dcc, quick_views=quick_views, view_state=view_state
                ),
            )
        if pathname == "/settings":
            config = engine.load_config()
            return shell(
                html,
                "settings",
                settings_content(
                    html,
                    dcc,
                    config.get("quick_views", DEFAULT_QUICK_VIEWS),
                    bool(config.get("settings", {}).get("dark_mode", True)),
                    bool(
                        config.get("settings", {}).get(
                            "tags_collapsed_by_default", True
                        )
                    ),
                    str(config.get("settings", {}).get("lastfm_username", "") or ""),
                ),
            )
        if pathname == "/mixes":
            return shell(
                html,
                "mixes",
                mixes_content(
                    html, dcc, quick_views=quick_views, view_state=view_state
                ),
            )
        if pathname and pathname.startswith("/mixes/"):
            folder_name = unquote(pathname.removeprefix("/mixes/").strip("/"))
            return shell(
                html,
                f"mix:{folder_name}",
                mixes_content(
                    html, dcc, folder_name, quick_views=quick_views,
                    view_state=view_state,
                ),
            )
        if pathname == "/watched-mixes":
            return shell(
                html,
                "watched-mixes",
                watched_mixes_content(
                    html, dcc, quick_views=quick_views, view_state=view_state
                ),
            )
        if pathname == "/watched-mixes/pending":
            return shell(html, "pending-tracks", pending_content(html, dcc))
        if pathname and pathname.startswith("/watched-mixes/"):
            video_id = unquote(pathname.removeprefix("/watched-mixes/").strip("/"))
            return shell(
                html,
                f"watched-mix:{video_id}",
                watched_mixes_content(
                    html, dcc, video_id, quick_views=quick_views,
                    view_state=view_state,
                ),
            )
        if pathname and pathname.startswith("/artists/"):
            artist_key = unquote(pathname.removeprefix("/artists/").strip("/"))
            artist = tidal_artist(artist_key)
            if artist:
                collection = {
                    "type": "artist",
                    "id": artist_key,
                    "name": artist.get("name") or artist_key,
                }
                return shell(
                    html,
                    "liked-tracks",
                    track_browser_content(
                        html, dcc, collection, quick_views, view_state
                    ),
                )
        collection_routes = {
            "/playlists/": ("playlist", "playlist"),
            "/events/": ("event", "event"),
            "/sources/": ("source", "source"),
        }
        route = next(
            (
                (prefix, kind, active_prefix)
                for prefix, (kind, active_prefix) in collection_routes.items()
                if pathname and pathname.startswith(prefix)
            ),
            None,
        )
        if route:
            prefix, kind, active_prefix = route
            playlist_id = pathname.removeprefix(prefix).strip("/")
            indexed = {item["id"]: item for item in tidal_indexed_playlists()}
            playlist = indexed.get(playlist_id)
            if playlist and playlist.get("collection_type") == kind:
                collection = {
                    "type": "playlist",
                    "id": playlist_id,
                    "name": playlist.get("name") or playlist_id,
                    "collection_type": kind,
                }
                return shell(
                    html,
                    f"{active_prefix}:{playlist_id}",
                    track_browser_content(
                        html,
                        dcc,
                        collection,
                        quick_views,
                        view_state,
                        header_extra=(
                            event_links_panel(html, dcc, playlist_id)
                            if kind == "event"
                            else None
                        ),
                    ),
                )
        return playlist_sync_layout()

    register_track_browser_callbacks(
        app, callback, Input, Output, State, ALL, html, ctx, engine
    )
    register_mixes_callbacks(app, callback, Input, Output, State, ctx, html, dcc, engine)
    register_watched_mixes_callbacks(
        callback, Input, Output, State, ALL, html, dcc, engine
    )
    register_pending_callbacks(
        callback, Input, Output, State, ALL, html, dcc, ctx, engine
    )
    register_settings_callbacks(
        callback, Input, Output, State, ALL, html, dcc, ctx, no_update, engine
    )
    register_event_callbacks(callback, Input, Output, State, ctx, html)

    @callback(Output("mapping-list", "children"), Input("mapping-store", "data"))
    def render_mappings(rows: list[dict[str, Any]]):
        return [mapping_card(row, index) for index, row in enumerate(rows)]

    @callback(Output("app-sidebar", "children"), Input("mapping-store", "data"))
    def refresh_sidebar(_rows: list[dict[str, Any]]):
        """Reflect saved collection classifications without a page reload."""
        return sidebar(html, "playlist-sync").children

    form_states = [
        State({"type": "mapping-label", "index": ALL}, "value"),
        State({"type": "mapping-enabled", "index": ALL}, "value"),
        State({"type": "mapping-direction", "index": ALL}, "value"),
        State({"type": "mapping-collection-type", "index": ALL}, "value"),
        State({"type": "mapping-spotify", "index": ALL}, "value"),
        State({"type": "mapping-tidal", "index": ALL}, "value"),
        State({"type": "mapping-name", "index": ALL}, "value"),
        State("mapping-store", "data"),
    ]

    @callback(
        Output("mapping-store", "data"),
        Input("add", "n_clicks"),
        Input({"type": "mapping-delete", "index": ALL}, "n_clicks"),
        *form_states,
        prevent_initial_call=True,
    )
    def change_rows(
        _, delete_clicks, labels, enabled, directions, collection_types,
        spotify_values, tidal_values, names, stored_rows
    ):
        rows = rows_from_form(
            labels, enabled, directions, collection_types,
            spotify_values, tidal_values, names, stored_rows
        )
        trigger = ctx.triggered_id
        if trigger == "add":
            rows.append(
                {
                    "enabled": True,
                    "name": "",
                    "direction": "spotify_to_tidal",
                    "collection_type": "playlist",
                    "spotify": "",
                    "tidal": "",
                    "tidal_name": "",
                }
            )
        elif isinstance(trigger, dict) and trigger.get("type") == "mapping-delete":
            index = int(trigger["index"])
            if index >= len(delete_clicks) or not delete_clicks[index]:
                return no_update
            if 0 <= index < len(rows):
                rows.pop(index)
        return rows

    @callback(
        Output("status", "children", allow_duplicate=True),
        Output("mapping-store", "data", allow_duplicate=True),
        Input("save", "n_clicks"),
        *form_states,
        prevent_initial_call=True,
    )
    def save_rows(
        _, labels, enabled, directions, collection_types,
        spotify_values, tidal_values, names, stored_rows
    ):
        rows = rows_from_form(
            labels, enabled, directions, collection_types,
            spotify_values, tidal_values, names, stored_rows
        )
        config = engine.load_config()
        config["playlists"] = rows
        engine.save_config(config)
        for row in rows:
            playlist_id = engine._id(row.get("tidal", ""))
            if playlist_id:
                set_tidal_playlist_collection_type(
                    playlist_id, row.get("collection_type", "playlist")
                )
        return f"Saved {len(rows)} mapping(s).", rows

    app.clientside_callback(
        "function(n) { if (n) { window.location.assign('/spotify/login'); } "
        "return window.dash_clientside.no_update; }",
        Output("spotify-login", "title"),
        Input("spotify-login", "n_clicks"),
        prevent_initial_call=True,
    )

    @callback(
        Output("spotify-state", "children"),
        Output("spotify-state", "className"),
        Output("tidal-state", "children"),
        Output("tidal-state", "className"),
        Input("connection-refresh", "n_intervals"),
        prevent_initial_call=True,
    )
    def refresh_connections(_: int):
        spotify = engine._connection_badge("spotify", engine.SPOTIFY_CACHE)
        tidal = engine._connection_badge("tidal", engine.TIDAL_CACHE)
        return spotify[0], spotify[1], tidal[0], tidal[1]

    @callback(
        Output("status", "children", allow_duplicate=True),
        Output("tidal-state", "children", allow_duplicate=True),
        Output("tidal-state", "className", allow_duplicate=True),
        Input("tidal-login", "n_clicks"),
        prevent_initial_call=True,
    )
    def connect_tidal(_: int):
        messages: list[str] = []
        try:
            engine.LOGGER.info("ui.tidal_connect clicked")
            session = engine.tidal_client(interactive=True, message=messages.append)
            label = str(getattr(session.user, "name", "") or session.user.id)
            engine._remember_connection("tidal", label)
            return (
                f"TIDAL connected as {label}.",
                f"● TIDAL connected: {label}",
                "connection connected",
            )
        except Exception as exc:
            engine.LOGGER.exception("ui.tidal_connect failed")
            badge = engine._connection_badge("tidal", engine.TIDAL_CACHE)
            return f"TIDAL connection failed: {exc}. " + " ".join(messages), badge[0], badge[1]

    @callback(
        Output("status", "children", allow_duplicate=True),
        Output("mapping-store", "data", allow_duplicate=True),
        Input("sync", "n_clicks"),
        *form_states,
        prevent_initial_call=True,
        running=[(Output("sync", "disabled"), True, False)],
    )
    def sync_now(
        _, labels, enabled, directions, collection_types,
        spotify_values, tidal_values, names, stored_rows
    ):
        rows = rows_from_form(
            labels, enabled, directions, collection_types,
            spotify_values, tidal_values, names, stored_rows
        )
        config = engine.load_config()
        config["playlists"] = rows
        engine.save_config(config)
        try:
            engine.LOGGER.info("ui.sync clicked mappings=%d", len(rows))
            results = engine.run_all_syncs()
            lines = []
            for result in results:
                prefix = f"{result.label}: " if result.label else ""
                if result.skipped:
                    lines.append(f"{prefix}skipped — source playlist has not changed since the last sync")
                elif result.error:
                    lines.append(f"{prefix}FAILED {result.source}: {result.error}")
                elif result.cached:
                    lines.append(f"{prefix}{result.source}: cached {result.cached} tracks in SQLite")
                else:
                    lines.append(
                        f"{prefix}{result.target}: added {result.added}, already present "
                        f"{result.already_present}, unmatched {result.unmatched}"
                    )
            return "\n".join(lines) or "No enabled playlists.", engine.load_config()["playlists"]
        except Exception as exc:
            engine.LOGGER.exception("ui.sync failed")
            return f"Sync failed: {exc}", no_update

    app.index_string = INDEX_STRING
    return app
