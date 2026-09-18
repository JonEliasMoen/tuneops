"""Dash presentation for manually saved YouTube mixes."""

from __future__ import annotations

from urllib.parse import quote

from music_library.database import save_watched_mix, watched_mix
from music_tools.mixes.service import (
    fetch_youtube_metadata,
    youtube_thumbnail_url,
    youtube_video_id,
)
from music_tools.track_browser import content as track_browser_content


def content(html, dcc, video_id: str | None = None):
    if video_id is None:
        return [
            html.H1("Watched mixes"),
            html.P("Save a YouTube mix so you can later record which tracks you discovered in it."),
            html.Section(
                [
                    html.Label("YouTube mix URL"),
                    dcc.Input(
                        id="watched-mix-url",
                        type="url",
                        placeholder="https://youtube.com/watch?v=...",
                        className="mix-youtube-input",
                    ),
                    html.Button("Add mix", id="watched-mix-add", className="primary mix-save"),
                    html.Span(id="watched-mix-add-status", className="mix-save-status"),
                ],
                className="watched-mix-add",
            ),
        ]

    record = watched_mix(video_id)
    if record is None:
        return [html.H1("Watched mixes"), html.P("That watched mix was not found.")]
    thumbnail = youtube_thumbnail_url(record["youtube_url"])
    cover = (
        html.Img(src=thumbnail, className="mix-cover", alt="YouTube mix thumbnail")
        if thumbnail
        else html.Div("No thumbnail available", className="mix-cover mix-cover-empty")
    )
    collection = {
        "type": "watched_mix",
        "id": record["video_id"],
        "name": record.get("title") or "Watched mix tracks",
    }
    return [
        html.Div(
            [
                html.H1("Watched mix"),
                html.H2(
                    record.get("title") or "Loading YouTube title…",
                    id="watched-mix-title",
                    className="mix-youtube-title",
                ),
            ],
            className="mix-heading",
        ),
        html.Section(
            [
                html.Div(cover, className="mix-cover-container"),
                html.Div(
                    [
                        html.Div(
                            " · ".join(
                                value
                                for value in (
                                    record.get("channel_name", ""),
                                    f"Uploaded {record['upload_date']}"
                                    if record.get("upload_date")
                                    else "",
                                )
                                if value
                            ),
                            id="watched-mix-facts",
                            className="mix-youtube-views",
                        ),
                        html.A(
                            "Open on YouTube",
                            href=record["youtube_url"],
                            target="_blank",
                            className="watched-mix-link",
                        ),
                        html.P(f"Added {record['added_at']}", className="hint"),
                        html.Div(id="watched-mix-metadata-status", className="mix-save-status"),
                    ],
                    className="mix-body",
                ),
            ],
            className="mix-card",
        ),
        dcc.Store(id="watched-mix-record", data=record),
        dcc.Interval(id="watched-mix-refresh", interval=200, max_intervals=1, n_intervals=0),
        html.Div(
            track_browser_content(html, dcc, collection),
            className="mix-track-browser",
        ),
    ]


def register_callbacks(callback, Input, Output, State):
    from dash import no_update

    @callback(
        Output("app-url", "pathname"),
        Output("watched-mix-add-status", "children"),
        Input("watched-mix-add", "n_clicks"),
        State("watched-mix-url", "value"),
        prevent_initial_call=True,
    )
    def add_mix(_clicks, value):
        video_id = youtube_video_id(value or "")
        if not video_id:
            return no_update, "Enter a valid YouTube video URL."
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        metadata = fetch_youtube_metadata(canonical_url)
        save_watched_mix(
            video_id,
            canonical_url,
            title=metadata.title,
            channel_name=metadata.channel_name,
            upload_date=metadata.upload_date,
        )
        return f"/watched-mixes/{quote(video_id, safe='')}", "Saved."

    @callback(
        Output("watched-mix-title", "children"),
        Output("watched-mix-facts", "children"),
        Output("watched-mix-metadata-status", "children"),
        Input("watched-mix-refresh", "n_intervals"),
        State("watched-mix-record", "data"),
    )
    def load_metadata(_refresh, record):
        metadata = fetch_youtube_metadata((record or {}).get("youtube_url", ""))
        if record and (metadata.title or metadata.channel_name or metadata.upload_date):
            save_watched_mix(
                record.get("video_id", ""),
                record.get("youtube_url", ""),
                title=metadata.title or record.get("title", ""),
                channel_name=metadata.channel_name or record.get("channel_name", ""),
                upload_date=metadata.upload_date or record.get("upload_date", ""),
            )
        facts = []
        if metadata.view_count is not None:
            facts.append(f"{metadata.view_count:,} views")
        if metadata.channel_name:
            facts.append(metadata.channel_name)
        if metadata.upload_date:
            facts.append(f"Uploaded {metadata.upload_date}")
        return metadata.title or "YouTube mix", " · ".join(facts), metadata.error
