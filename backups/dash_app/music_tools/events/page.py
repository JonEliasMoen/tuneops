"""User-owned links associated with indexed event collections."""

from __future__ import annotations

from urllib.parse import urlparse

from music_library.database import event_links, save_event_links
from music_tools.mixes.service import (
    fetch_youtube_metadata,
    youtube_thumbnail_url,
    youtube_video_id,
)


def _safe_web_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _cover(html, youtube_url: str):
    thumbnail = youtube_thumbnail_url(youtube_url)
    if thumbnail:
        return html.Img(
            src=thumbnail,
            className="mix-cover",
            alt="Event video thumbnail",
        )
    return html.Div(
        "No YouTube video linked",
        className="mix-cover mix-cover-empty",
    )


def links_panel(html, dcc, playlist_id: str):
    """Render link controls without contacting Concert Archives."""
    saved = event_links(playlist_id)
    youtube_url = _safe_web_url(saved.get("youtube_url", ""))
    key = str(playlist_id)
    return html.Section(
        [
            html.Div(
                _cover(html, youtube_url),
                id={"type": "event-video-cover", "id": key},
                className="mix-cover-container",
            ),
            html.Div(
                [
                    html.H2(
                        "Event video",
                        id={"type": "event-video-title", "id": key},
                        className="mix-title",
                    ),
                    html.Div(
                        "",
                        id={"type": "event-video-facts", "id": key},
                        className="mix-youtube-views",
                    ),
                    html.Label("YouTube video URL"),
                    dcc.Input(
                        id={"type": "event-youtube-url", "id": key},
                        value=saved.get("youtube_url", ""),
                        type="url",
                        placeholder="https://youtube.com/watch?v=...",
                        className="mix-youtube-input",
                    ),
                    html.Label("Concert Archives URL", className="event-link-label"),
                    dcc.Input(
                        id={"type": "event-concert-url", "id": key},
                        value=saved.get("concert_archives_url", ""),
                        type="url",
                        placeholder="https://www.concertarchives.org/...",
                        className="mix-youtube-input",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Save links",
                                id={"type": "event-links-save", "id": key},
                                className="primary mix-save",
                            ),
                            html.A(
                                "Open on YouTube",
                                id={"type": "event-youtube-open", "id": key},
                                href=youtube_url or None,
                                target="_blank",
                                className="watched-mix-link event-open-link",
                                style={} if youtube_url else {"display": "none"},
                            ),
                        ],
                        className="event-link-actions",
                    ),
                    html.Div(
                        "",
                        id={"type": "event-links-status", "id": key},
                        className="mix-save-status",
                    ),
                    dcc.Interval(
                        id={"type": "event-video-refresh", "id": key},
                        interval=200,
                        max_intervals=1,
                        n_intervals=0,
                    ),
                ],
                className="mix-body",
            ),
        ],
        className="mix-card event-links-card",
    )


def register_callbacks(callback, Input, Output, State, ctx, html):
    from dash import MATCH, no_update

    @callback(
        Output({"type": "event-links-status", "id": MATCH}, "children"),
        Output({"type": "event-video-title", "id": MATCH}, "children"),
        Output({"type": "event-video-facts", "id": MATCH}, "children"),
        Output({"type": "event-video-cover", "id": MATCH}, "children"),
        Output({"type": "event-youtube-open", "id": MATCH}, "href"),
        Output({"type": "event-youtube-open", "id": MATCH}, "style"),
        Input({"type": "event-links-save", "id": MATCH}, "n_clicks"),
        Input({"type": "event-video-refresh", "id": MATCH}, "n_intervals"),
        State({"type": "event-youtube-url", "id": MATCH}, "value"),
        State({"type": "event-concert-url", "id": MATCH}, "value"),
    )
    def update_event_links(_clicks, _refresh, youtube_value, concert_value):
        playlist_id = str(ctx.triggered_id["id"])
        youtube_raw = str(youtube_value or "").strip()
        concert_raw = str(concert_value or "").strip()
        saving = ctx.triggered_id.get("type") == "event-links-save"

        if youtube_raw and not youtube_video_id(youtube_raw):
            return (
                "Enter a valid YouTube video URL.", no_update, no_update,
                no_update, no_update, no_update,
            )
        youtube_url = _safe_web_url(youtube_raw)
        concert_url = _safe_web_url(concert_raw)
        if concert_raw and not concert_url:
            return (
                "Concert Archives must be a valid http(s) URL.",
                no_update, no_update, no_update, no_update, no_update,
            )
        if saving:
            save_event_links(playlist_id, youtube_raw, concert_raw)

        metadata = fetch_youtube_metadata(youtube_raw) if youtube_raw else None
        facts = []
        if metadata and metadata.channel_name:
            facts.append(metadata.channel_name)
        if metadata and metadata.view_count is not None:
            facts.append(f"{metadata.view_count:,} views")
        if metadata and metadata.upload_date:
            facts.append(f"Uploaded {metadata.upload_date}")
        status = "Saved." if saving else ""
        if metadata and metadata.error:
            status = f"{status} {metadata.error}".strip()
        return (
            status,
            metadata.title if metadata and metadata.title else "Event video",
            " · ".join(facts),
            _cover(html, youtube_raw),
            youtube_url or None,
            {} if youtube_url else {"display": "none"},
        )
