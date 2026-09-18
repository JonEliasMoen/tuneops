"""Dash presentation for manually saved YouTube mixes."""

from __future__ import annotations

import time
from urllib.parse import quote

from music_library.database import (
    add_tidal_liked_track,
    add_pending_track,
    associate_tidal_tracks_with_watched_mix,
    save_watched_mix,
    watched_mix,
)
from music_tools.mixes.service import (
    fetch_youtube_metadata,
    youtube_thumbnail_url,
    youtube_video_id,
)
from music_tools.track_browser import content as track_browser_content
from music_tools.track_browser.stopwatch import content as stopwatch_content
from .tracklist import find_tidal_matches, parse_tracklist


def content(html, dcc, video_id: str | None = None, quick_views=None):
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
        dcc.Store(id="watched-tracklist-draft", data=[]),
        dcc.Interval(id="watched-mix-refresh", interval=200, max_intervals=1, n_intervals=0),
        html.Section(
            [
                html.H2("Tracklist import"),
                html.P(
                    "Paste an Artist - Title tracklist (timestamps are optional), match it against TIDAL, then like and associate confirmed tracks.",
                    className="hint",
                ),
                dcc.Textarea(
                    id="watched-tracklist-input",
                    placeholder="00:00 Artist - Track\n[05:30] Artist - Next track\nArtist - Track without timestamp",
                    className="tracklist-input",
                ),
                dcc.Dropdown(
                    id="watched-tracklist-order",
                    options=[
                        {"label": "Artist - Title", "value": "artist_title"},
                        {"label": "Title - Artist", "value": "title_artist"},
                    ],
                    value="artist_title",
                    clearable=False,
                    className="tracklist-order",
                ),
                html.Div(
                    [
                        html.Button("Parse tracklist", id="watched-tracklist-parse"),
                        html.Button(
                            "Find TIDAL matches",
                            id="watched-tracklist-search",
                            className="primary",
                        ),
                    ],
                    className="actions",
                ),
                stopwatch_content(html),
                html.Div(id="watched-tracklist-status", className="track-status"),
                html.Div(id="watched-tracklist-table"),
            ],
            className="tracklist-import",
        ),
        html.Div(
            track_browser_content(html, dcc, collection, quick_views),
            className="mix-track-browser",
        ),
    ]


def register_callbacks(callback, Input, Output, State, ALL, html, dcc, engine):
    from dash import ctx, no_update

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

    @callback(
        Output("watched-tracklist-table", "children"),
        Input("watched-tracklist-draft", "data"),
    )
    def render_tracklist(rows):
        rows = rows or []
        if not rows:
            return html.Div("No parsed tracklist yet.", className="detail-empty")
        return html.Div(
            html.Table(
                [
                    html.Thead(
                        html.Tr([
                            html.Th("Time"), html.Th("Artist"), html.Th("Title"),
                            html.Th("TIDAL match"), html.Th("Status"), html.Th("Action"),
                        ])
                    ),
                    html.Tbody([
                        html.Tr([
                            html.Td(
                                row.get("timestamp") or "—",
                                className="tracklist-time",
                            ),
                            html.Td(
                                row.get("artist") or "—",
                                className="tracklist-artist",
                            ),
                            html.Td(
                                row.get("title") or "—",
                                className="tracklist-title",
                            ),
                            html.Td(
                                dcc.Dropdown(
                                    id={"type": "watched-track-match", "row": row["row_id"]},
                                    options=[
                                        {
                                            "label": candidate.get("label") or candidate.get("id"),
                                            "value": candidate.get("id"),
                                        }
                                        for candidate in row.get("matches") or []
                                    ],
                                    value=row.get("selected_id") or None,
                                    clearable=False,
                                    disabled=not bool(row.get("matches")),
                                    className="tracklist-match-select",
                                ),
                                className="tracklist-match",
                            ),
                            html.Td(
                                str(row.get("status") or "").replace("_", " ").title(),
                                className=f"tracklist-state state-{row.get('status') or 'unknown'}",
                            ),
                            html.Td(
                                html.Div(
                                    [
                                        html.Button(
                                            "Liked ✓"
                                            if row.get("status") == "imported"
                                            else "♥ Like",
                                            id={
                                                "type": "watched-track-like",
                                                "row": row["row_id"],
                                            },
                                            disabled=(
                                                row.get("status") == "imported"
                                                or not bool(row.get("matches"))
                                            ),
                                            className="tracklist-like",
                                        ),
                                        html.Button(
                                            "Watching ✓"
                                            if row.get("status") == "watching"
                                            else "Watch",
                                            id={
                                                "type": "watched-track-watch",
                                                "row": row["row_id"],
                                            },
                                            disabled=row.get("status") in {
                                                "imported", "watching", "invalid", "unresolved"
                                            },
                                            className="tracklist-watch",
                                        ),
                                    ],
                                    className="tracklist-actions",
                                )
                            ),
                        ], **(
                            {"data-track-start-time": str(row.get("timestamp"))}
                            if row.get("timestamp") else {}
                        ))
                        for row in rows
                    ]),
                ],
                className="track-table tracklist-table",
            ),
            className="track-table-wrap tracklist-table-wrap",
        )

    @callback(
        Output("watched-tracklist-draft", "data"),
        Output("watched-tracklist-status", "children"),
        Output("liked-refresh", "n_clicks"),
        Input("watched-tracklist-parse", "n_clicks"),
        Input("watched-tracklist-search", "n_clicks"),
        Input({"type": "watched-track-like", "row": ALL}, "n_clicks"),
        Input({"type": "watched-track-watch", "row": ALL}, "n_clicks"),
        State("watched-tracklist-input", "value"),
        State("watched-tracklist-order", "value"),
        State("watched-tracklist-draft", "data"),
        State({"type": "watched-track-match", "row": ALL}, "value"),
        State({"type": "watched-track-match", "row": ALL}, "id"),
        State("watched-mix-record", "data"),
        State("liked-refresh", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_tracklist(
        parse_clicks, search_clicks, like_clicks, watch_clicks, text, order, rows,
        selected_matches, match_ids, mix_record, refresh_clicks,
    ):
        trigger = ctx.triggered_id
        if trigger == "watched-tracklist-parse":
            if not parse_clicks:
                return no_update, no_update, no_update
            parsed = parse_tracklist(text or "", order or "artist_title")
            valid = sum(
                row["status"] not in {"invalid", "unresolved"} for row in parsed
            )
            return parsed, f"Parsed {len(parsed)} lines; {valid} ready to search.", no_update

        rows = [dict(row) for row in (rows or [])]
        if trigger == "watched-tracklist-search":
            if not search_clicks or not rows:
                return no_update, "Parse a tracklist first.", no_update
            try:
                session = engine.tidal_client(interactive=False)
                delay = max(
                    0.0,
                    float(engine.load_config().get("settings", {}).get(
                        "tidal_search_delay_seconds", 0.35
                    )),
                )
                searchable = [
                    row for row in rows
                    if row.get("status") not in {
                        "invalid", "unresolved", "imported", "watching"
                    }
                ]
                for index, row in enumerate(searchable):
                    matches = find_tidal_matches(engine, session, row)
                    row["matches"] = matches
                    row["selected_id"] = matches[0]["id"] if matches else ""
                    row["status"] = (
                        "matched"
                        if matches and int(matches[0].get("score", 0)) >= 8
                        else "ambiguous" if matches else "not_found"
                    )
                    if delay and index + 1 < len(searchable):
                        time.sleep(delay)
                matched = sum(bool(row.get("matches")) for row in searchable)
                return (
                    rows,
                    f"Found candidates for {matched}/{len(searchable)} searched tracks.",
                    no_update,
                )
            except Exception as exc:
                engine.LOGGER.exception("ui.watched_mix tracklist_search_failed")
                return rows, f"TIDAL search failed: {exc}", no_update

        if isinstance(trigger, dict) and trigger.get("type") == "watched-track-like":
            if not any(like_clicks or []):
                return no_update, no_update, no_update
            row_id = int(trigger.get("row"))
            selections = {
                int(identity.get("row")): value
                for identity, value in zip(match_ids or [], selected_matches or [])
            }
            selected_id = str(selections.get(row_id) or "")
            row = next((item for item in rows if int(item["row_id"]) == row_id), None)
            candidate = next(
                (
                    item for item in (row or {}).get("matches", [])
                    if str(item.get("id")) == selected_id
                ),
                None,
            )
            if not row or not candidate or not mix_record:
                return rows, "Choose a valid TIDAL match first.", no_update
            try:
                session = engine.tidal_client(interactive=False)
                engine._call(
                    "tidal",
                    "favorite_track_from_watched_mix",
                    lambda: session.user.favorites.add_track(selected_id),
                    track_id=selected_id,
                    watched_mix=mix_record.get("video_id", ""),
                )
                local_added = add_tidal_liked_track(str(session.user.id), candidate)
                associated = associate_tidal_tracks_with_watched_mix(
                    str(mix_record.get("video_id") or ""), [selected_id]
                )
                row["selected_id"] = selected_id
                row["status"] = "imported"
                message = (
                    f"Liked {candidate.get('label') or selected_id} on TIDAL; "
                    f"{'added to' if local_added else 'already in'} the local liked cache; "
                    f"{'associated with' if associated else 'already associated with'} this mix."
                )
                return rows, message, int(refresh_clicks or 0) + 1
            except Exception as exc:
                engine.LOGGER.exception(
                    "ui.watched_mix tracklist_like_failed track_id=%s", selected_id
                )
                return rows, f"Like failed: {exc}", no_update

        if isinstance(trigger, dict) and trigger.get("type") == "watched-track-watch":
            if not any(watch_clicks or []):
                return no_update, no_update, no_update
            row_id = int(trigger.get("row"))
            row = next((item for item in rows if int(item["row_id"]) == row_id), None)
            if not row or not mix_record:
                return rows, "Could not identify the track or watched mix.", no_update
            try:
                _pending, added = add_pending_track(
                    str(mix_record.get("video_id") or ""),
                    str(row.get("artist") or ""),
                    str(row.get("title") or ""),
                    mix_position=str(row.get("timestamp") or ""),
                    raw_line=str(row.get("raw_line") or ""),
                )
                row["status"] = "watching"
                return (
                    rows,
                    "Added to Pending tracks."
                    if added else "That track is already being watched.",
                    no_update,
                )
            except Exception as exc:
                engine.LOGGER.exception("ui.watched_mix pending_track_add_failed")
                return rows, f"Could not watch track: {exc}", no_update
        return no_update, no_update, no_update
