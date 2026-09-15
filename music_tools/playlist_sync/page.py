"""Dash page and callbacks for the playlist synchronization tool."""

from __future__ import annotations

from typing import Any

from music_tools.liked_tracks import content as liked_tracks_content
from music_tools.liked_tracks import register_callbacks as register_liked_tracks_callbacks
from music_tools.ui import INDEX_STRING, shell


def create_app(engine):
    """Build the web app without coupling the headless sync runner to Dash."""
    try:
        from dash import ALL, Dash, Input, Output, State, callback, ctx, dcc, html, no_update
        from flask import redirect, request
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from exc

    app = Dash(__name__, title="Music tools", suppress_callback_exceptions=True)

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

    initial = engine.load_config()
    for row in initial["playlists"]:
        row.setdefault("name", "")
        row.setdefault("direction", "spotify_to_tidal")

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
        labels, enabled, directions, spotify_values, tidal_values, names, stored_rows=None
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
                    "spotify": spotify_values[index] or "",
                    "tidal": tidal_values[index] or "",
                    "tidal_name": names[index] or "",
                }
            )
            rows.append(row)
        return rows

    spotify_badge = engine._connection_badge("spotify", engine.SPOTIFY_CACHE)
    tidal_badge = engine._connection_badge("tidal", engine.TIDAL_CACHE)
    playlist_sync_layout = shell(
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
            dcc.Store(id="mapping-store", data=initial["playlists"]),
            html.H2("Playlist mappings"),
            html.Div(id="mapping-list"),
            html.Div(
                [html.Button("Add row", id="add"), html.Button("Save configuration", id="save")],
                className="actions",
            ),
            html.P(f"Configuration: {engine.CONFIG_PATH}", className="hint"),
        ],
    )

    app.layout = html.Div([dcc.Location(id="app-url"), html.Div(id="page-root")])

    @callback(Output("page-root", "children"), Input("app-url", "pathname"))
    def route_page(pathname: str | None):
        if pathname == "/liked-tracks":
            return shell(html, "liked-tracks", liked_tracks_content(html, dcc))
        return playlist_sync_layout

    register_liked_tracks_callbacks(app, callback, Input, Output, State, html, ctx, engine)

    @callback(Output("mapping-list", "children"), Input("mapping-store", "data"))
    def render_mappings(rows: list[dict[str, Any]]):
        return [mapping_card(row, index) for index, row in enumerate(rows)]

    form_states = [
        State({"type": "mapping-label", "index": ALL}, "value"),
        State({"type": "mapping-enabled", "index": ALL}, "value"),
        State({"type": "mapping-direction", "index": ALL}, "value"),
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
        _, delete_clicks, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows
    ):
        rows = rows_from_form(
            labels, enabled, directions, spotify_values, tidal_values, names, stored_rows
        )
        trigger = ctx.triggered_id
        if trigger == "add":
            rows.append(
                {
                    "enabled": True,
                    "name": "",
                    "direction": "spotify_to_tidal",
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
        Input("save", "n_clicks"),
        *form_states,
        prevent_initial_call=True,
    )
    def save_rows(_, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows):
        rows = rows_from_form(
            labels, enabled, directions, spotify_values, tidal_values, names, stored_rows
        )
        config = engine.load_config()
        config["playlists"] = rows
        engine.save_config(config)
        return f"Saved {len(rows)} mapping(s)."

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
    def sync_now(_, labels, enabled, directions, spotify_values, tidal_values, names, stored_rows):
        rows = rows_from_form(
            labels, enabled, directions, spotify_values, tidal_values, names, stored_rows
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
