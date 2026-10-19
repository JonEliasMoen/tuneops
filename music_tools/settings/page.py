"""Settings page for track-table Quick Views."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from music_library.database import lastfm_import_summary
from music_tools.lastfm import import_scrobbles
from music_tools.track_browser.table import columns_for, default_visible_fields


DEFAULT_QUICK_VIEWS = [
    {
        "id": "default",
        "name": "Default",
        "fields": default_visible_fields(None),
        "default": True,
    }
]


def _normalized(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    default_seen = False
    for index, row in enumerate(rows or []):
        view_id = str(row.get("id") or f"view-{index + 1}")
        is_default = bool(row.get("default")) and not default_seen
        default_seen = default_seen or is_default
        result.append(
            {
                "id": view_id,
                "name": str(row.get("name") or f"View {index + 1}"),
                "fields": list(dict.fromkeys(row.get("fields") or [])),
                "default": is_default,
            }
        )
    return result


def _form_rows(names, name_ids, fields, selected_default, stored):
    """Preserve the currently mounted editor values before a draft mutation."""
    existing = {view["id"]: view for view in _normalized(stored)}
    rows = []
    for index, identity in enumerate(name_ids or []):
        view_id = str(identity.get("id"))
        selected_fields = fields[index] if fields and index < len(fields) else []
        rows.append(
            {
                "id": view_id,
                "name": (
                    (names[index] if names and index < len(names) else "") or ""
                ).strip()
                or existing.get(view_id, {}).get("name")
                or "Untitled view",
                "fields": list(dict.fromkeys(selected_fields or [])),
                "default": view_id == selected_default,
            }
        )
    return rows


def _append_quick_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new draft with one predictably identified Quick View appended."""
    result = [dict(row) for row in rows]
    used = {row["id"] for row in result}
    number = 1
    while f"view-{number}" in used:
        number += 1
    result.append(
        {
            "id": f"view-{number}",
            "name": f"View {number}",
            "fields": default_visible_fields(None),
            "default": not result,
        }
    )
    return result


def _lastfm_summary_text(username: str) -> str:
    summary = lastfm_import_summary(username)
    if not summary["scrobbles"]:
        return "No Last.fm listening history imported yet."
    latest = (
        datetime.fromtimestamp(summary["latest"]).strftime("%Y-%m-%d %H:%M")
        if summary.get("latest")
        else "unknown"
    )
    return (
        f"{summary['scrobbles']:,} scrobbles cached · "
        f"{summary['matched']:,} matched to indexed TIDAL tracks · "
        f"latest {latest}"
    )


def _editor(views, html, dcc, all_columns):
    """Build the complete editor so the first render never depends on a callback."""
    views = _normalized(views)
    if not views:
        return (
            html.Div(
                "No Quick Views yet. Add one to get started.",
                className="detail-empty",
            ),
            [],
            None,
        )
    default_id = next((view["id"] for view in views if view.get("default")), None)
    cards = [
        html.Div(
            [
                html.Div(
                    [
                        dcc.Input(
                            id={"type": "quick-view-name", "id": view["id"]},
                            value=view["name"],
                            type="text",
                            placeholder="Quick View name",
                            className="quick-view-name",
                        ),
                        html.Button(
                            "Remove",
                            id={"type": "quick-view-delete", "id": view["id"]},
                            className="danger",
                        ),
                    ],
                    className="quick-view-settings-head",
                ),
                dcc.Checklist(
                    id={"type": "quick-view-fields", "id": view["id"]},
                    options=[{"label": label, "value": key} for key, label in all_columns],
                    value=view["fields"],
                    className="quick-view-fields",
                ),
            ],
            className="quick-view-settings-card",
        )
        for view in views
    ]
    return (
        cards,
        [{"label": f" {view['name']}", "value": view["id"]} for view in views],
        default_id,
    )


def content(
    html: Any,
    dcc: Any,
    quick_views: list[dict[str, Any]] | None = None,
    dark_mode: bool = True,
    tags_collapsed_default: bool = True,
    lastfm_username: str = "",
):
    editor, default_options, default_value = _editor(
        quick_views, html, dcc, columns_for({"type": "setlist"})
    )
    return [
        dcc.Store(id="quick-view-draft", data=_normalized(quick_views)),
        html.Div(
            [
                html.H1("Settings"),
                html.P(
                    "Create reusable field sets for every track table. Settings are saved in SQLite."
                ),
            ],
            className="tool-heading",
        ),
        html.Div(
            [
                html.H2("Appearance"),
                dcc.Checklist(
                    id="dark-mode-toggle",
                    options=[{"label": " Dark mode", "value": "dark"}],
                    value=["dark"] if dark_mode else [],
                    className="dark-mode-toggle",
                ),
                dcc.Checklist(
                    id="tags-collapsed-toggle",
                    options=[
                        {
                            "label": " Tags collapsed by default",
                            "value": "collapsed",
                        }
                    ],
                    value=["collapsed"] if tags_collapsed_default else [],
                    className="dark-mode-toggle",
                ),
            ],
            className="settings-section",
        ),
        html.Div(
            [
                html.H2("Last.fm"),
                html.P(
                    "Import listening history into SQLite for local play counts and future monthly charts.",
                    className="hint",
                ),
                html.Div(
                    "API key configured in .env"
                    if os.getenv("LASTFM_API_KEY", "").strip()
                    else "Add LASTFM_API_KEY to .env, then restart the app.",
                    className=(
                        "connection connected"
                        if os.getenv("LASTFM_API_KEY", "").strip()
                        else "connection disconnected"
                    ),
                ),
                html.Label("Last.fm username"),
                dcc.Input(
                    id="lastfm-username",
                    value=lastfm_username,
                    type="text",
                    placeholder="Your Last.fm username",
                    className="quick-view-name lastfm-username",
                ),
                html.Div(
                    [
                        html.Button("Save username", id="lastfm-save"),
                        html.Button(
                            "Import listening history",
                            id="lastfm-import",
                            className="primary",
                        ),
                    ],
                    className="actions",
                ),
                dcc.Loading(
                    html.Div(
                        _lastfm_summary_text(lastfm_username),
                        id="lastfm-status",
                        className="track-status",
                    ),
                    type="circle",
                ),
            ],
            className="settings-section",
        ),
        html.H2("Quick Views"),
        html.Div(
            [
                html.Label("Default Quick View"),
                dcc.RadioItems(
                    id="quick-view-default",
                    options=default_options,
                    value=default_value,
                    className="quick-view-default",
                ),
            ],
            className="quick-view-default-picker",
        ),
        html.Div(editor, id="quick-view-settings-list"),
        html.Div(
            [
                html.Button("Add quick view", id="quick-view-add"),
                html.Button("Save settings", id="quick-view-save", className="primary"),
            ],
            className="actions",
        ),
        html.Div(id="quick-view-settings-status", className="track-status"),
    ]


def register_callbacks(
    callback, Input, Output, State, ALL, html, dcc, ctx, no_update, engine
):
    all_columns = columns_for({"type": "setlist"})

    @callback(
        Output("lastfm-status", "children"),
        Input("lastfm-save", "n_clicks"),
        Input("lastfm-import", "n_clicks"),
        State("lastfm-username", "value"),
        prevent_initial_call=True,
        running=[(Output("lastfm-import", "disabled"), True, False)],
    )
    def update_lastfm(_save_clicks, _import_clicks, username):
        username = str(username or "").strip()
        if not username:
            return "Enter your Last.fm username."
        config = engine.load_config()
        settings = config.setdefault("settings", {})
        settings["lastfm_username"] = username
        engine.save_config(config)
        if ctx.triggered_id == "lastfm-save":
            return f"Saved Last.fm username {username}. {_lastfm_summary_text(username)}"
        try:
            result = import_scrobbles(
                username,
                os.getenv("LASTFM_API_KEY", ""),
                delay_seconds=float(
                    settings.get("lastfm_import_delay_seconds", 0.5)
                ),
            )
            summary = _lastfm_summary_text(username)
            return (
                f"Import complete: {result['added']:,} new of "
                f"{result['fetched']:,} fetched; "
                f"{result['scrobbles_matched']:,} plays newly matched. {summary}"
            )
        except Exception as exc:
            engine.LOGGER.exception("lastfm.import_failed username=%r", username)
            return f"Last.fm import failed: {exc}"

    @callback(
        Output("theme-settings", "data"),
        Input("dark-mode-toggle", "value"),
        prevent_initial_call=True,
    )
    def save_dark_mode(values):
        enabled = "dark" in (values or [])
        config = engine.load_config()
        config.setdefault("settings", {})["dark_mode"] = enabled
        engine.save_config(config)
        return {"dark_mode": enabled}

    @callback(
        Output("ui-preferences", "data"),
        Input("tags-collapsed-toggle", "value"),
        prevent_initial_call=True,
    )
    def save_tags_collapsed_default(values):
        enabled = "collapsed" in (values or [])
        config = engine.load_config()
        config.setdefault("settings", {})["tags_collapsed_by_default"] = enabled
        engine.save_config(config)
        return {"tags_collapsed": enabled}

    @callback(
        Output("quick-view-settings-list", "children"),
        Output("quick-view-default", "options"),
        Output("quick-view-default", "value"),
        Input("quick-view-draft", "data"),
    )
    def render_quick_views(rows):
        return _editor(rows, html, dcc, all_columns)

    @callback(
        Output("quick-view-draft", "data"),
        Output("quick-views", "data"),
        Output("quick-view-settings-status", "children"),
        Input("quick-view-add", "n_clicks"),
        Input("quick-view-save", "n_clicks"),
        Input({"type": "quick-view-delete", "id": ALL}, "n_clicks"),
        State({"type": "quick-view-name", "id": ALL}, "value"),
        State({"type": "quick-view-name", "id": ALL}, "id"),
        State({"type": "quick-view-fields", "id": ALL}, "value"),
        State("quick-view-default", "value"),
        State("quick-view-draft", "data"),
        prevent_initial_call=True,
    )
    def update_quick_views(
        _add, _save, _deletes, names, name_ids, fields, selected_default, stored
    ):
        triggered = ctx.triggered_id
        if not triggered:
            return no_update, no_update, no_update
        if triggered == "quick-view-add" and not _add:
            return no_update, no_update, no_update
        if triggered == "quick-view-save" and not _save:
            return no_update, no_update, no_update
        if (
            isinstance(triggered, dict)
            and triggered.get("type") == "quick-view-delete"
            and not any(_deletes or [])
        ):
            return no_update, no_update, no_update
        rows = _form_rows(
            names, name_ids, fields, selected_default, stored
        )

        if isinstance(triggered, dict) and triggered.get("type") == "quick-view-delete":
            deleted_id = str(triggered.get("id"))
            rows = [row for row in rows if row["id"] != deleted_id]
            return rows, no_update, "Quick View removed from the draft. Save to keep this change."
        if triggered == "quick-view-add":
            rows = _append_quick_view(rows)
            return rows, no_update, "Quick View added. Choose its fields, then save."
        config = engine.load_config()
        config["quick_views"] = rows
        engine.save_config(config)
        return rows, rows, f"Saved {len(rows)} Quick View(s) to {engine.CONFIG_PATH}."
