# MusicSync agent guide

This directory contains a local music-library application in an incremental
Dash-to-React/FastAPI migration. Dash remains the compatibility application;
the React application is the new implementation under active development.
Preserve existing user configuration, OAuth caches, logs, and SQLite data. Never
commit or print secrets from `.env`, `.spotify_cache`, `.tidal_session.json`, or
`.connection_state.json`.

## Commands

- Web application: `python musicsync.py` (defaults to `127.0.0.1:8080`)
- React/FastAPI preview: build in `frontend` with `npm run build`, then run
  `python react_app.py` (defaults to `127.0.0.1:8081`)
- FastAPI documentation: `http://127.0.0.1:8081/api/docs`
- Headless configured sync: `python startup_sync.py`
- Full TIDAL liked-track cache: `python cache_liked_tracks.py`
- Direct headless sync: `python musicsync.py --sync`
- Dependencies are declared in the repository-level `../requirements.txt`.

On this machine, the Microsoft Store Python aliases may return "access denied".
The working interpreter is:

```powershell
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -m compileall -q .
```

## Architecture

- `backend/app/`: FastAPI application, versioned local API, background jobs,
  sanitized errors, and adapters over the existing Python services.
- `frontend/src/`: React/TypeScript shell and feature UI. All provider and
  filesystem access goes through `/api/v1`; never expose credentials here.
- `react_app.py`: preview launcher that serves the built React application and
  API together. It does not replace the Dash launcher until parity is verified.
- `musicsync.py`: reusable playlist-sync engine, provider authentication, and
  backward-compatible CLI/application entry point.
- `startup_sync.py`: delayed, headless startup runner using `run_all_syncs`.
- `music_tools/ui.py`: shared full-width application shell, responsive sidebar,
  navigation, and global CSS.
- `music_tools/playlist_sync/page.py`: Dash app factory, URL routing, Spotify
  OAuth routes, playlist-sync layout, and callbacks.
- `music_tools/track_browser/`: stable, tool-neutral public API for the shared
  interactive track browser.
- `music_tools/global_search/`: SQLite-only search across liked tracks, indexed
  Playlists/Events/Sources, and My Mixes through the shared track browser.
- `music_tools/lastfm/`: provider-neutral listening-history import and
  conservative Last.fm identity matching through `pylast`; it must not depend
  on Dash. Translate provider errors without logging request URLs or API keys.
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

During migration, new HTTP routes belong in `backend/app/api`, use cases in
`backend/app/services`, and new browser UI in `frontend/src/features`. Reuse
existing provider/session functions and SQLite functions instead of duplicating
authentication or storage logic. Browsing, sorting, filtering, and paging are
SQLite-only. TIDAL refreshes run as explicit background jobs.

## Track browser extension contract

All present and future data tables should follow the shared track-table interaction
contract unless a table is strictly presentational: persist the active sort through
reloads/navigation, cycle sort ascending → descending → off, support mouse row
selection, and support Up/Down selection plus Enter or Right Arrow activation.
Build reusable table-state/navigation helpers instead of one-off key handlers.

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
- **Date added** sorting is collection-wide: sort the complete SQLite result
  before slicing each 30-row page, keep missing dates at the end, and use the
  full provider timestamp as the hidden sort value rather than the minute-only
  display string.
- The Fields popover beside Refresh controls visible columns from the same
  declarative schema. Column-specific CSS must use semantic classes such as
  `track-column-remix`, never positional `nth-child` selectors.
- Every dimension declared in `music_library/dimensions.py` is available as an
  optional Fields column backed by `row["dimensions"]`. Keep dimensions hidden
  by default, sortable when enabled, and synchronized with inspector edits.
- Quick Views are named sets of visible table fields configured under
  `/settings` and persisted in the top-level `quick_views` list in
  `music_sync.json`; never store them in browser-local storage. Render their
  buttons beside Fields in every shared track browser, and apply the one marked
  default in the server-rendered initial layout whenever a track browser opens;
  do not rely on a delayed callback or the Fields checklist's browser persistence.
- The Settings appearance toggle persists `settings.dark_mode` in
  `music_sync.json` and applies the theme immediately across the entire app.
- The selected-track **Tags & ratings** section is a native collapsible panel.
  Its current open/closed state lives in the root in-memory `ui-preferences`
  store so it survives navigation between track collections without browser
  persistence. Settings persists only the startup default as
  `settings.tags_collapsed_by_default` in `music_sync.json`.
- **Auto tag with Qwen3** is a shared track action backed only by the local
  Ollama endpoint configured by `settings.ollama_url` and
  `settings.ollama_model`. Send cached metadata only, require catalog-constrained
  JSON, validate every returned value, preserve Rating, and write accepted
  dimensions to SQLite. It must work for the current multi-track selection.
- Quick filters operate on the complete current SQLite collection before
  pagination, not only the loaded browser rows. Different filter categories are
  ANDed; multiple selections inside a category are ORed. Filter controls retain
  their existing browser persistence. The Track text filter appears before
  Artist and matches title plus remix/version case-insensitively.
- Sort and Fields are shared transient view preferences in the root
  session-backed `track-view-state` store. They survive internal navigation,
  browser Back, and switching collections, while Quick Views remain the way to
  reset/apply a named field set. Per-collection state retains loaded row count
  (capped at 1,000 on restore) and selected track ID. Scroll position is keyed
  by collection in `sessionStorage` and restored after table DOM replacement.
- The track loader suppresses its component-mount call and performs one
  controlled initial load from `liked-initial-load`; do not reintroduce a cache
  render followed immediately by a second provider-check render. Infinite-scroll
  append must retry scroll restoration until the replacement table is mounted.
- Artist cells and top-artist summaries link to `/artists/<normalized-key>`,
  which shows every locally indexed track credited to that artist without a
  provider call.
- Keep collection descriptors JSON-serializable. The common keys are `type`,
  `id`, and `name`. Setlist timestamps come from SQLite membership rows rather
  than being carried in the collection descriptor.
- Register shared track-browser callbacks once in the application factory.
  Tools embed browser layouts but must not register duplicate callbacks.
- Timestamped staging/setlist tables use the shared browser-side stopwatch.
  Start/Pause must not invoke Dash callbacks; Stop resets it. Rows carrying a
  valid Time/Position data attribute are highlighted from their start time
  until the next timestamp. Mounting a different stopwatch page resets state.

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

Adding a new independent table with `CREATE TABLE IF NOT EXISTS` is safe while
the app is running and does not require a stop. Before changing, copying,
backing up, rebuilding, or migrating any existing live table or its data, tell
the user exactly what will change and wait for confirmation that the web app
and startup sync are stopped. Migrations against new temporary test databases
do not require this coordination.

Core tables:

- `tracks`: provider metadata keyed by provider and provider track ID.
- `artists` and `track_artists`: normalized artist identities and ordered
  many-to-many track credits. Existing flattened artist strings are backfilled;
  future TIDAL records retain provider artist IDs when available.
- `playlists`: indexed playlist names, provider `last_updated` values, and a
  presentation-only `collection_type` of `playlist`, `event`, or `source`.
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
- `pending_tracks`: independent release-watch queue for parsed watched-mix
  tracks, their source mix, last TIDAL candidates, and resolution state.
- `event_links`: independent user-owned YouTube and Concert Archives URLs keyed
  to an indexed TIDAL event. YouTube metadata may be fetched for presentation;
  Concert Archives is storage/link-out only and must never be scraped or fetched.
- `lastfm_scrobbles`: immutable listening-history rows keyed by user, timestamp,
  and normalized identity. Preserve timestamps for monthly charts. Matching to
  TIDAL tracks must be conservative: ambiguous identities remain unmatched.
- `youtube_mix_analytics`: independent cached owner analytics keyed by local
  My Mix folder. Only show a row when its cached video ID still matches the
  mix's saved YouTube URL; entering My Mixes Overview triggers one refresh.
- `youtube_video_metadata`: independent cached YouTube title and upload date
  keyed by video ID so overview metadata survives backend restarts.

## Mix explorer

- Routes: `/mixes` and `/mixes/<folder>`; `MUSICSYNC_MIX_ROOT` overrides the default
  `~/Documents/djstuff` directory.
- Mix folders appear as children of a collapsible **My mixes** sidebar node; each
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
- Google OAuth stays in the FastAPI backend. Store its refresh token only in the
  ignored `.youtube_oauth.json` file, request read-only YouTube scopes, validate
  the callback state cookie, and expose connection controls in Settings. Entering
  My Mixes Overview refreshes cached analytics once; manual refresh remains a retry.
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

## Watched mixes

- `/watched-mixes` is a separate, manually managed collection of YouTube mixes;
  it must not reuse local setlist rows or imply that the user created the mix.
- Store the validated YouTube video ID/URL, title, channel name, upload date,
  and date added. The thumbnail and current view count remain live values.
- Watched mixes use their own collapsible sidebar group with an always-present
  **Add mix** child and follow the standard mouse/keyboard navigation contract.
- `watched_mix_tracks` is an ordered many-to-many association between saved
  watched mixes and existing local TIDAL tracks. A watched-mix detail route
  renders those tracks through the shared track browser.
- The shared track table exposes watched-mix provenance as the **Dj Mix**
  column. It displays clickable YouTube-channel membership pills linking to the
  corresponding watched-mix route and hides the currently viewed mix itself.

## Watched-mix tracklist import

- Watched-mix detail pages contain a temporary staging table for pasted
  tracklists. Timestamps are optional and may be plain or bracketed. Support
  explicit `Artist - Title` and `Title - Artist` parsing modes, common spaced
  dash variants, harmless trailing star markers, and paired
  `Artist A vs. Artist B - Song A vs. Song B (Mashup)` entries. Expand a
  balanced mashup into separately searchable staging rows while preserving its
  timestamp and original line; never create canonical track rows while parsing.
  `ID`/unknown titles remain unresolved and are not searched.
- Search TIDAL only when explicitly requested, throttle sequential searches,
  cache serializable alternatives in the staging store, and let the user choose
  a candidate before liking it.
- A staging Like is provider-first and repairable: add the selected track to
  TIDAL favorites, upsert it at the front of the local liked snapshot,
  associate it with the watched mix, then refresh the normal SQLite track
  browser. Do not persist staging rows.
- **Watch** persists a named staging row to `pending_tracks` without creating a
  canonical library track. Pending tracks live at `/watched-mixes/pending`, a
  fixed child of the Watched mixes sidebar group. Opening that page and its
  explicit Refresh both search TIDAL; a confirmed Like follows the same
  provider-first liked-cache and watched-mix-association flow, then resolves
  the queue item. `ID` rows cannot be watched because they lack a searchable
  title.

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
- Last.fm history is imported explicitly from Settings using `LASTFM_API_KEY`
  from `.env` and `settings.lastfm_username` from `music_sync.json`. The first
  import walks oldest-to-newest so an interrupted run can resume safely;
  subsequent imports use the newest cached timestamp. Track tables expose
  optional Play count and Last played fields, and the inspector shows the
  current matched count. Importing must never modify TIDAL or scrobble plays.
- Route `/search` is the global library search. It deduplicates tracks across
  liked tracks, indexed Playlists/Events/Sources, and My Mixes, never calls a
  provider while searching, and matches free text against title, remix,
  artist, and album. Watched mixes remain provenance and are not part of this
  global library collection.
- Opening the route performs exactly one bounded live-prefix refresh from TIDAL
  into SQLite; **Refresh from TIDAL** explicitly repeats it. Subsequent paging,
  scrolling, filtering, and sorting read only SQLite and must not call TIDAL.
  Other collection routes retain the **Reload SQLite** button and never refresh
  liked tracks. `cache_liked_tracks.py` performs a complete reconciliation.
  Each manual/startup Playlist Sync run also performs the bounded maintenance
  pass, adding recent likes and reconciling removals within the scanned prefix
  while preserving the older cached tail.
- Opening an indexed Playlist/Event/Source route performs one lightweight
  provider metadata check. If TIDAL `last_updated` still matches SQLite, keep
  reading the local membership; otherwise refetch and transactionally replace
  that playlist cache. Its **Refresh from TIDAL** button always forces a remote
  membership fetch. Pagination, filters, and sorting remain SQLite-only.
- Indexed TIDAL playlists appear below the main sidebar tools and open at
  `/playlists/<tidal-id>`. These routes reuse the liked-tracks table, inspector,
  actions, selection, and local 30-row pagination, reading tracks from SQLite.
- Indexed playlist links live inside a collapsible **Playlists** sidebar node.
  Click or Enter toggles it, hidden children are skipped by keyboard navigation,
  and the node opens automatically on an active playlist route.
- Playlist-sync mappings classify their indexed TIDAL playlist as Playlist,
  Event, or Source. Each class has its own collapsible sidebar group and its own
  reverse-membership table/inspector field; do not leak Events or Sources into
  the Playlists field. Setlist membership is shown separately as Mixes.
- `music_sync.json` is authoritative for configured playlist classifications.
  Reconcile those values into SQLite when Playlist Sync opens, and refresh the
  mounted sidebar after Save/Sync so a changed classification moves immediately.
- Sorted by TIDAL favorite date, newest first.
- The React browser loads 200 rows at a time; an `IntersectionObserver` requests the next offset
  near the bottom of the table.
- Loaded pages are appended to SQLite. Recent cached pages are reused for five
  minutes; Refresh starts again at offset zero and bypasses the cache.
- Columns: title, artist, remix/version, album, length, BPM, Camelot key, year,
  and date added.
- TIDAL musical key/scale is converted to `01A`-`12A` / `01B`-`12B` and colored
  according to the Camelot wheel palette.
- Rows support mouse selection and Up/Down keyboard navigation. Selection
  follows the visible scroll area. Appending rows preserves scroll position.
- Shift+Up/Down and Shift+click create a contiguous multi-selection. Playlist
  actions, watched-mix association, and dimension edits apply to every selected
  row while the focused row remains the inspector anchor.
- From tracks, Left Arrow enters the sidebar and Right Arrow enters Actions.
  In the sidebar, Up/Down navigates tools and playlists; Right Arrow or Enter
  opens the highlighted destination and returns focus to its track list.
- The right inspector displays selected-track metadata plus green playlist tags
  for every currently indexed TIDAL playlist containing that track ID. A 320px
  TIDAL album-art URL is cached with track metadata and shown above the details.
- Render only non-empty Playlist/Event/Source/Mix/Dj Mix memberships as compact,
  clickable pills directly below the selected track's artist. Do not render
  labeled membership sections or `None` placeholders at the inspector bottom.
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
  dimensions stored in `track_dimension_values`. Rating, Energy, and Tension
  are single-choice 1–5 values; Driver and Scale allow up to two choices; Vibe,
  Movement, Function, Structure, and Texture are multi-value tags. Keep the
  catalog centralized in `music_library/dimensions.py` and highlight selected
  values in place. These dimensions do not
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
