"""Dash presentation for locally stored DJ mixes."""

from __future__ import annotations

from urllib.parse import quote

from music_library.database import save_setlist_tidal_source, save_setlist_youtube_url
from music_tools.track_browser import content as track_browser_content
from .service import (
    MIX_ROOT,
    cover_for,
    fetch_youtube_metadata,
    import_tidal_setlist,
    mix_for,
    youtube_thumbnail_url,
)


def _track_collection(mix, playlist_id: str | None = None, playlist_name: str | None = None):
    resolved_id = playlist_id or mix.tidal_playlist_id
    if not resolved_id:
        return None
    return {
        "type": "setlist",
        "id": mix.folder_name,
        "name": playlist_name or mix.tidal_playlist_name or mix.folder_name,
    }


def _cover_component(html, mix, youtube_url: str | None = None):
    if mix.cover_path:
        return html.Img(
            src=f"/mix-assets/{quote(mix.folder_name, safe='')}/cover",
            className="mix-cover",
            alt=f"{mix.folder_name} cover",
        )
    thumbnail = youtube_thumbnail_url(youtube_url if youtube_url is not None else mix.youtube_url)
    if thumbnail:
        return html.Img(
            src=thumbnail,
            className="mix-cover",
            alt=f"{mix.folder_name} YouTube thumbnail",
        )
    return html.Div("No cover available", className="mix-cover mix-cover-empty")


def content(html, dcc, folder_name: str | None = None):
    mix = mix_for(folder_name) if folder_name else None
    if mix is None:
        message = "Select a mix from the My mixes section in the sidebar."
        if folder_name:
            message = f"Mix folder not found: {folder_name}"
        return [
            html.H1("My mixes"),
            html.P(message),
            html.P(f"Local mixes from {MIX_ROOT}", className="hint"),
        ]

    cover = _cover_component(html, mix)
    collection = _track_collection(mix)
    track_browser = track_browser_content(html, dcc, collection) if collection else []
    return [
        html.Div(
            [
                html.H1(mix.folder_name),
                html.H2(
                    "",
                    id={"type": "mix-youtube-title", "name": mix.folder_name},
                    className="mix-youtube-title",
                ),
                html.H2(
                    mix.tidal_playlist_name,
                    id={"type": "mix-tidal-title", "name": mix.folder_name},
                    className="mix-tidal-title",
                ),
            ],
            className="mix-heading",
        ),
        html.Section(
            [
                html.Div(
                    cover,
                    id={"type": "mix-cover", "name": mix.folder_name},
                    className="mix-cover-container",
                ),
                html.Div(
                    [
                        html.Div(
                            "Final audio found" if mix.audio_path else f"Missing {mix.folder_name}yt.wav",
                            className="mix-file-state" if mix.audio_path else "mix-file-state missing",
                        ),
                        html.Label("YouTube link"),
                        dcc.Input(
                            id={"type": "mix-youtube-url", "name": mix.folder_name},
                            value=mix.youtube_url,
                            type="url",
                            placeholder="https://youtube.com/watch?v=...",
                            className="mix-youtube-input",
                        ),
                        html.Button(
                            "Save link",
                            id={"type": "mix-save-youtube", "name": mix.folder_name},
                            className="primary mix-save",
                        ),
                        html.Span(
                            "",
                            id={"type": "mix-save-status", "name": mix.folder_name},
                            className="mix-save-status",
                        ),
                        html.Div(
                            "",
                            id={"type": "mix-youtube-views", "name": mix.folder_name},
                            className="mix-youtube-views",
                        ),
                        dcc.Interval(
                            id={"type": "mix-youtube-refresh", "name": mix.folder_name},
                            interval=200,
                            max_intervals=1,
                            n_intervals=0,
                        ),
                        html.H3("TIDAL playlist", className="mix-tidal-heading"),
                        dcc.Input(
                            id={"type": "mix-tidal-url", "name": mix.folder_name},
                            value=mix.tidal_url,
                            type="url",
                            placeholder="https://tidal.com/browse/playlist/...",
                            className="mix-youtube-input",
                        ),
                        html.Button(
                            "Sync playlist",
                            id={"type": "mix-sync-tidal", "name": mix.folder_name},
                            className="primary mix-save",
                        ),
                        html.Span(
                            "",
                            id={"type": "mix-sync-status", "name": mix.folder_name},
                            className="mix-save-status",
                        ),
                    ],
                    className="mix-body",
                ),
            ],
            className="mix-card",
        ),
        html.Div(
            track_browser,
            id={"type": "mix-track-browser", "name": mix.folder_name},
            className="mix-track-browser",
        ),
    ]


def register_routes(server) -> None:
    from flask import abort, send_file

    @server.get("/mix-assets/<folder_name>/cover")
    def mix_cover(folder_name: str):
        cover = cover_for(folder_name)
        if cover is None:
            abort(404)
        return send_file(cover, conditional=True)


def register_callbacks(app, callback, Input, Output, State, ctx, html, dcc, engine) -> None:
    from dash import MATCH, no_update

    @callback(
        Output({"type": "mix-save-status", "name": MATCH}, "children"),
        Output({"type": "mix-youtube-title", "name": MATCH}, "children"),
        Output({"type": "mix-youtube-views", "name": MATCH}, "children"),
        Output({"type": "mix-cover", "name": MATCH}, "children"),
        Input({"type": "mix-save-youtube", "name": MATCH}, "n_clicks"),
        Input({"type": "mix-youtube-refresh", "name": MATCH}, "n_intervals"),
        State({"type": "mix-youtube-url", "name": MATCH}, "value"),
    )
    def load_youtube_metadata(_clicks, _refresh, value):
        folder_name = str(ctx.triggered_id["name"])
        mix = mix_for(folder_name)
        if mix is None:
            return "Mix folder no longer exists.", "", "", no_update
        saving = ctx.triggered_id.get("type") == "mix-save-youtube"
        if saving:
            save_setlist_youtube_url(folder_name, value or "")
        metadata = fetch_youtube_metadata(value or "")
        status = "Saved." if saving and not metadata.error else metadata.error
        facts = []
        if metadata.view_count is not None:
            facts.append(f"{metadata.view_count:,} views")
        if metadata.upload_date:
            facts.append(f"Uploaded {metadata.upload_date}")
        cover = no_update if mix.cover_path else _cover_component(html, mix, value or "")
        return status, metadata.title, " · ".join(facts), cover

    @callback(
        Output({"type": "mix-sync-status", "name": MATCH}, "children"),
        Output({"type": "mix-track-browser", "name": MATCH}, "children"),
        Output({"type": "mix-tidal-title", "name": MATCH}, "children"),
        Input({"type": "mix-sync-tidal", "name": MATCH}, "n_clicks"),
        State({"type": "mix-tidal-url", "name": MATCH}, "value"),
        prevent_initial_call=True,
        running=[
            (Output({"type": "mix-sync-tidal", "name": MATCH}, "disabled"), True, False)
        ],
    )
    def sync_tidal_playlist(_clicks, value):
        folder_name = str(ctx.triggered_id["name"])
        mix = mix_for(folder_name)
        if mix is None:
            return "Mix folder no longer exists.", no_update, no_update
        tidal_url = str(value or "").strip()
        if not tidal_url:
            save_setlist_tidal_source(folder_name, "")
            return "TIDAL playlist mapping cleared.", [], ""
        # Save the user's input even if the provider is temporarily unavailable.
        save_setlist_tidal_source(folder_name, tidal_url)
        try:
            playlist, records = import_tidal_setlist(engine, mix, tidal_url)
            playlist_id = str(playlist.id)
            playlist_name = str(getattr(playlist, "name", "") or folder_name)
            collection = _track_collection(mix, playlist_id, playlist_name)
            engine.LOGGER.info(
                "ui.mixes tidal_sync_ok mix=%r playlist_id=%s tracks=%d",
                folder_name,
                playlist_id,
                len(records),
            )
            return (
                f"Synced {len(records):,} tracks from {playlist_name}.",
                track_browser_content(html, dcc, collection),
                playlist_name,
            )
        except Exception as exc:
            engine.LOGGER.exception("ui.mixes tidal_sync_failed mix=%r", folder_name)
            return f"TIDAL sync failed: {exc}", no_update, no_update
