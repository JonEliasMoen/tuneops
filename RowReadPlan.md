# TuneOps row-read remediation plan

Last reviewed: 2026-11-02.

## Implementation status

- [x] Define `lastfm_track_totals` and compact `lastfm_import_state` schema.
- [x] Add an idempotent, verified legacy-to-aggregate rebuild helper. It is
  intentionally non-destructive until the coordinated cutover.
- [x] Lock the design to matching against already indexed TuneOps TIDAL tracks;
  importing Last.fm must never search TIDAL.
- [x] Stop writers and run the aggregate backfill against the selected working
  database. `tuneops-w.sqlite3` retained 43,549 matched plays across 4,318
  tracks and 128 months; the pre-cutover copy is under `backups/`.
- [x] Change collection, Artists, orphan, Settings, History, and MCP reads to
  aggregate-only queries.
- [x] Change incremental Last.fm import to match locally, discard unmatched
  rows, update aggregates transactionally, and advance the watermark.
- [x] Verify all-time/monthly totals, then remove the legacy raw table and its
  active code paths.
- [x] Persist a schema-version marker and add process-local initialization
  caching. On the measured local smoke test this reduced a five-row Liked
  request from 201 to 9 SQL statements, Last.fm status from 134 to 9, and
  Artists from 134 to 6.
- [ ] Move future schema-version upgrades to an explicit pre-deploy migration
  command; a missing/outdated marker still performs the compatibility migration
  once today.
- [ ] Complete the remaining collection-statistics, frontend-fetch, and
  query-budget phases below.

## Why this exists

The Turso free allowance of 500 million rows read was exhausted in roughly one
day of normal TuneOps use plus one backup/restore cycle. The database contains
only about 136,000 application rows, so copying the 27.7 MB backup cannot by
itself explain that consumption.

The dominant amplification is in interactive collection queries:

- `music_library.collection_query._query_parts()` aggregates all matched rows
  in `lastfm_scrobbles` to calculate play count and last played for every
  track-table page.
- The current raw history contains roughly 78,000 rows. Loading five 200-row
  pages can therefore repeat that raw aggregation five times.
- First-page collection statistics run a separate query built from the same
  CTE. Liked Tracks now skips those statistics, but its normal page query still
  aggregates the raw history.
- Other collection routes, Artists, orphan inspection, and a few Settings/MCP
  reads also aggregate raw scrobbles.
- Restoring a saved browser state can automatically fetch up to 1,000 tracks.
- A fresh serverless process may run schema, cleanup, backfill, and migration
  checks through `database.initialize()` before serving normal requests.

The Turso portal counts work performed by the query, not merely result rows.
Joins, grouping, window functions, correlated subqueries, repeated pages, and
repeated CTE evaluation can therefore cost far more than the returned page.

## Non-negotiable target

Normal interactive browsing must never aggregate or scan the complete raw
Last.fm history. Its cost must scale with the requested page and a bounded
number of relationships, not with total lifetime scrobbles.

Initial engineering budgets:

- Target fewer than 10,000 estimated rows read for a normal page/API request.
- Stop and review any interactive query estimated above 25,000 rows read.
- Stop and review every interactive full-table scan once the table can exceed
  10,000 rows, even if it is currently small.
- An explicit import, rebuild, migration, or maintenance job may scan a large
  table once. It must not repeat that scan per track, page, month, or poll.
- Polling endpoints must remain indexed, single-purpose, and constant-cost.

These are guardrails rather than promises about Turso's exact billing counter.
They should be tightened after production measurements are available again.

## Phase 0: freeze and establish a baseline

- Keep the clean 27.7 MB SQLite backup as the immutable rollback point.
- Do query work against a copied local SQLite database until Turso is usable.
- Record table counts and run `EXPLAIN QUERY PLAN` for:
  - Liked Tracks first page and a later page.
  - A playlist first page with and without collection statistics.
  - Global search.
  - Artists overview and artist detail.
  - History navigation/month/year/overall.
  - Settings, orphaned tracks, and MCP collection reads.
- Build a request-to-query inventory. Include automatic React Query refetches,
  saved-page restoration, navigation loading, provider checks, and job polling.
- Do not infer safety from response size. A 20-row result can still scan the
  entire history table.

No live-table mutation is required for this phase.

## Last.fm storage decision

TuneOps does not need a permanent raw Last.fm event store in its operational
database. The product only needs scrobbles that can be matched to an indexed
TIDAL track, represented as:

- One all-time total per user and TIDAL track.
- One monthly total per user, month, and TIDAL track.
- A small import watermark/state row so incremental imports are resumable.

Matching is strictly local against TIDAL tracks already indexed in TuneOps.
Last.fm import must never search the live TIDAL catalogue, create a canonical
track, or make any TIDAL provider call. Unmatched scrobbles are discarded
during import and are not retained for a possible future match. Consequently,
a track indexed after an unmatched play will not gain that historical play,
which is an accepted product tradeoff.
Last.fm corrections or deletions to old plays are also ignored unless the user
explicitly runs a complete aggregate rebuild from the provider.

There is no raw-query fallback. Missing or invalid aggregate state is a visible
repair condition: History and play counts should be unavailable until an
explicit import/rebuild repairs it. They must never silently scan the legacy
raw table.

## Phase 1: replace raw Last.fm history with aggregate-only storage

### 1. Add compact per-track totals

Add an independent `lastfm_track_totals` table with one row per user and
matched TIDAL track:

```sql
CREATE TABLE IF NOT EXISTS lastfm_track_totals (
    username TEXT NOT NULL,
    tidal_track_id TEXT NOT NULL,
    play_count INTEGER NOT NULL,
    last_played INTEGER NOT NULL,
    PRIMARY KEY (username, tidal_track_id)
);
```

`lastfm_track_totals` serves normal track tables and inspectors.
`lastfm_monthly_track_counts` remains the source for month/year History views.
After migration, these aggregate tables are authoritative for TuneOps.

Backfill is one explicit maintenance operation:

```sql
INSERT INTO lastfm_track_totals(...)
SELECT username, tidal_track_id, COUNT(*), MAX(played_at)
FROM lastfm_scrobbles
WHERE tidal_track_id IS NOT NULL
GROUP BY username, tidal_track_id;
```

This is a one-time conversion from the legacy table, not an ongoing fallback.
Rebuild `lastfm_monthly_track_counts` in the same migration, verify all matched
play totals, then retire/drop `lastfm_scrobbles`. Do not run this migration
against the live primary until the user confirms the app/background writers
are stopped and the backup is current.

### 2. Add compact import state

Add a small `lastfm_import_state` table containing the username, last committed
provider timestamp/watermark, last successful import time, and aggregate
validity/status. Update the watermark only in the same transaction as the
corresponding aggregate increments.

- Fetch only provider rows newer than the committed watermark.
- Match each fetched row conservatively to an indexed TIDAL track.
- Discard unmatched rows immediately.
- Increment the all-time and monthly aggregate rows for matched plays.
- Advance the watermark only after those increments commit.
- Make overlapping/retried imports idempotent. If a strict provider timestamp
  watermark cannot guarantee this, retain only a small bounded recent-import
  deduplication ledger, never the lifetime event history.
- Add tests for duplicate imports, interrupted pages, equal/overlapping
  timestamps, unmatched rows, latest-play changes, and rebuild idempotency.

### 3. Replace all raw-history reads

- Change the `plays` CTE in `collection_query.py` to an indexed join against
  `lastfm_track_totals`.
- Change Artists overview to sum compact totals through `track_artists`.
- Change per-track Last.fm stats to use the totals table.
- Change orphan inspection to use totals rather than grouping raw history.
- Audit MCP reads so they reuse the same bounded repositories.
- Remove raw-history fallback from History navigation and month/year/overall
  queries. Missing aggregate state returns a repair-required result.
- Remove normal import, reconciliation, Settings, MCP, and admin dependencies
  on `lastfm_scrobbles` before dropping the legacy table.

### 4. Cache user-level import summary

Settings currently calculates total, matched, and latest directly from raw
scrobbles. Store matched total and latest in the import-state/summary row and
update them after import/rebuild. Because unmatched plays are discarded,
TuneOps reports matched imported plays rather than the provider's lifetime
scrobble count. Settings must not count aggregate rows on every visit.

### 5. Retire the legacy raw table

- Verify that the sum of `lastfm_track_totals.play_count` equals the sum of
  `lastfm_monthly_track_counts.play_count` for each user.
- Verify month/year/overall Top X and representative per-track counts against
  the clean backup.
- Preserve the clean pre-migration backup outside the live database.
- Stop writers, run the verified migration, then drop `lastfm_scrobbles` from
  the live schema. This is destructive and requires explicit confirmation.
- Do not recreate the table during initialization or future migrations.

## Phase 2: make collection statistics optional and bounded

- Keep Liked Tracks statistics disabled unless a dedicated cached solution is
  implemented.
- Do not couple statistics to the first track-page response. Load them lazily
  only where they materially improve the page.
- Cache statistics by collection identity plus membership/version fingerprint.
  Invalidate on membership or relevant metadata changes.
- Ensure filters cannot turn each stats branch into a separate lifetime-history
  aggregation.
- Consider replacing the complete Artist dropdown with searchable suggestions
  when a collection becomes large.
- Add query-shape tests asserting collection browsing SQL does not reference
  `lastfm_scrobbles`.

## Phase 3: remove schema work from request handling

`database.initialize()` is process-local. Every new Vercel function instance
can therefore repeat schema creation, duplicate cleanup, column inspection,
artist backfill checks, and legacy migrations.

- Introduce an explicit, versioned migration command run before deployment or
  as a controlled administrative operation.
- Store the applied schema version in the database.
- Normal read endpoints may verify a version with one indexed/single-row read,
  but must not execute `SCHEMA`, cleanup deletes, table scans, or backfills.
- Keep test-database creation convenient through a separate initialization
  helper.
- Never run legacy data cleanup on every serverless cold start.

Current progress: a current `app_schema_meta` marker now makes cold-start
initialization one bounded version read, while a warm process performs no
initialization SQL. The remaining work in this phase is to make a future schema
version mismatch fail closed with an explicit migration command instead of
running the compatibility migration from a request.

This phase changes migration lifecycle and needs careful local and preview
verification before production cutover.

## Phase 4: control frontend and serverless amplification

- Inventory every automatic fetch on route entry. One user navigation should
  not cause duplicate collection, navigation, settings, or provider requests.
- Preserve stateful track browsing, but do not automatically restore five
  expensive pages until the backend query is proven bounded.
- Give React Query deliberate `staleTime`, focus-refetch, retry, and invalidation
  policies. Avoid retry storms when Turso returns quota or timeout errors.
- Keep job polling constant-cost and stop polling terminal/missing jobs.
- Cache stable navigation/settings data process-locally or client-side with
  explicit invalidation. Do not introduce Redis until SQL work is bounded;
  Redis would mask rather than fix these scans.

## Phase 5: measurement and regression protection

- Log per-request database statement count, pipeline count, returned rows,
  bytes, and duration without logging SQL parameters or secrets.
- Add a development-only query fingerprint/name so expensive endpoint classes
  can be identified without exposing user input.
- Run representative endpoints against the copied production-size SQLite
  backup and retain benchmark results.
- Add tests that fail when:
  - Active application SQL references legacy `lastfm_scrobbles` after cutover.
  - A page performs per-row database calls.
  - First-page stats execute unexpectedly.
  - A serverless request invokes schema migration/backfill work.
- After Turso is available, measure one week of ordinary use before deciding on
  a database-platform migration.

## Acceptance criteria

- The live schema no longer contains `lastfm_scrobbles` after verified cutover.
- Liked Tracks, playlists, search, mixes, and artist detail join compact
  `lastfm_track_totals` by indexed keys.
- Loading/restoring five pages performs bounded indexed reads rather than five
  lifetime-history scans.
- Artists overview and Settings use compact aggregates.
- History views use `lastfm_monthly_track_counts` with no raw fallback. Invalid
  state explicitly requests an import/rebuild.
- A Vercel cold start does not execute data cleanup, backfill, or legacy
  migration queries.
- Production metrics show normal use comfortably below the monthly allowance,
  with enough headroom for imports and backups.

## Optional analytical store

Do not add one for the current requirements. All-time and monthly aggregates
answer the TuneOps UI without raw events.

If future features genuinely require event-level analysis such as listening
time by hour, sessions, streaks, or provider corrections, create a separate
offline analytical archive containing matched events only. Prefer compressed
Parquet/object storage queried on demand with DuckDB or a purpose-built
analytical service. It must not sit in the Turso request path, participate in
navigation, or become an automatic fallback for the application database.

## Platform decision after remediation

Do not migrate databases merely to hide full scans. PostgreSQL would remove
Turso's row-read billing model, but TuneOps currently relies on SQLite-specific
SQL and behavior (`PRAGMA`, `sqlite_master`, `INSERT OR IGNORE`, `strftime`,
`julianday`, and the custom Hrana transport). That migration is significant and
the bad queries would remain bad.

After the above phases:

- Stay on Turso if normal monthly reads have comfortable headroom and latency
  is acceptable.
- Use a paid Turso plan as temporary breathing room, not as a substitute for
  remediation. A 2.5-billion-row allowance is only five times the exhausted
  free allowance.
- Prefer managed PostgreSQL over Azure SQL/SQL Server if a platform migration
  is still justified, because it is the smaller dialect and ecosystem jump.

## Marketplace plan issue

The current Turso database was provisioned through Vercel Marketplace, but the
Marketplace configuration UI shows a locked region selector with a contradictory
"This field is required" validation error and never loads available plans. Treat
that as a provisioning/billing UI problem, not an application workaround.
Capture the screenshot and integration/database identifiers for Vercel/Turso
support. Do not create more databases merely to reset quota; usage is generally
account/integration scoped and the query amplification would remain.

