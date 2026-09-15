"""Shared application shell and navigation for all music tools."""

from __future__ import annotations

from typing import Any


def sidebar(html: Any, active: str):
    items = [
        ("playlist-sync", "⇄", "Playlist sync", "/"),
        ("liked-tracks", "♥", "Liked tracks", "/liked-tracks"),
    ]
    return html.Aside(
        [
            html.Div(
                [html.Span("♪", className="brand-mark"), html.Span("Music tools")],
                className="brand",
            ),
            html.Nav(
                [
                    html.A(
                        [html.Span(icon, className="nav-icon"), html.Span(label)],
                        href=href,
                        className="nav-item active" if key == active else "nav-item",
                    )
                    for key, icon, label, href in items
                ],
                className="side-nav",
                **{"aria-label": "Main navigation"},
            ),
        ],
        className="sidebar",
    )


def shell(html: Any, active: str, content: list[Any]):
    return html.Div(
        [sidebar(html, active), html.Main(content, className="page-content")],
        className="app-shell",
    )


INDEX_STRING = """<!DOCTYPE html><html><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>body{margin:0;background:#0c1117;color:#e8edf2;font:16px system-ui}.app-shell{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;box-sizing:border-box;padding:26px 18px;background:#0a0f15;border-right:1px solid #26313d}.brand{display:flex;align-items:center;gap:10px;padding:0 10px 24px;font-size:19px;font-weight:700}.brand-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:#35e0a1;color:#07110d}.side-nav{display:flex;flex-direction:column;gap:6px}.nav-item{display:flex;align-items:center;gap:11px;padding:11px 13px;border-radius:9px;color:#aebbc7;text-decoration:none;font-weight:600}.nav-item:hover{background:#141e28;color:#fff}.nav-item.active{background:#17372c;color:#6be8ae}.nav-icon{font-size:20px}.page-content{box-sizing:border-box;width:calc(100% - 48px);max-width:1400px;margin:40px auto;padding:28px;background:#121a23;border-radius:18px;min-width:0}h1{color:#35e0a1}button{padding:10px 16px;margin:5px;border:0;border-radius:8px;cursor:pointer}.primary{background:#35e0a1}.danger{background:#48232a;color:#ffbdc5}.mapping-card{background:#18222d;border:1px solid #344252;border-radius:12px;padding:18px;margin:14px 0}.mapping-head{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:12px}.mapping-title{display:flex;flex-direction:column;gap:5px;flex:1}.mapping-name{box-sizing:border-box;width:min(430px,100%);padding:10px 12px;border:1px solid #46586b;border-radius:7px;background:#101923;color:#fff;font-size:18px;font-weight:600}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.field{display:flex;flex-direction:column;gap:6px;margin-top:14px}.field input{box-sizing:border-box;width:100%;padding:11px 12px;border:1px solid #46586b;border-radius:7px;background:#0d151e;color:#e8edf2;font:inherit}.field input:focus,.mapping-name:focus{outline:2px solid #35e0a1;border-color:transparent}label{color:#bdc8d2;font-size:14px}.direction-select{max-width:320px;color:#111}pre{background:#091016;padding:14px;border-radius:8px;white-space:pre-wrap}.actions,.connections{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.connection{padding:8px 12px;border-radius:999px;font-size:14px}.connected{color:#69e6a3;background:#123525}.disconnected{color:#aab5c0;background:#26313d}.hint{color:#91a0af;font-size:13px}.track-table-wrap{overflow:auto;max-height:calc(100vh - 220px);border:1px solid #344252;border-radius:9px}.track-table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}.track-table th{position:sticky;top:0;z-index:1;padding:9px 12px;background:#303840;color:#aebbc7;text-align:left;font-weight:600}.track-table td{padding:8px 12px;border-bottom:1px solid #202a34}.track-table tbody tr:nth-child(even){background:#18222d}.track-table tbody tr:hover{background:#21303c}.track-table .track-title,.track-table .track-artist{color:#45e6e6}.numeric{text-align:right!important;font-variant-numeric:tabular-nums}.tool-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.track-status{color:#91a0af;margin:6px 0 14px}@media(max-width:800px){.app-shell{display:block}.sidebar{position:static;width:100%;height:auto;padding:12px 16px;border-right:0;border-bottom:1px solid #26313d}.brand{padding:0 4px 10px}.side-nav{flex-direction:row;overflow-x:auto}.nav-item{padding:8px 11px;white-space:nowrap}.page-content{width:100%;margin:0;border-radius:0;padding:18px}.field-grid{grid-template-columns:1fr}}</style>
<style>
.page-content{width:100%;max-width:none;min-height:100vh;margin:0;border-radius:0}
.library-layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:start}
.track-list-pane{min-width:0}
.library-layout .track-table-wrap{height:calc(100vh - 220px);max-height:none}
.liked-track-row{cursor:pointer;outline:none}
.track-table tbody .liked-track-row.selected{background:#2c4655}
.track-table tbody .liked-track-row.selected:hover{background:#2c4655}
.track-details{position:sticky;top:20px;box-sizing:border-box;min-height:300px;padding:20px;background:#18222d;border:1px solid #344252;border-radius:9px}
.detail-eyebrow{color:#7f91a1;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.detail-title{margin:12px 0 5px;color:#fff;font-size:22px;line-height:1.2}
.detail-artist{color:#bdc8d2;margin-bottom:24px}
.detail-fields{display:grid;gap:0}
.detail-field{display:grid;grid-template-columns:95px minmax(0,1fr);gap:10px;padding:10px 0;border-top:1px solid #2b3743}
.detail-field span{color:#7f91a1}
.detail-field strong{overflow-wrap:anywhere;color:#e8edf2;font-weight:500}
.detail-empty{color:#7f91a1}
.detail-playlists{grid-template-columns:1fr}
.playlist-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.playlist-tag{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;padding:5px 8px;border:1px solid #3e6255;border-radius:999px;background:#17372c;color:#78e8b6;font-size:12px;white-space:nowrap}
.scroll-sentinel{padding:14px;text-align:center;color:#7f91a1;font-size:13px}
@media(max-width:1000px){.library-layout{grid-template-columns:1fr}.library-layout .track-table-wrap{height:60vh}.track-details{position:static;min-height:0}}
</style>
</head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""
