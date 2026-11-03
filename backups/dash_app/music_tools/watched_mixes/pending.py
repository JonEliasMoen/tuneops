"""Persistent release-watch queue for tracks discovered in watched mixes."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from music_library.database import (
    add_tidal_liked_track,
    associate_tidal_tracks_with_watched_mix,
    delete_pending_track,
    pending_track,
    pending_tracks,
    resolve_pending_track,
    update_pending_track_candidates,
)
from .tracklist import find_tidal_matches


def content(html: Any, dcc: Any):
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.H1("Pending tracks"),
                        html.P(
                            "Tracks from watched mixes that you want to find on TIDAL later.",
                            className="hint",
                        ),
                    ]
                ),
                html.Button(
                    "Refresh from TIDAL",
                    id="pending-refresh",
                    className="primary",
                ),
            ],
            className="tool-heading",
        ),
        dcc.Interval(
            id="pending-initial-load", interval=250, max_intervals=1, n_intervals=0
        ),
        dcc.Store(id="pending-revision", data=0),
        html.Div(id="pending-feedback", className="action-feedback"),
        html.Div(id="pending-status", className="track-status"),
        html.Div(id="pending-table"),
    ]


def _date(value: Any) -> str:
    return str(value or "").replace("T", " ")[:16]


def _table(html: Any, dcc: Any, rows: list[dict[str, Any]]):
    if not rows:
        return html.Div(
            "Nothing pending. Use Watch on a parsed watched-mix track.",
            className="detail-empty",
        )
    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Artist"),
                            html.Th("Title"),
                            html.Th("Watched mix"),
                            html.Th("Position"),
                            html.Th("TIDAL candidate"),
                            html.Th("Last checked"),
                            html.Th("Actions"),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(row.get("artist") or "—"),
                                html.Td(row.get("title") or "—"),
                                html.Td(
                                    html.A(
                                        row.get("mix_title")
                                        or row.get("channel_name")
                                        or row.get("video_id"),
                                        href=(
                                            "/watched-mixes/"
                                            + quote(str(row.get("video_id") or ""), safe="")
                                        ),
                                        className="watched-mix-link pending-mix-link",
                                    )
                                ),
                                html.Td(row.get("mix_position") or "—"),
                                html.Td(
                                    [
                                        dcc.Dropdown(
                                            id={
                                                "type": "pending-candidate",
                                                "id": int(row["id"]),
                                            },
                                            options=[
                                                {
                                                    "label": candidate.get("label")
                                                    or candidate.get("id"),
                                                    "value": candidate.get("id"),
                                                }
                                                for candidate in row.get("candidates") or []
                                            ],
                                            value=(
                                                (row.get("candidates") or [{}])[0].get("id")
                                                if row.get("candidates")
                                                else None
                                            ),
                                            clearable=False,
                                            disabled=not bool(row.get("candidates")),
                                            className="tracklist-match-select",
                                        ),
                                        html.Small(
                                            str(row.get("status") or "pending")
                                            .replace("_", " ")
                                            .title(),
                                            className=(
                                                "tracklist-state state-"
                                                + str(row.get("status") or "pending")
                                            ),
                                        ),
                                    ],
                                    className="pending-candidate-cell",
                                ),
                                html.Td(_date(row.get("last_checked_at")) or "Never"),
                                html.Td(
                                    [
                                        html.Button(
                                            "♥ Like",
                                            id={
                                                "type": "pending-like",
                                                "id": int(row["id"]),
                                            },
                                            disabled=not bool(row.get("candidates")),
                                            className="tracklist-like",
                                        ),
                                        html.Button(
                                            "Remove",
                                            id={
                                                "type": "pending-remove",
                                                "id": int(row["id"]),
                                            },
                                            className="danger",
                                        ),
                                    ],
                                    className="tracklist-actions",
                                ),
                            ]
                        )
                        for row in rows
                    ]
                ),
            ],
            className="track-table pending-track-table",
        ),
        className="track-table-wrap pending-track-table-wrap",
    )


def register_callbacks(callback, Input, Output, State, ALL, html, dcc, ctx, engine):
    from dash import no_update

    @callback(
        Output("pending-table", "children"),
        Output("pending-status", "children"),
        Input("pending-initial-load", "n_intervals"),
        Input("pending-refresh", "n_clicks"),
        Input("pending-revision", "data"),
    )
    def load_pending(_initial, _refresh, _revision):
        rows = pending_tracks()
        searched = False
        error = ""
        if ctx.triggered_id in {"pending-initial-load", "pending-refresh"} and rows:
            try:
                session = engine.tidal_client(interactive=False)
                delay = max(
                    0.0,
                    float(
                        engine.load_config()
                        .get("settings", {})
                        .get("tidal_search_delay_seconds", 0.35)
                    ),
                )
                for index, row in enumerate(rows):
                    candidates = find_tidal_matches(engine, session, row)
                    status = (
                        "matched"
                        if candidates and int(candidates[0].get("score", 0)) >= 8
                        else "ambiguous" if candidates else "not_found"
                    )
                    update_pending_track_candidates(row["id"], candidates, status)
                    if delay and index + 1 < len(rows):
                        time.sleep(delay)
                searched = True
                rows = pending_tracks()
            except Exception as exc:
                engine.LOGGER.exception("ui.pending_tracks tidal_refresh_failed")
                error = f" TIDAL refresh failed: {exc}"
        matched = sum(bool(row.get("candidates")) for row in rows)
        status = (
            f"{len(rows)} pending; {matched} with TIDAL candidates."
            + (" Refreshed from TIDAL." if searched else "")
            + error
        )
        return _table(html, dcc, rows), status

    @callback(
        Output("pending-revision", "data"),
        Output("pending-feedback", "children"),
        Input({"type": "pending-like", "id": ALL}, "n_clicks"),
        Input({"type": "pending-remove", "id": ALL}, "n_clicks"),
        State({"type": "pending-candidate", "id": ALL}, "value"),
        State({"type": "pending-candidate", "id": ALL}, "id"),
        State("pending-revision", "data"),
        prevent_initial_call=True,
    )
    def pending_action(like_clicks, remove_clicks, selections, selection_ids, revision):
        trigger = ctx.triggered_id
        if not isinstance(trigger, dict):
            return no_update, no_update
        pending_id = int(trigger.get("id"))
        if trigger.get("type") == "pending-remove":
            if not any(remove_clicks or []):
                return no_update, no_update
            delete_pending_track(pending_id)
            return int(revision or 0) + 1, "Removed from Pending tracks."
        if trigger.get("type") != "pending-like" or not any(like_clicks or []):
            return no_update, no_update
        selected = {
            int(identity.get("id")): value
            for identity, value in zip(selection_ids or [], selections or [])
        }.get(pending_id)
        record = pending_track(pending_id)
        candidate = next(
            (
                item
                for item in (record or {}).get("candidates", [])
                if str(item.get("id")) == str(selected or "")
            ),
            None,
        )
        if not record or not candidate:
            return no_update, "Choose a valid TIDAL candidate first."
        track_id = str(candidate["id"])
        try:
            session = engine.tidal_client(interactive=False)
            engine._call(
                "tidal",
                "favorite_pending_track",
                lambda: session.user.favorites.add_track(track_id),
                track_id=track_id,
                watched_mix=record.get("video_id", ""),
            )
            add_tidal_liked_track(str(session.user.id), candidate)
            associate_tidal_tracks_with_watched_mix(record["video_id"], [track_id])
            resolve_pending_track(pending_id)
            return int(revision or 0) + 1, (
                f"Liked {candidate.get('label') or track_id} and associated it "
                "with the watched mix."
            )
        except Exception as exc:
            engine.LOGGER.exception(
                "ui.pending_tracks like_failed pending_id=%s", pending_id
            )
            return no_update, f"Like failed: {exc}"

