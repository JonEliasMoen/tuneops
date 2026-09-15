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
- `music_tools/liked_tracks/`: TIDAL liked-track retrieval, table presentation,
  selection behavior, infinite scrolling, and selected-track inspector.
- `music_library/database.py`: shared SQLite schema, TIDAL playlist cache,
  liked-track cache, reverse playlist membership lookup, and future user
  metadata storage.

New sidebar tools should live in `music_tools/<tool_name>/`. Keep provider and
database work outside presentation callbacks when practical. Shared layout and
styles belong in `music_tools/ui.py`.

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

Core tables:

- `tracks`: provider metadata keyed by provider and provider track ID.
- `playlists`: indexed playlist names and provider `last_updated` values.
- `playlist_tracks`: ordered membership with an index supporting
  track-to-playlists queries.
- `liked_track_snapshots` and `liked_tracks`: per-user ordered liked-track cache.
- `track_user_metadata`: reserved for star ratings and notes.
- `tags` and `track_tags`: normalized future tagging support.

Configured TIDAL playlists are indexed as playlist sync reads them. If the
provider `last_updated` value matches SQLite, membership is loaded locally.
Changed playlists are fetched and transactionally re-indexed. When sync adds
tracks, local membership is updated immediately and marked for provider
revalidation on the following run.

## Liked tracks UI

- Route: `/liked-tracks`.
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
- The right inspector displays selected-track metadata plus green playlist tags
  for every currently indexed TIDAL playlist containing that track ID.
- An Actions panel sits below the inspector. Right Arrow moves keyboard focus
  from the selected track into Add/Remove actions; Up/Down navigates, Enter or
  Right Arrow opens an action, and Left Arrow backs out. Add lists all indexed
  playlists; Remove lists only current memberships. Choosing a playlist calls
  TIDAL first, then mirrors a successful add/removal into SQLite and marks the
  cached playlist version for revalidation.
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
