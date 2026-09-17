"""Shared application shell and navigation for all music tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from music_library.database import tidal_indexed_playlists
from music_tools.mixes.service import discover_mixes


def sidebar(html: Any, active: str):
    items = [
        ("playlist-sync", "⇄", "Playlist sync", "/"),
        ("liked-tracks", "♥", "Liked tracks", "/liked-tracks"),
    ]
    indexed = tidal_indexed_playlists()
    tool_links = [
        html.A(
            [html.Span(icon, className="nav-icon"), html.Span(label)],
            href=href,
            className="nav-item active" if key == active else "nav-item",
            **{"data-sidebar-index": str(index), "data-sidebar-href": href},
        )
        for index, (key, icon, label, href) in enumerate(items)
    ]
    next_index = len(items)

    def collection_group(label, key, records, route_prefix, active_prefix, icon="♫"):
        nonlocal next_index
        if not records:
            return []
        parent_index = next_index
        next_index += 1
        children = []
        for record in records:
            record_id = str(record["id"])
            href = f"/{route_prefix}/{record_id}"
            children.append(
                html.A(
                    [html.Span(icon, className="nav-icon"), html.Span(record.get("name") or record_id)],
                    href=href,
                    className=(
                        "nav-item playlist-nav active"
                        if f"{active_prefix}:{record_id}" == active
                        else "nav-item playlist-nav"
                    ),
                    title=record.get("name") or record_id,
                    **{
                        "data-sidebar-index": str(next_index),
                        "data-sidebar-href": href,
                    },
                )
            )
            next_index += 1
        return [
            html.Details(
                [
                    html.Summary(
                        [html.Span("▸", className="nav-chevron"), html.Span(label)],
                        className="nav-item playlist-toggle",
                        **{
                            "data-sidebar-index": str(parent_index),
                            "data-sidebar-toggle": key,
                        },
                    ),
                    html.Div(children, className="playlist-nav-list"),
                ],
                open=active.startswith(f"{active_prefix}:"),
                className="playlist-group",
            )
        ]

    collection_groups = []
    for label, key, route_prefix, active_prefix, kind in (
        ("Playlists", "playlists", "playlists", "playlist", "playlist"),
        ("Events", "events", "events", "event", "event"),
        ("Sources", "sources", "sources", "source", "source"),
    ):
        records = [item for item in indexed if item.get("collection_type") == kind]
        collection_groups.extend(
            collection_group(label, key, records, route_prefix, active_prefix)
        )
    mixes = discover_mixes()
    mix_index = next_index
    mix_group = [
        html.Details(
            [
                html.Summary(
                    [html.Span("▸", className="nav-chevron"), html.Span("Mixes")],
                    className="nav-item playlist-toggle",
                    **{
                        "data-sidebar-index": str(mix_index),
                        "data-sidebar-toggle": "mixes",
                    },
                ),
                html.Div(
                    [
                        html.A(
                            [html.Span("♪", className="nav-icon"), html.Span(mix.folder_name)],
                            href=f"/mixes/{quote(mix.folder_name, safe='')}",
                            className=(
                                "nav-item playlist-nav active"
                                if f"mix:{mix.folder_name}" == active
                                else "nav-item playlist-nav"
                            ),
                            title=mix.folder_name,
                            **{
                                "data-sidebar-index": str(mix_index + index + 1),
                                "data-sidebar-href": f"/mixes/{quote(mix.folder_name, safe='')}",
                            },
                        )
                        for index, mix in enumerate(mixes)
                    ],
                    className="playlist-nav-list",
                ),
            ],
            open=active.startswith("mix:"),
            className="playlist-group",
        )
    ]
    return html.Aside(
        [
            html.Div(
                [html.Span("♪", className="brand-mark"), html.Span("Music tools")],
                className="brand",
            ),
            html.Nav(
                [*tool_links, *collection_groups, *mix_group],
                className="side-nav",
                **{"aria-label": "Main navigation"},
            ),
        ],
        id="app-sidebar",
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
.sidebar{overflow-y:auto}
.playlist-group{margin-top:10px}
.playlist-toggle{list-style:none;cursor:pointer}
.playlist-toggle::-webkit-details-marker{display:none}
.nav-chevron{display:inline-block;font-size:13px;transition:transform .15s ease}
.playlist-group[open] .nav-chevron{transform:rotate(90deg)}
.playlist-nav-list{display:flex;flex-direction:column;gap:3px;margin-top:3px}
.playlist-nav{padding-left:18px;font-size:14px}
.playlist-nav span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-item.keyboard-selected{outline:2px solid #63dca8;outline-offset:-2px}
.library-layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:start}
.track-list-pane{min-width:0}
.library-layout .track-table-wrap{height:calc(100vh - 220px);max-height:none}
.track-column-remix{width:140px;max-width:140px;overflow:hidden;text-overflow:ellipsis}
.sortable-column{cursor:pointer;user-select:none}.sortable-column:hover{color:#fff;background:#3a454f}.sort-indicator{display:inline-block;min-width:13px;margin-left:6px;color:#65dbab;font-size:10px}
.track-toolbar{display:flex;align-items:center;gap:4px}.field-picker{position:relative}.field-picker-menu{position:absolute;right:0;top:calc(100% + 5px);z-index:20;min-width:190px;max-height:360px;overflow:auto;padding:10px;border:1px solid #46586b;border-radius:9px;background:#101923;box-shadow:0 12px 32px #0008}.field-picker-options label{display:block;padding:6px 8px;border-radius:5px;color:#dbe3ea;white-space:nowrap}.field-picker-options label:hover{background:#202d39}.field-picker-options input{margin-right:8px}
.liked-track-row{cursor:pointer;outline:none}
.track-table tbody .liked-track-row.selected{background:#2c4655}
.track-table tbody .liked-track-row.selected:hover{background:#2c4655}
.inspector-column{position:sticky;top:20px;display:grid;gap:14px}
.track-details{box-sizing:border-box;min-height:300px;max-height:calc(100vh - 190px);overflow:auto;padding:20px;background:#18222d;border:1px solid #344252;border-radius:9px}
.selected-album-art{display:block;width:100%;aspect-ratio:1;object-fit:cover;margin:0 0 18px;border-radius:7px;background:#0d151e}
.track-actions{box-sizing:border-box;padding:18px;background:#18222d;border:1px solid #344252;border-radius:9px}
.track-actions h2{margin:0 0 12px;font-size:18px}
.action-prompt{margin-bottom:10px;color:#91a0af;font-size:13px}
.action-option{padding:9px 10px;margin:3px 0;border:1px solid transparent;border-radius:7px;color:#c7d0d9;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.action-option:hover{background:#202d39}
.action-option.selected{border-color:#4fcf98;background:#17372c;color:#82edbd}
.action-feedback{min-height:18px;margin-top:10px;color:#82edbd;font-size:13px}
.detail-eyebrow{color:#7f91a1;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.detail-title{margin:12px 0 5px;color:#fff;font-size:22px;line-height:1.2}
.detail-artist{color:#bdc8d2;margin-bottom:24px}
.detail-fields{display:grid;gap:0}
.detail-field{display:grid;grid-template-columns:95px minmax(0,1fr);gap:10px;padding:10px 0;border-top:1px solid #2b3743}
.detail-field span{color:#7f91a1}
.detail-field strong{overflow-wrap:anywhere;color:#e8edf2;font-weight:500}
.detail-empty{color:#7f91a1}
.detail-dimension{grid-template-columns:1fr}
.dimension-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.dimension-tag{padding:4px 7px;border:1px solid #48586a;border-radius:6px;background:#202a35;color:#dbe3ea;font-size:12px}
.dimension-tag.editable{cursor:pointer;user-select:none}.dimension-tag.editable:hover{border-color:#65dbab;background:#263a36}.dimension-tag.editable.selected{border-color:#4fcf98;background:#17372c;color:#82edbd}
.detail-playlists{grid-template-columns:1fr}
.playlist-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.playlist-tag{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;padding:5px 8px;border:1px solid #3e6255;border-radius:999px;background:#17372c;color:#78e8b6;font-size:12px;white-space:nowrap}
.table-playlist-tags{flex-wrap:nowrap;margin-top:0;max-width:320px;overflow:hidden}
.scroll-sentinel{padding:14px;text-align:center;color:#7f91a1;font-size:13px}
.mix-list{display:grid;gap:20px;margin-top:20px}
.mix-card{display:grid;grid-template-columns:minmax(220px,340px) minmax(0,1fr);gap:24px;padding:20px;border:1px solid #344252;border-radius:12px;background:#18222d}
.mix-cover-container{width:100%}.mix-cover{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:9px;background:#0d151e}
.mix-cover-empty{display:grid;place-items:center;color:#7f91a1}
.mix-body{min-width:0}.mix-title{margin:0 0 5px;color:#fff}.mix-file-state{margin-bottom:20px;color:#6be8ae;font-size:13px}.mix-file-state.missing{color:#e5a66d}
.mix-heading{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap}.mix-heading h1{margin-bottom:12px}.mix-youtube-title,.mix-tidal-title{margin:0;color:#e8edf2;font-size:22px;font-weight:500}.mix-tidal-title{color:#65dbab}.mix-youtube-views{min-height:20px;margin:0 0 14px;color:#91a0af;font-size:14px}
.mix-tidal-heading{margin:16px 0 0}.mix-track-browser{margin-top:28px}.mix-track-browser:empty{display:none}
.mix-youtube-input{box-sizing:border-box;width:100%;margin-top:7px;padding:11px 12px;border:1px solid #46586b;border-radius:7px;background:#0d151e;color:#e8edf2;font:inherit}
.mix-youtube-input:focus{outline:2px solid #35e0a1;border-color:transparent}.mix-save{margin:10px 8px 14px 0}.mix-save-status{color:#82edbd;font-size:13px}
.mix-positions{max-height:360px;margin:8px 0 0;overflow:auto;line-height:1.7;white-space:pre-wrap}
@media(max-width:1000px){.library-layout{grid-template-columns:1fr}.library-layout .track-table-wrap{height:60vh}.inspector-column{position:static}.track-details{min-height:0}}
@media(max-width:800px){.mix-card{grid-template-columns:1fr}.mix-cover{max-width:360px}}
</style>
<script>
(function() {
    var selectedIndex = null;
    var sidebarFocused = false;

    function hasSidebar() {
        return Boolean(document.querySelector('[data-sidebar-index]'));
    }

    function visibleItems() {
        return Array.from(document.querySelectorAll('[data-sidebar-index]')).filter(
            function(item) { return item.offsetParent !== null; }
        );
    }

    function visibleTopLevelItems() {
        return Array.from(document.querySelectorAll(
            '.side-nav > [data-sidebar-index], ' +
            '.side-nav > details > summary[data-sidebar-index]'
        )).filter(function(item) { return item.offsetParent !== null; });
    }

    function paintSidebarSelection() {
        document.querySelectorAll('[data-sidebar-index]').forEach(function(item) {
            item.classList.toggle(
                'keyboard-selected',
                sidebarFocused && Number(item.dataset.sidebarIndex) === selectedIndex
            );
        });
    }

    function enterSidebar() {
        sidebarFocused = true;
        var active = document.querySelector('[data-sidebar-index].active');
        var mixToggle = document.querySelector('[data-sidebar-toggle="mixes"]');
        var first = visibleItems()[0];
        var target = active || mixToggle || first;
        selectedIndex = target ? Number(target.dataset.sidebarIndex) : null;
        paintSidebarSelection();
        if (target) target.scrollIntoView({block: 'nearest'});
    }

    document.addEventListener('click', function(event) {
        if (!hasSidebar()) return;
        var item = event.target.closest('[data-sidebar-index]');
        if (!item) {
            sidebarFocused = false;
            paintSidebarSelection();
            return;
        }
        sidebarFocused = true;
        selectedIndex = Number(item.dataset.sidebarIndex);
        window.setTimeout(paintSidebarSelection, 0);
    });

    document.addEventListener('keydown', function(event) {
        if (!hasSidebar()) return;
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;

        if (!sidebarFocused) {
            if (event.key === 'ArrowLeft') {
                if (window.__likedTracksFocus === 'actions') return;
                event.preventDefault();
                event.stopImmediatePropagation();
                enterSidebar();
            }
            return;
        }

        var items = visibleItems();
        if (!items.length) return;
        if (event.key === 'ArrowLeft') {
            var current = items.find(function(item) {
                return Number(item.dataset.sidebarIndex) === selectedIndex;
            });
            var parentDetails = current && current.closest('details');
            event.preventDefault();
            event.stopImmediatePropagation();
            if (parentDetails && !current.dataset.sidebarToggle) {
                var parentSummary = parentDetails.querySelector(
                    ':scope > summary[data-sidebar-index]'
                );
                parentDetails.open = false;
                if (parentSummary) {
                    selectedIndex = Number(parentSummary.dataset.sidebarIndex);
                    paintSidebarSelection();
                    parentSummary.scrollIntoView({block: 'nearest'});
                }
            } else if (parentDetails && current.dataset.sidebarToggle) {
                parentDetails.open = false;
                paintSidebarSelection();
            }
            return;
        }
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            event.preventDefault();
            event.stopImmediatePropagation();
            var currentItem = items.find(function(item) {
                return Number(item.dataset.sidebarIndex) === selectedIndex;
            });
            var currentDetails = currentItem && currentItem.closest('details');
            if (
                event.key === 'ArrowDown' &&
                currentItem && currentItem.dataset.sidebarToggle &&
                currentDetails && currentDetails.open
            ) {
                var firstVisibleChild = currentDetails.querySelector(
                    '.playlist-nav-list [data-sidebar-index]'
                );
                if (firstVisibleChild) {
                    selectedIndex = Number(firstVisibleChild.dataset.sidebarIndex);
                    paintSidebarSelection();
                    firstVisibleChild.scrollIntoView({block: 'nearest'});
                    return;
                }
            }
            var navigationItems = currentItem && currentItem.dataset.sidebarToggle
                ? visibleTopLevelItems() : items;
            var position = navigationItems.findIndex(function(item) {
                return Number(item.dataset.sidebarIndex) === selectedIndex;
            });
            if (position < 0) position = 0;
            var delta = event.key === 'ArrowDown' ? 1 : -1;
            position = Math.max(0, Math.min(navigationItems.length - 1, position + delta));
            selectedIndex = Number(navigationItems[position].dataset.sidebarIndex);
            paintSidebarSelection();
            navigationItems[position].scrollIntoView({block: 'nearest'});
            return;
        }

        if (event.key !== 'Enter' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        event.stopImmediatePropagation();
        var selected = items.find(function(item) {
            return Number(item.dataset.sidebarIndex) === selectedIndex;
        }) || items[0];
        if (selected.dataset.sidebarToggle) {
            var details = selected.closest('details');
            if (details) {
                details.open = event.key === 'Enter' ? !details.open : true;
                window.setTimeout(paintSidebarSelection, 0);
            }
            return;
        }
        var href = selected.dataset.sidebarHref;
        if (href) window.location.assign(href);
    }, true);
})();
</script>
</head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""
