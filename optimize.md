# TuneOps performance optimization plan

## Purpose

TuneOps was originally designed around local SQLite, where many small queries
and repeatedly materializing a few thousand rows are cheap. The primary database
is now remote Turso/libSQL over HTTP. The current API still works correctly, but
some request paths multiply network latency by opening several transactions and
loading complete collections before returning one page.

This document maps the current React -> FastAPI -> database -> React flow and
defines an optimization sequence. It is an implementation plan, not a database
migration. No live data or schema was changed while producing this review.

## Implementation status (2026-10-24)

The code-only optimization pass is complete. The shared collection path is now
bounded and server-side, read-only calls avoid Turso transaction overhead,
related reads can share one remote pipeline, provider mirrors use batched
writes, and request logs expose database costs. Navigation and local mix
discovery use short explicitly-invalidated process caches. Configuration,
artist, orphan, health, credential, action, and job paths no longer hydrate
unrelated state.

The remaining unchecked items below are deliberately deferred rather than
forgotten:

- measured indexes or other schema changes require an app stop, a fresh backup,
  and explicit approval before touching the existing database;
- production/Turso/Vercel latency targets require real environment benchmarks,
  which this test pass intentionally does not run;
- durable hosted jobs, durable cover storage, and YouTube stale-while-refresh
  are deployment/product architecture decisions rather than safe query cleanup;
- revision caches, optimistic concurrency, retries, cursor restoration, and a
  driver swap are optional follow-ups only if measurements justify the added
  complexity.

No live database rows, tables, or indexes were changed by this pass.

Observed baseline on 2026-10-22 from a local backend using remote Turso:

| Request | Before | Current | Note |
| --- | ---: | ---: | --- |
| `GET /api/v1/settings` | 7,121 ms | 3,318 ms | Narrow settings read already removed mapping fan-out; transport overhead remains. |
| `GET /api/v1/collections/liked/liked/tracks?offset=0&limit=200` | n/a | 15,181 ms | Loads and enriches the complete liked library before slicing 200 rows. |
| `GET /api/v1/navigation` | 11,803 ms | not remeasured | Intentionally left unchanged after the first settings fix. |

## Executive conclusion

Do not add Redis or pay for a larger Turso plan as the first performance fix.
The dominant problems are application-side round trips and query shape:

1. A single `connect()` against Turso currently starts a transaction, executes
   each SQL statement in a separate HTTP pipeline, commits, and closes the
   stream. Even a one-row read can therefore require several network requests.
2. The shared track browser always asks the repository for up to `1_000_000`
   base rows, attaches every relationship to every row, calculates filters and
   statistics in Python, and only then returns `offset:offset + limit`.
3. Infinite-scroll pages repeat that complete operation. Collection statistics
   are recalculated and retransmitted on every page even though they are the
   same for the active filter set.
4. Full document-shaped configuration reads and rewrites remain in several
   endpoints that only require one or two settings or mappings.

The first target should be bounded work: one page request must do work
proportional to the requested page size, not to the entire library.

## Performance budgets

Measure both local Python -> Turso and deployed Vercel -> Turso. Initial targets:

| Operation | Target p50 | Target p95 |
| --- | ---: | ---: |
| Cached settings/navigation read | < 250 ms | < 750 ms |
| First 200-track page without filters | < 750 ms | < 1,500 ms |
| Filtered/sorted 200-track page | < 1,000 ms | < 2,000 ms |
| Next infinite-scroll page | < 600 ms | < 1,200 ms |
| Small metadata mutation | < 750 ms | < 1,500 ms, excluding provider calls |
| Job status read | < 200 ms | < 500 ms |

These are engineering targets, not provider guarantees. Record response size,
database time, SQL execution count, remote pipeline count, and returned row
count alongside total request duration.

## Current database transport

Relevant code: `music_library/connection.py` and
`music_library/database.py:connect`.

### Findings

- `TursoConnection.__init__()` immediately sends `PRAGMA foreign_keys = ON` and
  `BEGIN` in a pipeline.
- Every `execute()` sends another HTTP request.
- Exiting every `connect()` context sends `COMMIT`, then a separate close
  request. Read-only queries pay write-transaction lifecycle costs.
- Repository helpers each open their own connection. One API request therefore
  creates many HTTP sessions/transactions instead of sharing one unit of work.
- `requests.Session` only helps within one short-lived connection. It is thrown
  away between repository helpers.
- `initialize()` is cached per Python process, but a fresh Vercel instance runs
  the complete schema script, duplicate cleanup, table inspection, backfill
  checks, and legacy migration checks again. This is especially expensive over
  HTTP and mixes startup/migration responsibility into ordinary queries.
- Synchronous requests are acceptable inside FastAPI's thread pool, but the
  number of blocking network calls must be bounded.

### Opportunities

- [x] Add a one-statement read-only Turso execution path that does not issue `BEGIN`,
  `COMMIT`, or a separate remote stream-close request for a simple SELECT.
- [x] Add a backend-neutral batch/pipeline abstraction so several SELECTs can
  be sent in one Turso HTTP request and still work with local SQLite.
- [ ] Introduce a request-scoped repository/unit-of-work connection. Service
  functions should accept an existing connection instead of opening one each.
- [x] Keep explicit transactions for mutations, but batch their statements in
  as few pipeline calls as possible.
- [ ] Separate schema migration from request-time initialization. Run migrations
  as an explicit deployment/startup step and let requests perform only a cheap
  schema-version readiness check when required.
- [ ] Add safe retry only for idempotent reads and connection setup. Do not
  blindly retry provider mutations or committed database writes.
- [ ] Evaluate the official libSQL client again when its Python/runtime support
  matches the deployed environment. Do not make a driver swap a prerequisite
  for fixing query shape.

Expected result: the already-narrow Settings query should fall well below its
current 3.3 seconds, and all later repository improvements gain the same benefit.

## Endpoint audit

### P0: shared collection track endpoint

Route:
`GET /api/v1/collections/{kind}/{collection_id}/tracks`

Flow:

1. `backend/app/api/library.py:tracks`
2. `backend/app/services/library.py:collection_page`
3. `descriptor()` performs collection-specific lookup work.
4. `_base_rows()` requests `limit=1_000_000` for every collection type.
5. `_attach_related()` separately loads playlists, My Mixes, watched mixes,
   artists, dimensions, full configuration, and Last.fm statistics for every
   base row.
6. `_matches()`, `_stats()`, and `_sort()` operate in Python.
7. The result is sliced to the requested page only at the end.

For liked tracks, the base load also looks up the latest liked user in a
separate transaction. With approximately 5,300 liked tracks, a 200-row request
still transfers and enriches all 5,300 rows. Every next page repeats it.

#### Required redesign

- [x] Create one collection-query repository with a shared SQL CTE that yields
  the track IDs and collection-specific `date_added`, `mix_position`, and source
  order for `liked`, `playlist`, `event`, `source`, `setlist`, `watched_mix`,
  `artist`, `search`, and `history`.
- [x] Translate title, artist, key, BPM, rating, tag, and collection-membership
  filters into SQL predicates.
- [x] Translate supported sorts into allowlisted SQL expressions. Preserve the
  current contract: missing values remain last in both directions and sort-off
  restores collection source order.
- [x] Compute `total` with `COUNT(*) OVER()` or a batched count query rather
  than materializing the complete result in Python.
- [x] Apply `LIMIT` and `OFFSET` before relationship enrichment.
- [x] Enrich only the visible page IDs. Prefer one query with JSON aggregation;
  otherwise pipeline a bounded set of relationship queries in one remote call.
- [x] Return stable source-order values from SQL so selection and restored scroll
  behavior remain unchanged.
- [x] Add query tests for every collection type, sort field, missing-value
  ordering, filters, duplicates, and page boundaries.

#### Collection statistics

The current response repeats top artists, every artist filter option, BPM range,
and top vibe on every page.

- [x] Move statistics to a separate query/result keyed by collection plus active
  filters, or include them only on the first page.
- [x] Calculate counts and min/max values with SQL aggregation.
- [ ] Cache statistics by a collection revision/version, not by an arbitrary
  long TTL. Invalidate after refreshes and local metadata mutations.
- [x] Do not make page 2 wait for statistics already returned with page 1.

#### Frontend request behavior

- [x] Replace `useDeferredValue` as the only search control with a real
  250-400 ms debounce. Deferred rendering does not guarantee request debouncing.
- [x] Cancel obsolete fetches using React Query's `AbortSignal` and pass the
  signal through `api()` to `fetch()`.
- [ ] Avoid restoring five 200-row pages through five complete server
  recomputations. After the SQL redesign this is less serious, but a cursor or
  a larger bounded restore request can reduce round trips further.
- [x] Keep the current stateful sort/filter/selection behavior; performance work
  must not reset table state.
- [ ] Consider gzip/Brotli for JSON responses after query work is bounded.

Expected result: the 15.2-second liked-track request should become a bounded
page query rather than a full-library export.

### P0: global search

Global search uses `tidal_library_tracks_page(limit=1_000_000)`, constructs a
deduplicated library in SQL, then applies text and relationship filters after
loading it into Python.

- [x] Reuse the new collection-query repository instead of maintaining a
  separate Python filter path.
- [x] Search only indexed memberships using an SQL CTE and page the result.
- [x] Initially use normalized indexed columns/`LIKE` for the current dataset.
- [ ] Consider SQLite FTS only after measuring. FTS introduces schema and sync
  complexity and is not necessary merely to eliminate the current full scan.

### P0: full configuration reads and writes

Relevant code: `music_library/config_store.py`, `main.load_config()`, and
`main.save_config()`.

Current full reads execute a query for metadata, settings, mappings, one
unmatched-track query per mapping, and two Quick View queries. Full writes
delete and rebuild every mapping, unmatched row, and Quick View even when one
setting changed.

Already completed:

- [x] `GET /settings` uses `load_settings_bundle()` and one SQL statement.
- [x] The shared frontend Settings query stays fresh for five minutes and
  autosave updates it immediately.

Remaining:

- [x] Add `load_runtime_settings()` for callers that need only settings; do not
  make jobs, history, artist pages, or track enrichment load mappings.
- [x] Add `load_sync_mappings()` using a join or JSON aggregation instead of an
  unmatched-track N+1 query.
- [x] Replace Settings autosave's full `save_config()` with a narrow settings
  and Quick View transaction.
- [x] Replace mapping autosave's full document rewrite with mapping-specific
  upsert/reorder/delete operations.
- [x] Preserve unknown JSON fields and stable mapping IDs in all narrow paths.
- [ ] Add optimistic concurrency/version checking so two saves cannot silently
  overwrite each other.

### P0/P1: navigation

Route: `GET /api/v1/navigation`.

The route currently combines:

- indexed playlist lookup;
- a narrow runtime-settings read;
- one combined Last.fm month/year query (previously two remote reads);
- `discover_mixes()`, which queries setlist/analytics metadata and scans every
  local mix directory/positions file;
- watched-mix lookup.

This explains why navigation can be slower than the page it frames.

- [x] Replace the full configuration read with `load_runtime_settings()`.
- [x] Combine Last.fm year/month navigation into one grouped database query.
- [ ] Build a `navigation_snapshot()` repository operation that pipelines or
  combines playlist, history, setlist, and watched-mix metadata reads.
- [x] Cache the assembled navigation response in process for 30-60 seconds.
- [x] Invalidate it explicitly after mapping changes, provider refreshes,
  watched-mix changes, setlist imports, orphan cleanup, and relevant settings
  changes.
- [x] Separate local mix-folder discovery from database metadata and cache the
  filesystem snapshot by directory modification state. Vercel deployments with
  no local mix root should skip the scan immediately.
- [ ] Add `ETag`/conditional GET after server-side invalidation is reliable.

### P1: Artists overview and history

`GET /artists` first performs a full config load to obtain `lastfm_username`.
The artist repository then executes the same expensive library CTE once for the
total and again for the page.

- [x] Use the narrow runtime settings read.
- [x] Return total with a window function or pipeline count and data queries.
- [x] Materialize/reuse the indexed-library membership CTE in the query design.
- [x] Debounce artist search and cancel obsolete requests.
- [ ] Ensure artist and Last.fm indexes support the final query plan; confirm
  with `EXPLAIN QUERY PLAN` against a copied database before adding indexes.

History track views should use the same page/enrichment repository as other
collections rather than converting a top-X result and then running the generic
full enrichment flow.

### P1: bulk dimensions and tags

Routes: `PUT /tracks/dimensions` and `POST /tracks/dimensions/toggle`.

- `update_dimensions` calls a transactional database function once per selected
  track, then reads all dimensions again.
- `toggle_dimensions` reads current values, opens one write transaction per
  changed track, then performs a second full read.
- Individual toggle helpers contain additional per-value SELECT/DELETE/INSERT
  loops.

Actions on a multi-selected set therefore multiply remote transactions.

- [x] Add bulk replacement/toggle repository methods that accept all track IDs
  and use one transaction.
- [x] Fetch current values once, calculate changes once, and use batched deletes
  and inserts.
- [x] Return the updated rows from the same unit of work where practical.
- [x] Preserve dimension cardinality rules atomically.

### P1: playlist and like actions

Provider calls may need to remain sequential for safety, but local database
mirroring does not need one transaction per track.

- [x] Fetch selected cached tracks in one query for bulk Like.
- [x] Apply successful liked memberships in one database transaction.
- [x] Apply successful playlist membership changes in one transaction and
  compact/recalculate positions once per playlist.
- [x] Query destination/source playlist records directly by ID instead of
  loading all indexed playlists twice for Move.
- [x] Keep the provider-first and rollback behavior unchanged.

### P1: provider cache imports and sync writes

The main cache writers (`store_tidal_playlist`, `store_tidal_setlist`,
`store_tidal_liked_tracks`, and parts of `merge_tidal_liked_tracks_prefix`)
iterate through tracks and issue separate upserts for the canonical track,
artists, artist relationships, and membership. Local SQLite handles this pattern
well inside one transaction. The current Turso adapter turns most individual
`execute()` calls into separate HTTP requests, so a provider refresh can spend
more time mirroring results than fetching them.

- [x] Normalize provider objects into track, artist, relationship, and membership
  row batches before opening the write transaction.
- [x] Use `executemany()`/pipeline batches for track upserts, artist upserts,
  relationship replacement, and membership insertion.
- [ ] Chunk large writes by a measured payload/statement limit rather than by
  one row per request.
- [x] Preserve the atomic replacement semantics for each playlist/setlist.
- [ ] Avoid updating unchanged canonical track metadata when a fingerprint or
  compared row proves it is identical, if measurement shows this is worthwhile.
- [x] Keep Last.fm's existing batched insert/update approach and apply the same
  pattern consistently to TIDAL cache writers.

### P1: job persistence and polling

The browser polls `GET /jobs/{id}` every 750 ms. On a Vercel instance without
the job in memory, each poll performs a remote database transaction. Every job
progress message also opens and commits a separate database transaction.

Vercel jobs currently run synchronously inside the initiating function because
ordinary background threads are not durable. That means the browser cannot
start polling until the POST response returns, so intermediate progress cannot
reliably appear there even though each progress update is persisted.

- [x] Throttle persisted progress updates (for example at most once per second
  or when phase/percentage materially changes).
- [x] Use a read-only one-shot query for job status.
- [x] Back off frontend polling from roughly 0.75 s to 1-2 s, then slower for
  long jobs; stop immediately on terminal state.
- [ ] Define the hosted job architecture explicitly: Vercel wait-until/queue,
  an external worker, or another durable execution service. Polling versus SSE
  is secondary; the work first needs to outlive a request.
- [x] Keep persisted terminal job records so another serverless instance can
  serve the result.
- [ ] Add retention cleanup for old `app_jobs` rows.

Redis would only become useful here if TuneOps later needs cross-instance
ephemeral progress/pub-sub. It should not be introduced as a cache in front of
inefficient library queries.

### P1: health and credentials

`GET /health` checks Spotify and TIDAL credentials separately. With database
credential storage enabled, that means two remote transactions.

- [x] Fetch all required provider connection metadata for the current user in
  one query.
- [x] Cache non-secret connection status briefly and invalidate after credential
  writes/refreshes.
- [x] In `save_credentials`, avoid reopening the database to return metadata
  that was just written.
- [x] Never cache decrypted credential payloads beyond the minimum provider
  client lifetime and never include secrets in timing logs.

### P1/P2: My Mixes and watched mixes

- `discover_mixes()` calls `setlist_metadata()` and rereads every local
  `positions.txt` on each invocation.
- `mix_for()` and `cover_for()` rediscover every mix rather than resolving one
  folder directly.
- My Mix and watched-mix detail routes fetch live YouTube metadata during the
  user-facing request.
- Saving two My Mix URLs performs two independent database writes, then calls a
  detail path that scans the filesystem and may call YouTube.
- Watched-mix covers perform a database existence read before checking the
  cached file. Local files are ephemeral on Vercel.

Opportunities:

- [ ] Serve cached `youtube_video_metadata` immediately and refresh stale
  metadata explicitly or in a job. Do not block detail rendering on YouTube.
- [x] Cache the local mix directory snapshot for a short period and invalidate
  after saved URL/setlist changes.
- [x] Resolve a single safe folder directly for detail/cover paths instead of
  scanning every folder.
- [x] Save both My Mix URLs in one database transaction.
- [ ] Decide on durable object storage for watched-mix covers before relying on
  them in serverless production. Until then, remote YouTube thumbnails may be a
  more reliable hosted fallback.
- [x] Avoid repeated `discover_mixes()` calls inside one YouTube analytics job;
  capture the list once and reuse it.

### P2: event media, playlist pickers, and authentication

- Event media detail validates its event through a query that loads every
  indexed playlist, then opens another transaction for the links. Saving repeats
  validation, write, and reread across separate transactions.
- The playlist-sync picker correctly caches provider playlist enumeration for
  five minutes, but the cache is process-local and is lost across Vercel
  instances. Its remaining slowness is provider/network work, not a reason to
  cache arbitrary library pages.
- TuneOps Google session validation is signed-cookie based and does not perform
  a database lookup on every request. The login callback's external Google
  exchange is not part of the ordinary database hot path.

Opportunities:

- [x] Query an event directly by provider playlist ID and collection type.
- [x] Read or return event links within the same repository unit of work as
  validation/write.
- [x] Keep the provider playlist picker cache, add explicit refresh if needed,
  and measure provider time separately from database time.
- [ ] Only add a shared playlist-picker cache if serverless cache misses are a
  demonstrated usability issue; persisted provider snapshots may fit the
  existing database-first design better than Redis.
- [x] Keep auth session verification database-free. Any future user lookup
  should be narrowly cached and must preserve account-disable semantics.

### P2: orphaned tracks

The orphan view correctly uses SQL pagination, but it runs a count and data
query sequentially. Each row also contains correlated counts for tags,
dimensions, and Last.fm plays.

- [x] Use a window count or pipeline the count/page queries.
- [x] Rewrite correlated counts as pre-aggregated joins if query-plan evidence
  shows repeated scans.
- [ ] Consider an index beginning with `lastfm_scrobbles.tidal_track_id`; the
  current index begins with username and may not help orphan queries that do not
  constrain username.

### P2: static and low-volatility API data

- [x] Cache `/dimensions` indefinitely in React Query; it is compiled static
  data and currently inherits the global 30-second stale time.
- [x] Give local cover responses long cache headers plus validation identifiers.
- [x] Avoid refetching `/playlist-options` and `/watched-mixes` every time the
  inspector remounts; use deliberate invalidation after mutations.
- [ ] Add response compression only after measuring payload sizes.

## Index review candidates

Do not add indexes speculatively. Capture the final SQL, run `EXPLAIN QUERY PLAN`
against a copied database, then add only indexes that eliminate demonstrated
scans/sorts.

Likely candidates:

- `track_dimension_values(provider, dimension, value, provider_track_id)` for
  dimension/rating filters.
- `lastfm_scrobbles(tidal_track_id, played_at)` for orphan/global per-track
  aggregation that does not constrain username first.
- `watched_mix_tracks(video_id, position)` if ordered mix reads show a temp sort.
- Normalized/search columns or FTS only if indexed `LIKE` queries remain a
  measured bottleneck.

Important safety gate: adding or changing indexes touches existing live tables.
Per `AGENTS.md`, stop the app/startup sync, take a backup, tell Jon exactly what
will change, and receive confirmation before applying such a migration. Query
and repository refactors can be developed and tested against temporary copies
before this gate.

## Caching strategy

Use caching only after bounding the underlying queries.

### Good cache candidates

- Settings and Quick Views: five-minute frontend freshness plus immediate
  mutation updates is already in place.
- Navigation snapshot: short server TTL plus explicit invalidation.
- Collection statistics: keyed by collection/filter signature and collection
  revision.
- Static dimension catalog: effectively immutable for one frontend build.
- Provider playlist pickers: existing session cache is appropriate, although
  serverless instances cannot share it.
- Cached YouTube metadata and analytics: stale-while-revalidate semantics.

### Poor cache candidates

- Whole track-page responses with arbitrary filters, sorts, and offsets.
- Decrypted credentials.
- Mutable playlist membership without a revision/invalidation key.
- Redis as a mask over full-library reads.

Redis should be reconsidered only when there is a demonstrated cross-instance
need such as job progress/pub-sub, rate-limit coordination, or a very hot shared
navigation/statistics cache. It adds another network dependency and does not
replace correct SQL pagination.

## Observability before and during implementation

- [ ] Assign a stable operation name to every repository call.
- [x] Track per-request database connections, SQL statements, Turso pipeline
  HTTP calls, database milliseconds, rows decoded, and response bytes.
- [x] Add these totals to the existing `http.complete` log without SQL values or
  sensitive parameters.
- [x] Add a `Server-Timing` header in development so browser timings can be
  compared with database time.
- [x] Add slow-operation logs at 250 ms, then tune the threshold from evidence.
- [x] Create a read-only profiling script that exercises representative routes
  against local SQLite and configured Turso, emits a compact table, and never
  calls Spotify/TIDAL/YouTube.
- [ ] Benchmark cold process, warm process, first page, next page, sorted page,
  filtered page, and empty result.
- [x] Track p50/p95 rather than judging one request.

Never log authorization headers, credential blobs, provider tokens, query text
entered by the user, or full SQL parameter values.

## Recommended implementation order

### Phase 1 - make costs visible

1. Add database/pipeline timing counters and request summary logging.
2. Add the read-only profiling script and baseline tests.
3. Record local SQLite, local-to-Turso, and Vercel-to-Turso baselines.

### Phase 2 - remove transport multiplication

1. Implement one-shot read-only Turso execution.
2. Implement batched/pipelined reads and request-scoped repository access.
3. Move schema migration out of normal request initialization.
4. Remeasure Settings and simple one-row endpoints.

### Phase 3 - fix the shared track browser path

1. Implement SQL collection membership CTEs.
2. Add server-side filters, sorting, count, and pagination.
3. Enrich only the current page.
4. Separate/cache statistics.
5. Add frontend debounce and cancellation.
6. Verify all collection types and persistent table state.

This phase should deliver the largest visible improvement.

### Phase 4 - narrow configuration and navigation

1. Add runtime-settings and sync-mapping repositories.
2. Narrow Settings and mapping writes.
3. Build and cache a navigation snapshot with explicit invalidation.
4. Replace remaining settings-only `load_config()` calls.

### Phase 5 - bulk mutations and jobs

1. Batch dimension/tag writes.
2. Batch local liked/playlist membership mirrors.
3. Throttle job persistence and reduce polling pressure.
4. Choose a durable hosted job execution model.

### Phase 6 - measured indexes and secondary endpoints

1. Capture query plans from the new SQL.
2. Coordinate app stop and backup.
3. Add only proven indexes.
4. Optimize artist, orphan, mix, health, and metadata endpoints from recorded
   timings.

## Verification requirements

Every optimization must preserve behavior, not merely improve a happy-path
benchmark.

- [x] Repository tests use temporary SQLite databases and assert exact paging,
  filters, sorts, statistics, and relationship payloads.
- [x] Transport tests assert the number of remote pipeline calls for representative
  reads and writes without contacting live Turso.
- [x] API tests verify response schemas and error boundaries.
- [x] React tests verify debounce/cancellation, infinite paging, state restore,
  selection, and keyboard navigation.
- [x] Performance regression tests use query/pipeline counts rather than fragile
  wall-clock limits in CI.
- [x] No test makes live Spotify, TIDAL, Last.fm, YouTube, or Turso calls.
- [x] Full Python tests, frontend tests, and production build pass after every
  phase.

## Definition of done

The optimization project is complete when:

- a 200-row page never loads/enriches the full library;
- next-page requests do not recompute unchanged collection statistics;
- ordinary read endpoints do not open write transactions;
- request logs expose database/pipeline cost without secrets;
- settings, navigation, health, and jobs no longer load unrelated data;
- bulk metadata actions use bounded transactions rather than one transaction per
  selected track;
- measured targets are met from both local development and the hosted app; and
- Redis or a paid database tier is considered only with benchmark evidence that
  the remaining latency is infrastructure-bound.
