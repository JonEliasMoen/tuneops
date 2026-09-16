# MusicSync agent guide

This directory contains a local Dash application for TIDAL/Spotify music tools.
Preserve existing user configuration, OAuth caches, logs, and SQLite data. Never
commit or print secrets from `.env`, `.spotify_cache`, `.tidal_session.json`, or
`.connection_state.json`.

## Commands

- Web application: `python musicsync.py` (defaults to `127.0.0.1:8080`)
- Headless configured sync: `python startup_sync.py`
- Direct headless sync: `python musicsync.py --sync`
- Dependencies are declared in the repository-level `../requirements.txt`.

On this machine, the Microsoft Store Python aliases may return "access denied".
The working interpreter is:

```powershell
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -m compileall -q .
```

## Architecture

- `musicsync.py`: reusable playlist-sync engine, provider authentication, and
  backward-compatible CLI/application entry point.
- `startup_sync.py`: delayed, headless startup runner using `run_all_syncs`.
- `music_tools/ui.py`: shared full-width application shell, responsive sidebar,
  navigation, and global CSS.
- `music_tools/playlist_sync/page.py`: Dash app factory, URL routing, Spotify
  OAuth routes, playlist-sync layout, and callbacks.
- `music_tools/track_browser/`: stable, tool-neutral public API for the shared
  interactive track browser.
- `music_tools/liked_tracks/`: current track-browser implementation plus TIDAL
  liked/indexed-playlist retrieval; consumers outside this feature import the
  neutral `music_tools.track_browser` API.
- `music_tools/mixes/`: read-only local mix-folder discovery, cover serving,
  timestamp parsing, and locally persisted mix metadata.
- `music_library/database.py`: shared SQLite schema, TIDAL playlist cache,
  liked-track cache, reverse playlist membership lookup, and future user
  metadata storage.

New sidebar tools should live in `music_tools/<tool_name>/`. Keep provider and
database work outside presentation callbacks when practical. Shared layout and
styles belong in `music_tools/ui.py`.

## Track browser extension contract

- Reuse the browser through `music_tools.track_browser`; do not import its
  current `liked_tracks` implementation from another tool.
- Browser keyboard activation is based on the mounted
  `data-track-browser-root` marker, never route-name checks. A new route that
  embeds the browser must work without editing JavaScript route allowlists.
- Collection-specific columns belong in `EXTRA_COLUMNS_BY_COLLECTION` and are
  selected from `collection["type"]`; do not infer schemas from whichever rows
  happen to be loaded.
- Shared table headers are clickable and cycle ascending, descending, then off.
  Off restores `_source_order`; appending an infinite-scroll page reapplies the
  active sort and preserves selection by source order rather than row index.
- The Fields popover beside Refresh controls visible columns from the same
  declarative schema. Column-specific CSS must use semantic classes such as
  `track-column-remix`, never positional `nth-child` selectors.
- Rating, Energy, Vibe, Movement, Function, and Structure are available as
  optional Fields columns backed by `row["dimensions"]`. Keep them hidden by
  default, sortable when enabled, and synchronized with inspector edits.
- Keep collection descriptors JSON-serializable. The common keys are `type`,
  `id`, and `name`. Setlist timestamps come from SQLite membership rows rather
  than being carried in the collection descriptor.
- Register shared track-browser callbacks once in the application factory.
  Tools embed browser layouts but must not register duplicate callbacks.

## Playlist sync behavior

- Supports `spotify_to_tidal`, `tidal_to_spotify`, and `tidal_cache` mappings
  from `music_sync.json`. `tidal_cache` indexes the configured TIDAL playlist
  without modifying Spotify and does not require a Spotify connection when all
  enabled mappings are cache-only.
- New destination playlists default to the source playlist name.
- Matching prefers ISRC, then normalized title and artist.
- The engine diffs source and destination inventories before catalogue search.
- Previously unmatched tracks are persisted per mapping and direction.
- Spotify searches are throttled by `spotify_search_delay_seconds`.
- Sync is non-destructive: it adds missing tracks but does not propagate deletes.
- Spotify source changes use `snapshot_id`; TIDAL source changes use the cached
  playlist inventory/fingerprint.
- Logs include the human-readable mapping name and remote-call timing.

## SQLite library

The default database is `music_library.sqlite3`; `MUSICSYNC_DATABASE` can
override it. Database, WAL, and shared-memory files are ignored by Git.

Before applying any schema or data migration to the live database, tell the
user exactly what will change and wait for confirmation that the web app and
startup sync are stopped. Do not treat a requested database feature as implicit
permission to migrate the live file while it may be in use. Migrations against
new temporary test databases do not require this coordination.

Core tables:

- `tracks`: provider metadata keyed by provider and provider track ID.
- `playlists`: indexed playlist names and provider `last_updated` values.
- `playlist_tracks`: ordered membership and per-playlist `date_added`, with an
  index supporting track-to-playlists queries.
- `liked_track_snapshots` and `liked_tracks`: per-user ordered liked-track cache.
- `track_user_metadata`: reserved for star ratings and notes.
- `tags` and `track_tags`: normalized future tagging support.
- `setlists`: user-owned metadata for discovered local mix folders and their
  YouTube/TIDAL import-source mappings.
- `setlist_tracks`: ordered many-to-many setlist membership with the timestamp
  where each TIDAL track begins. Its track index supports reverse lookup from a
  track to every mix/setlist containing it.

## Mix explorer

- Routes: `/mixes` and `/mixes/<folder>`; `MUSICSYNC_MIX_ROOT` overrides the default
  `~/Documents/djstuff` directory.
- Mix folders appear as children of a collapsible **Mixes** sidebar node; each
  child route renders only that mix's cover, YouTube link, and positions.
- Each immediate child folder is one mix. `cover.png` and `positions.txt` are
  read when present; the conventional final audio filename is
  `<foldername>yt.wav`.
- Mix `cover.png` artwork uses a 16:9 landscape aspect ratio in the UI.
- Prefer a local `cover.png`; when it is absent and the saved YouTube URL is
  valid, show the video's YouTube thumbnail as the mix cover. Saving a new URL
  updates this fallback immediately and must never replace a local cover.
- The saved YouTube URL is user-owned SQLite metadata. Fetch its current title,
  view count, and upload date on demand, but do not persist fetched metadata.
  Only make requests for validated YouTube video IDs and fail gracefully when
  metadata is unavailable.
- Each mix can store a TIDAL playlist URL plus its resolved playlist ID/name.
  TIDAL playlist import is manual through the mix's **Sync playlist** button;
  do not add mix setlists to startup sync implicitly. A TIDAL playlist is only
  the setlist's import source: store membership in `setlists`/`setlist_tracks`,
  never `playlists`/`playlist_tracks`. Reuse shared `tracks` rows so one track
  can belong to multiple playlists and multiple setlists. The mix browser reads
  timestamps from setlist membership and shows them in its Position column.
- Do not show raw `positions.txt` contents in the mix detail view. Display the
  mapped TIDAL playlist name beside the live YouTube title in the mix header.
- The reused track browser must retain its full mouse and keyboard behavior on
  `/mixes/<folder>` routes, including row selection, Up/Down navigation,
  sidebar focus, and the Actions panel.
- `vis1tracktimer` and the existing `visv1trackTimer` spelling are excluded.
- The browser may only retrieve covers belonging to currently discovered mixes;
  do not expose a general filesystem-serving route.

## Sidebar navigation standard

- Collections in the left sidebar, including Playlists and Mixes, use the same
  collapsible parent-and-children pattern. Continue this pattern for future
  collection-style tools.
- Sidebar tools, collapsible parents, and visible children must always be both
  mouse accessible and keyboard navigable.
- Use the shared sidebar navigation behavior across every tool route; do not
  introduce route-specific sidebar handlers that prevent moving between tools.
- Left Arrow enters the sidebar from the current tool. Up/Down moves through
  visible sidebar entries. Enter toggles a collapsible parent. Enter or Right
  Arrow opens the highlighted tool or child entry.
- Collapsible parents are sibling navigation entries. When a parent is closed,
  Up/Down moves between top-level tools and parents. Enter or Right Arrow opens
  a closed parent while leaving selection on the parent; Down then enters its
  first child. Up/Down moves normally within an open child list. Left Arrow on
  a child collapses its group and returns selection to the parent. Enter or
  Right Arrow on a child opens that child's route. Enter on an open parent may
  collapse it.
- Do not capture arrow keys while the user is editing an input, textarea, or
  select control.

Configured TIDAL playlists are indexed as playlist sync reads them. If the
provider `last_updated` value matches SQLite, membership is loaded locally.
Changed playlists are fetched and transactionally re-indexed. When sync adds
tracks, local membership is updated immediately and marked for provider
revalidation on the following run.

## Liked tracks UI

- Route: `/liked-tracks`.
- Indexed TIDAL playlists appear below the main sidebar tools and open at
  `/playlists/<tidal-id>`. These routes reuse the liked-tracks table, inspector,
  actions, selection, and local 30-row pagination, reading tracks from SQLite.
- Indexed playlist links live inside a collapsible **Playlists** sidebar node.
  Click or Enter toggles it, hidden children are skipped by keyboard navigation,
  and the node opens automatically on an active playlist route.
- Sorted by TIDAL favorite date, newest first.
- Loads 30 rows at a time; an `IntersectionObserver` requests the next offset
  near the bottom of the table.
- Loaded pages are appended to SQLite. Recent cached pages are reused for five
  minutes; Refresh starts again at offset zero and bypasses the cache.
- Columns: title, artist, remix/version, album, length, BPM, Camelot key, year,
  and date added.
- TIDAL musical key/scale is converted to `01A`-`12A` / `01B`-`12B` and colored
  according to the Camelot wheel palette.
- Rows support mouse selection and Up/Down keyboard navigation. Selection
  follows the visible scroll area. Appending rows preserves scroll position.
- From tracks, Left Arrow enters the sidebar and Right Arrow enters Actions.
  In the sidebar, Up/Down navigates tools and playlists; Right Arrow or Enter
  opens the highlighted destination and returns focus to its track list.
- The right inspector displays selected-track metadata plus green playlist tags
  for every currently indexed TIDAL playlist containing that track ID. A 320px
  TIDAL album-art URL is cached with track metadata and shown above the details.
- Do not duplicate ordinary table fields such as remix, album, length, BPM, key,
  year, or date added in the selected-track inspector. Keep it focused on album
  art, title/artist, playlist membership, and editable local dimensions.
- An Actions panel sits below the inspector. Right Arrow moves keyboard focus
  from the selected track into Add/Remove/Move actions; Up/Down navigates, Enter or
  Right Arrow opens an action, and Left Arrow backs out. Add lists all indexed
  playlists; Remove lists only current memberships. Choosing a playlist calls
  TIDAL first, then mirrors a successful add/removal into SQLite and marks the
  cached playlist version for revalidation.
- Move is available only from an indexed playlist view. It adds to the selected
  destination first, removes from the currently viewed source second, then
  updates SQLite. If source removal fails after a real destination add, attempt
  to roll the destination add back before surfacing the error.
- The selected-track inspector always shows clickable choices for typed local
  dimensions stored in `track_dimension_values`: Rating and Energy are
  single-choice 1–5 values; Vibe, Movement, Function, and Structure are
  multi-value tags. Highlight selected values in place. These dimensions do not
  belong in the Actions panel; Actions is reserved for playlist operations.
- When removing a track while viewing that same indexed playlist, remove its
  row from the visible backing store immediately (unless another duplicate
  membership remains) and select the nearest remaining row.
- Do not enumerate `session.user.playlists()` for each liked-track action. The
  installed `tidalapi` factory already returns a writable `UserPlaylist` for an
  owned playlist; the enumeration can take tens of seconds.
- The loading spinner wraps only the track table; selecting a track should not
  flash or reload the surrounding page.

## Configuration and generated files

- `music_sync.json`: live configuration and sync state; preserve hidden fields
  such as unmatched records, `last_sync`, and `source_version` when editing UI
  rows.
- `music_sync.example.json`: example configuration.
- `.env`: local environment values; never expose or overwrite casually.
- `music_sync.log`: rotating application log.
- `.spotify_cache`, `.tidal_session.json`, `.connection_state.json`: local auth
  and connection state.

## Verification

Do not make live Spotify or TIDAL calls merely to test a code change. Prefer
mock objects and temporary SQLite databases. At minimum:

```powershell
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -m compileall -q .
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -c "import musicsync; app=musicsync.create_app(); client=app.server.test_client(); assert client.get('/_dash-layout').status_code == 200; assert client.get('/_dash-dependencies').status_code == 200; print('OK')"
```

When changing SQLite behavior, test against a database inside a newly-created
temporary directory. Verify cache hits, stale-version misses, ordered offsets,
and reverse track-to-playlist lookup.
