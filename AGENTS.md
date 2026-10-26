# MusicSync agent guide

This directory contains a local React/FastAPI music-library application. The
retired Dash presentation layer is archived under `backups/dash_app/` for source
reference only and must not be imported by active code.
Preserve existing user configuration, OAuth caches, logs, and SQLite data. Never
commit or print secrets from `.env`, `.spotify_cache`, `.tidal_session.json`, or
`.connection_state.json`.

## Commands

- Web application: build in `frontend` with `npm run build`, then run
  `python react_app.py` or `python main.py` (defaults to `127.0.0.1:8081`)
- FastAPI documentation: `http://127.0.0.1:8081/api/docs`
- Headless configured sync: `python startup_sync.py`
- Full TIDAL liked-track cache: `python cache_liked_tracks.py`
- Verified Turso-to-SQLite backup: `python backup_turso.py --database <name>`
- Direct headless sync: `python main.py --sync`
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
- `react_app.py`: launcher that serves the built React application and API.
- `main.py`: reusable playlist-sync engine, provider authentication, and an
  alternate FastAPI/headless-sync entry point.
- `startup_sync.py`: delayed, headless startup runner using `run_all_syncs`.
- `frontend/src/app/` and `frontend/src/components/`: application shell,
  responsive sidebar, routing, and shared React UI.
- `frontend/src/features/`: active feature pages and shared track browser.
- `backups/dash_app/`: retired Dash source only; never add active imports from
  this directory.
- The FastAPI app registers `frontend/dist` with `app.frontend()` after every
  API/login route. This is the Vercel-aware static frontend boundary: keep SPA
  fallback there rather than restoring a manual catch-all or conditional
  `StaticFiles` mount, which can omit hashed Vite assets from the deployment.
- `music_tools/lastfm/`: provider-neutral listening-history import and
  conservative Last.fm identity matching through `pylast`; keep it independent
  of the presentation layer. Translate provider errors without logging request
  URLs or API keys.
- `music_tools/liked_tracks/`: provider-neutral TIDAL liked/indexed-playlist
  retrieval used by backend jobs and services.
- `music_tools/mixes/`: database-backed My Mix metadata, YouTube presentation,
  and explicit TIDAL setlist import. It has no local media-folder dependency.
- `music_library/database.py`: shared SQLite schema, TIDAL playlist cache,
  liked-track cache, reverse playlist membership lookup, and future user
  metadata storage.

## Hosted authentication

- Vercel deployments require Google OIDC login by default; local development
  remains open unless `TUNEOPS_AUTH_REQUIRED=true` is set.
- Login uses a separate callback and only the `openid email profile` scopes.
  `GOOGLE_SIGNIN_CLIENT_ID` / `GOOGLE_SIGNIN_CLIENT_SECRET` may temporarily
  fall back to the existing Google client, but never add YouTube scopes to the
  sign-in request.
- `TUNEOPS_ALLOWED_EMAILS` is a comma-separated, fail-closed allowlist for the
  initial private deployment. Identify authenticated users by Google's stable
  `sub` claim, never by email.
- Browser sessions are signed, `HttpOnly`, `SameSite=Lax`, and `Secure` on
  Vercel. OAuth uses signed state, nonce, and PKCE. Keep
  `TUNEOPS_SESSION_SECRET` outside source control and at least 32 characters.
- Only `/login`, `/api/v1/auth/*`, and static assets are public. All other UI
  and API routes require a valid session; do not expose provider health labels
  through a public health endpoint.
- Google login authenticates TuneOps only. YouTube Analytics authorization is
  a separate provider connection and must retain its narrower provider-token
  lifecycle.
- Successful Google login resolves to the stable internal `app_users.id` and
  stores that ID in the signed browser session. External accounts are linked
  by `(issuer, subject)` through `music_library.identities`; never reassign an
  existing identity or use email as the authorization key. Legacy signed
  single-user sessions may temporarily resolve through `TUNEOPS_LOCAL_USER_ID`
  until the next login persists the Google identity link.
- MCP bearer validation lives under `backend/app/mcp`. The private ChatGPT
  connection uses a dedicated Google OAuth client: set
  `TUNEOPS_MCP_AUTH_PROVIDER=google`, `GOOGLE_MCP_CLIENT_ID`, and
  `TUNEOPS_MCP_RESOURCE_URL` (or `TUNEOPS_PUBLIC_URL`). Validate Google's
  opaque access token through Google's token-info endpoint, require the exact
  dedicated client ID, expiry, `openid`, and an existing Google
  `(issuer, subject)` link before exposing the internal user ID to a tool.
  `openid email profile` are the only OAuth scopes requested from Google;
  `profile:read`, `library:read`, and future write capabilities are internal
  TuneOps policy, not invented Google scopes. Keep synchronous Google/Turso
  validation off the ASGI event loop. Generic JWT IdPs remain supported through
  `TUNEOPS_MCP_ISSUER_URL`, optional `TUNEOPS_MCP_AUDIENCE`, and optional
  `TUNEOPS_MCP_JWKS_URL`.
- The MCP HTTP adapter is mounted only when that configuration is complete.
  Its canonical resource URL ends in `/mcp/`; the root protected-resource
  metadata routes and `/mcp` transport bypass browser-cookie auth but retain
  MCP bearer auth. Keep the SDK session manager in the host FastAPI lifespan,
  retain `stateless_http=True` for Vercel, and preserve DNS-rebinding host
  allowlists for the canonical host, Vercel preview host, and local testing.
- MCP library tools are bounded adapters in
  `backend/app/services/mcp_library.py`. Reuse shared collection queries,
  return concise summaries rather than raw rows, cap pages and membership
  requests at 50, and require the resolved internal user to equal the current
  single-user library owner until library tables gain explicit ownership.

New HTTP routes belong in `backend/app/api`, use cases in
`backend/app/services`, and browser UI in `frontend/src/features`. Keep provider
and database work out of React components. Reuse
existing provider/session functions and SQLite functions instead of duplicating
authentication or storage logic. Browsing, sorting, filtering, and paging are
SQLite-only. TIDAL refreshes run as explicit background jobs.
Persisted job-status polling is a one-statement read and must use
`connect_readonly()`; progress/result writes retain explicit transactions.

## Database performance contract

- Treat Turso as a remote HTTP database, not as local SQLite. A helper that
  opens several connections or executes one statement per row creates real
  network round trips.
- Every SELECT-only repository helper must use `connect_readonly()`. Use the
  backend-neutral `execute_batch()` path when one response needs several
  independent bounded SELECTs; Turso must send those statements in one
  pipeline while local SQLite keeps identical behavior.
- Shared track collections use `music_library.collection_query`. Apply
  allowlisted filters and sorting in SQL, page before enriching relationships,
  and return collection statistics only with the first page. Never restore the
  old `limit=1_000_000` plus Python filtering path.
- Provider imports may normalize rows in memory, but must batch canonical
  tracks, artists, relationships, and memberships inside one atomic write
  transaction. Do not open a transaction per provider track.
- Navigation has a short process-local cache. Any
  mutation that changes mappings, collection membership, watched mixes,
  setlists, history visibility, or relevant settings must invalidate the
  navigation cache explicitly.
- Request telemetry may record connection, statement, pipeline, row, byte, and
  duration counts. Never log SQL parameters, user-entered search text, tokens,
  decrypted credentials, or authorization headers.
- Performance tests use temporary SQLite databases or mocked Turso pipelines.
  Do not contact live providers or the configured Turso database merely to run
  the test suite.

## Track browser extension contract

All present and future data tables should follow the shared track-table interaction
contract unless a table is strictly presentational: persist the active sort through
reloads/navigation, cycle sort ascending → descending → off, support mouse row
selection, and support Up/Down selection plus Enter or Right Arrow activation.
Build reusable table-state/navigation helpers instead of one-off key handlers.

- Reuse the React browser under `frontend/src/features/track-browser`; do not
  build collection-specific copies of the table or inspector.
- Browser keyboard activation is based on the mounted
  `data-track-browser-root` marker, never route-name checks. A new route that
  embeds the browser must work without editing JavaScript route allowlists.
- Collection-specific columns belong in `EXTRA_COLUMNS_BY_COLLECTION` and are
  selected from `collection["type"]`; do not infer schemas from whichever rows
  happen to be loaded.
- Shared table headers are clickable and cycle ascending, descending, then off.
  The first direction comes from `settings.default_sort_direction`; the second
  click uses the opposite direction and the third turns sorting off. Missing
  values remain last in both directions.
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
  `/settings` and persisted in SQLite through `music_library.config_store`;
  never store them in browser-local storage. Render their
  buttons beside Fields in every shared track browser, and apply the one marked
  default in the server-rendered initial layout whenever a track browser opens;
  do not rely on a delayed callback or the Fields checklist's browser persistence.
- The Settings appearance toggle persists `settings.dark_mode` in the SQLite
  configuration store and applies the theme immediately across the entire app.
- The React Settings page autosaves the complete settings/Quick View draft
  after a short debounce. Do not restore a normal Save Settings button. Do not
  let an older save response overwrite newer local edits; show an explicit
  retry only after autosave ultimately fails.
- Settings reads use the narrow `config_store.load_settings_bundle()` path and
  must not hydrate sync mappings or unmatched-track state. The shared frontend
  Settings query stays fresh for five minutes; successful autosaves update that
  cache immediately.
- Backend callers that need only application settings use
  `main.load_runtime_settings()`. Do not load mappings, unmatched tracks, or
  Quick Views merely to read a runtime setting.
- Navigation obtains qualifying Last.fm years and months through the combined
  `lastfm_history_navigation()` query; do not split it back into two remote
  reads.
- The selected-track **Tags & ratings** section is a native collapsible panel.
  Its current open/closed state lives in the root in-memory `ui-preferences`
  store so it survives navigation between track collections without browser
  persistence. Settings persists only the startup default as
  `settings.tags_collapsed_by_default` in the SQLite configuration store.
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
- `/artists` is the SQLite-only Artists overview. Its indexed-track count must
  use the exact membership scope of artist detail pages: the deduplicated union
  of Liked tracks, Playlists/Events/Sources, and My Mixes setlists. Last.fm
  streams count matched scrobbles through canonical `track_artists`, so a
  collaborative track credits each artist. Keep its search, persistent
  three-state sorting, paging, mouse selection, and keyboard activation aligned
  with the shared table interaction contract.
- Keep collection descriptors JSON-serializable. The common keys are `type`,
  `id`, and `name`. Setlist timestamps come from SQLite membership rows rather
  than being carried in the collection descriptor.
- Keep shared track-browser behavior in its React feature components and hooks;
  collection routes should supply descriptors rather than duplicate handlers.
- Timestamped staging/setlist tables use the shared browser-side stopwatch.
  Start/Pause remains client-side; Stop resets it. Rows carrying a
  valid Time/Position data attribute are highlighted from their start time
  until the next timestamp. Mounting a different stopwatch page resets state.

## Playlist sync behavior

- The React mapping editor autosaves changes after a short debounce. Do not
  restore a normal Save Mappings button. Keep Sync Now disabled while changes
  are dirty or saving, and expose an explicit retry only after autosave fails.
- Removing a sync mapping removes its local indexed TIDAL playlist only when no
  remaining mapping references the same playlist. It must never delete the
  remote TIDAL or Spotify playlist. Tracks that lose their final membership are
  intentionally retained until the user reviews **Orphaned tracks** in Settings.
- Supports `spotify_to_tidal`, `tidal_to_spotify`, and `tidal_cache` mappings
  from the SQLite configuration store. `tidal_cache` indexes the configured TIDAL playlist
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

`music_library.connection` is the database transport boundary. SQLite remains
the safe default; `TUNEOPS_DATABASE_BACKEND=turso` explicitly selects the
shared remote primary using `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` (with the
current Vercel-prefixed names accepted as transitional fallbacks). Never
silently fall back from Turso to a stale local SQLite file after a remote
failure. After cutover, Turso is writable primary; local SQLite copies are
validated backups or an explicitly selected disaster-recovery mode.

Provider credentials use `music_library.credentials` as their only storage
boundary. File storage remains the default during migration;
`TUNEOPS_CREDENTIAL_STORAGE=database` opts into encrypted, user-scoped rows in
`provider_connections`. The encryption key comes only from
`TUNEOPS_CREDENTIAL_KEY`, and local/background ownership comes from the stable
UUID in `TUNEOPS_LOCAL_USER_ID`. Never print ciphertext, plaintext tokens, the
encryption key, or provider authorization headers. Spotify refreshes must keep
an existing refresh token when the provider omits it from a refresh response.
The legacy credential files remain untouched rollback inputs until an explicit,
coordinated cleanup after both local and hosted credential flows are verified.

Adding a new independent table with `CREATE TABLE IF NOT EXISTS` is safe while
the app is running and does not require a stop. Before changing, copying,
backing up, rebuilding, or migrating any existing live table or its data, tell
the user exactly what will change and wait for confirmation that the web app
and startup sync are stopped. Migrations against new temporary test databases
do not require this coordination.


Core tables:

- `app_users`, `external_identities`, `provider_connections`, and
  `credential_audit_events`: stable internal ownership plus AES-GCM encrypted
  Spotify/TIDAL/YouTube credential payloads. App-registration secrets remain
  environment variables and never belong in these tables.
- `app_settings`: versioned, semi-structured non-secret settings for the local
  profile.
- `sync_mappings`: ordered playlist-sync definitions and runtime state with a
  stable UUID per mapping.
- `sync_unmatched_tracks`: mapping/direction-specific unmatched-track state.
- `quick_views`: both track and My Mix field presets, distinguished by
  `view_type`, with at most one default per type.
- `config_store_meta`: marks an initialized SQLite configuration store and
  preserves unknown portable top-level configuration fields.
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
- `setlists`: user-owned My Mix metadata and YouTube/TIDAL import-source
  mappings.
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
- `lastfm_monthly_track_counts` and `lastfm_history_cache_state`: rebuildable
  per-user materialized history aggregates. Raw `lastfm_scrobbles` remain the
  authority. History navigation and month/year/overall Top X queries use these
  counts after a successful import or reconciliation, but retain a raw-query
  fallback for databases that have not built the cache yet. Any operation that
  changes historical TIDAL matches must rebuild or invalidate this cache.
- `youtube_mix_analytics`: independent cached owner analytics keyed by local
  My Mix folder. Only show a row when its cached video ID still matches the
  mix's saved YouTube URL; entering My Mixes Overview triggers one refresh.
- `youtube_video_metadata`: independent cached YouTube title and upload date
  keyed by video ID so overview metadata survives backend restarts.
- `youtube_video_reach_daily` and `youtube_reach_report_imports`: independent
  daily thumbnail-impression/CTR cache and imported-report ledger for the
  asynchronous YouTube Reporting API.

The Settings **Orphaned tracks** view lists TIDAL track rows that have no
membership in Liked tracks, indexed playlists/events/sources, My Mixes
setlists, or watched mixes. Clearing this view is an explicit, confirmed,
local-only destructive action: delete the orphan track rows and their cascading
local metadata, reset matching Last.fm scrobbles to unmatched, and never call a
music provider or delete remote data.

## Mix explorer

- Routes: `/mixes` and `/mixes/<id>`. Persisted `setlists` rows are the sole
  source for **My mixes** navigation and detail views.
- Active My Mix code must not inspect local folders, `MUSICSYNC_MIX_ROOT`,
  `cover.png`, WAV files, or `positions.txt`. TuneOps must behave identically
  locally and on Vercel.
- Show a validated saved YouTube video's thumbnail as artwork. A future TIDAL
  playlist-art fallback may be added without restoring filesystem discovery.
- The saved YouTube URL is user-owned SQLite metadata. Fetch its current title,
  view count, and upload date on demand, but do not persist fetched metadata.
  Only make requests for validated YouTube video IDs and fail gracefully when
  metadata is unavailable.
- Google OAuth stays in the FastAPI backend. Store its refresh token only in the
  ignored `.youtube_oauth.json` file, request read-only YouTube scopes, validate
  the callback state cookie, and expose connection controls in Settings. Entering
  My Mixes Overview refreshes cached analytics once; manual refresh remains a retry.
- My Mixes Overview has its own Quick Views, configured under Settings and
  persisted with `view_type='mix'`. Keep them separate from track-table
  `quick_views`; the overview's active fields and sort survive navigation in
  session state. Thumbnail impressions and cover CTR come from asynchronous
  YouTube Reporting API reach reports, so the first refresh may only create the
  reporting job and later refreshes import generated reports.
- YouTube Reporting API thumbnail CTR is stored as the provider's raw 0..1
  ratio and converted to percentage points when read. Label it as recent/report
  data, not lifetime Studio data: bulk reports only cover files generated after
  the MusicSync reporting job exists, so always show the reported impression
  sample alongside a detail CTR.
- My Mix detail headers reuse the cached owner-analytics row for that mix and
  expose both **Open on YouTube** and **Open in Analytics** links when the saved
  video URL is valid. Do not make a second owner-analytics request on detail
  page load; refresh remains an Overview job.
- Each mix can store a TIDAL playlist URL plus its resolved playlist ID/name.
  TIDAL playlist import is manual through the mix's **Sync playlist** button;
  do not add mix setlists to startup sync implicitly. A TIDAL playlist is only
  the setlist's import source: store membership in `setlists`/`setlist_tracks`,
  never `playlists`/`playlist_tracks`. Reuse shared `tracks` rows so one track
  can belong to multiple playlists and multiple setlists. The mix browser reads
  any already-stored timestamps from setlist membership. New TIDAL-only imports
  have no Time until a separate YouTube-description importer supplies it.
- `/settings/my-mixes` owns explicit automatic discovery. It scans only
  playlists owned by the connected TIDAL user, accepts exact case-insensitive
  names shaped as `djset <internal name>`, and derives the My Mix name from the
  suffix. Import a newly seen TIDAL playlist into `setlists`/`setlist_tracks`
  once; never refetch or overwrite an already linked playlist during discovery.
  Duplicate names are ambiguous and must be left untouched. Discovery is an
  explicit background job, not startup behavior, and must never create normal
  `playlists`/`playlist_tracks` membership.
- Display the mapped TIDAL playlist name beside the live YouTube title in the
  mix header.
- The reused track browser must retain its full mouse and keyboard behavior on
  `/mixes/<folder>` routes, including row selection, Up/Down navigation,
  sidebar focus, and the Actions panel.

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
  from `.env` and `settings.lastfm_username` from the SQLite configuration
  store. The first
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
- The SQLite configuration store is authoritative for configured playlist classifications.
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

- `music_library.sqlite3`: live configuration and sync state as well as the
  music library. Preserve mapping IDs, unmatched records, `last_sync`, and
  `source_version` when editing UI rows.
- `music_library/config_store.py`: transactional compatibility repository for
  settings, sync mappings/state, and both Quick View types. Existing callers
  currently use the document-shaped `main.load_config()` / `save_config()` API,
  but those functions read and write SQLite.
- `music_sync.json`: preserved legacy migration/rollback snapshot. It is used
  only to seed an absent SQLite configuration store and is ignored once
  `config_store_meta` exists. Never overwrite a populated store by silently
  re-importing this file.
- `music_sync.example.json`: example import/export configuration.
- `.env`: local environment values; never expose or overwrite casually.
- `music_sync.log`: rotating application log.
- `.spotify_cache`, `.tidal_session.json`, `.connection_state.json`: local auth
  and connection state. During the credential cutover these remain untouched
  rollback inputs; active reads/writes use encrypted database rows when
  `TUNEOPS_CREDENTIAL_STORAGE=database`.
- `migrate_auth.py`: read-only inspection plus explicit local credential import
  and decryption verification. It intentionally targets SQLite before the full
  database migration.
- `migrate_database.py`: protected SQLite-to-Turso copy/verification utility.
  It refuses to merge non-empty mismatched tables unless `--replace` is
  explicitly supplied, migrates table-by-table, and verifies every row count.
- `backup_turso.py`: read-only Turso-to-local backup utility. It uses the
  official CLI `.dump`, restores into a temporary SQLite file, verifies
  integrity, foreign keys, stable remote counts, and every table count, then
  atomically promotes a timestamped ignored `.sqlite3` file. Stop writers for
  exact count verification, never overwrite an existing backup, and preserve
  `TUNEOPS_CREDENTIAL_KEY` separately from encrypted credential rows.

## VirtualDJ companion

- The downloadable, standard-library-only companion lives under
  `frontend/public/downloads/virtualdj-companion/`; Vite copies this directory
  unchanged into the deployed site. Do not edit generated `frontend/dist`
  assets by hand.
- Collection track tables export every track plus typed dimensions and
  free-form tags through the authenticated `virtualdj-metadata` endpoint.
  Version its JSON contract before making a breaking change. The companion
  consumes ratings, typed dimensions, and free-form tags while retaining
  backward compatibility with the version-one ratings-only export.
- Match VirtualDJ TIDAL-extension entries only by the exact numeric provider ID
  found in `netsearch://td<ID>` or `Link NetSearch="td<ID>"`. Never guess using
  title or artist, and refuse entries whose two ID locations disagree.
- Ratings map to VirtualDJ's native `Stars="1"` through `Stars="5"` attribute
  on an existing `Tags` element. Do not store ratings in `Comment`.
- A valid release year maps to VirtualDJ's native `Tags Year="YYYY"` attribute.
- Other typed dimensions and free-form tags map to one managed Comment line:
  `[TuneOps] #Energy4 #Dark #VibeFlip`. Collapse spaces/punctuation into a
  hashtag-safe token, replace only the TuneOps line on rerun, and preserve all
  other user-authored comment content.
- Never synthesize missing VirtualDJ `Song` records: the minimal records tested
  in VirtualDJ were rejected as corrupt. Users must let VirtualDJ materialize
  provider tracks first, for example through a batch tag edit.
- Preview is read-only by default. An explicit apply must create a timestamped
  backup, validate the resulting XML, and atomically replace `database.xml`.
  Preserve all unrelated attributes, elements, and comments. VirtualDJ must be
  closed before an apply.

## Verification

Do not make live Spotify or TIDAL calls merely to test a code change. Prefer
mock objects and temporary SQLite databases. At minimum:

```powershell
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -m compileall -q .
& 'C:\Users\jon39\AppData\Local\Python\bin\python.exe' -m pytest -q
Set-Location frontend
npm test -- --run
npm run build
```

When changing SQLite behavior, test against a database inside a newly-created
temporary directory. Verify cache hits, stale-version misses, ordered offsets,
and reverse track-to-playlist lookup.
