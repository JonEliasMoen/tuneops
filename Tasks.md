# React + FastAPI migration status

Last reviewed: 2026-09-29. Dash remains the compatibility UI on port 8080.
`react_app.py` serves the React/FastAPI preview locally on port 8081. It reuses
the existing configuration, OAuth/session caches, services, and SQLite library;
authentication redesign is intentionally deferred.


# MESSAGE FROM JON
- [x] Cache watched-mix YouTube covers locally and reuse the local cover endpoint
  in both the list and detail views.
- [x] Allow setting the mix stopwatch start time.
- [x] Embedded YouTube playback was tested and removed because YouTube's
  third-party player is unreliable under the local Firefox/privacy setup.
  Keep the cached cover and explicit **Open on YouTube** link instead.
- [x] Retain parsed watched-mix staging rows and running stopwatch state across
  navigation/reloads, expiring the temporary state after 24 hours.

## Done

- [x] FastAPI local API, static React SPA, health/info, request IDs, sanitized
  errors, and JSON API 404/validation boundaries.
- [x] React shell: theme, sidebar groups, deep links, shared track browser for
  library, playlist/event/source, artist, My Mix, and Watched Mix routes.
- [x] SQLite-only paging, global sorting/filtering/stats, fields, Quick Views,
  selection, scroll restoration, and table state persistence.
- [x] Inspector, typed dimensions, bulk selection, provider-first playlist
  actions, watched-mix association, Qwen job, and native TIDAL track links.
- [x] Playlist Sync, settings, Last.fm jobs, My Mix stopwatch, Watched Mix
  tracklist staging/pending queue, and Event media links.
- [x] Last.fm History sidebar with nested Year/Month navigation and configurable
  monthly, yearly Overall, and all-time Overall Top X shared track-table views
  from cached imported scrobbles.
- [x] My Mixes overview table backed by existing SQLite setlist metadata, with
  sortable mix/setlist/track-count/update columns and local media availability;
  read-only Google OAuth plus explicitly refreshed/cached YouTube owner
  analytics columns.
- [x] Existing liked/playlist cache duplicates cleaned; unique membership
  indexes now prevent overlapping cache results from returning duplicates.
- [x] Automated checks cover Python contracts plus React browser-state,
  navigation, action, selection, Quick View, scroll, stopwatch, and presentation
  behavior; exact passing totals are recorded by the current test runs.
  Python compilation, and React production build.

## Required before React is the default

### Real-account verification

- [ ] Exercise Add, Remove, Move, watched-mix Like, pending resolution, Qwen
  tagging, and Playlist Sync against the real account.
- [ ] Verify expired provider sessions and the legacy Dash login/callback flow
  can reconnect them on the real account. TLS failures now show a concise
  cached-data-safe UI message rather than the raw Python certificate exception.
- [ ] Re-test bounded TIDAL refreshes after the local Python TLS issue is fixed.
- [ ] Compare Dash/React counts for liked tracks, Playlist, Event, Source, My
  Mix, and Watched Mix.

### Browser reliability

- [x] Expanded Vitest coverage to track selection and Quick Views. Vitest now covers stateful
  sorting/filter/field persistence, collection-specific selection/scroll/
  pagination restoration, the sidebar keyboard group/navigation contract, and
  local mocked action-menu grouping/payloads for Playlist/Event/Source targets,
  plus stopwatch parsing, active-track calculation, and stopping.
- [x] Playwright intentionally excluded. Browser reliability is covered with
  lightweight Vitest tests plus manual Chrome verification; do not add the
  Playwright browser/runtime dependency.
- [ ] Manually verify keyboard navigation contract end-to-end.
- [x] Profiled 5,000 real cached global-library rows: median SQLite/Python
  preparation was 252 ms. Keep 200-row paging and the existing 1,000-row
  restore cap; defer virtualization unless that cap is raised or browser DOM
  profiling proves it necessary. `profile_library.py` repeats the read-only
  measurement.

### Remaining feature parity

- [x] My Mix editor: save YouTube/TIDAL URLs, live YouTube title/views/date,
  and manually import a TIDAL setlist through an explicit background job.
- [x] Watched Mix editor/delete controls and graceful live YouTube
  metadata/views. Deletion requires an in-browser confirmation.
- [x] Multi-track playlist actions preserve successful provider/SQLite updates
  and report failed/skipped tracks instead of hiding a partial result behind a
  generic error.
- [x] Pending tracks show candidate confidence and support an explicit
  per-track **Recheck TIDAL** background job.
- [x] Tag/rating edits update the visible table optimistically and restore the
  exact prior view with a clear error if the SQLite write fails.
- [x] Global Search filters by indexed Playlists, Events, Sources, or My Mixes
  without treating a liked-track-only membership as a searchable collection.
- [x] Empty collections now explain the relevant recovery path: clear filters,
  refresh TIDAL, sync a My Mix setlist, or associate watched-mix tracks.
- [x] Last.fm monthly, yearly, and all-time Top X history views.
- [ ] Future: optionally materialize a Last.fm Top X history view as a TIDAL
  playlist; the current history views are read-only.
- [ ] Future: VirtualDJ export, label confidence, compatible BPM/key/tag artist
  exploration, and scheduled cache/sync UI.

### Backend hardening and cutover

- [x] Add contract tests for settings/mappings and partial mutation failures.
- [x] Add contract tests for provider/job failure sanitization and
  refresh-version behavior.
- [x] Add contract tests for Last.fm status/import configuration handoff.
- [x] Add contract coverage for provider-auth failure reporting and secret
  redaction in background refresh jobs.
- [x] OpenAPI contract coverage checks React-critical routes and response
  fields; the React production build runs TypeScript validation.
- [x] Add a read-only SQLite collection performance probe and profile a 5k+
  row view.
- [x] Explicit launcher choice: `python main.py --ui dash|react`; Dash remains
  the default. Make React default only after verification and retain a rollback
  window before removal.

## Safety rules

- Auth remains Python-only: `.env`, Spotify/TIDAL caches, and connection state
  never enter React.
- Normal browsing/sort/filter/paging is SQLite-only; provider work is explicit
  background work or bounded entry refresh.
- Provider writes are provider-first, SQLite-second. Never test them live.
- Before changing, copying, rebuilding, backing up, or cleaning an existing
  SQLite table: stop the app/startup sync, tell the user, and make an external
  backup first. Independent new tables are okay.


## Resolved migration notes

- Tag edits are SQLite-only and update the visible view optimistically.
- My Mix YouTube/TIDAL URLs are editable and persist through the FastAPI job.
