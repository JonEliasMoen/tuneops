# Spotify → TIDAL music sync

This is a local Dash app that copies missing tracks in either direction between
Spotify and TIDAL playlists. It is deliberately non-destructive: existing
tracks are kept and tracks are never removed.

The **TIDAL cache** mapping direction only indexes the specified TIDAL playlist
in SQLite. It performs no Spotify reads or writes, participates in normal
manual and startup runs, and uses TIDAL's `last_updated` value to avoid fetching
unchanged playlist contents.

## Project structure

- `musicsync.py` contains the reusable sync engine and remains the command-line
  entry point.
- `startup_sync.py` runs that engine without loading the web interface.
- `music_tools/ui.py` owns the shared application shell, sidebar, and styling.
- `music_tools/playlist_sync/page.py` owns the playlist-sync page, its Dash
  layout, authentication routes, and callbacks.
- `music_tools/liked_tracks/` owns the TIDAL liked-tracks browser and its
  provider-to-table data mapping.
- `music_library/database.py` owns the local SQLite catalogue, playlist
  membership index, and user-owned metadata schema.

New sidebar tools should live in their own `music_tools/<tool_name>/` package.
Shared navigation and presentation belong in `music_tools/ui.py`; reusable
service logic should remain independent of Dash so startup jobs can import it.

## Local music library

Playlist sync maintains `music_library.sqlite3` for every configured TIDAL
playlist it reads. A playlist's TIDAL `last_updated` value is compared with the
stored version; unchanged playlist membership is loaded locally, while changed
playlists are fetched and atomically re-indexed. The database is local-only and
ignored by Git. Set `MUSICSYNC_DATABASE` to override its location.

The membership table is indexed by track ID, so later tools can efficiently
look up every indexed playlist containing a track. Provider metadata is kept
separate from user-owned metadata. Tables for star ratings, notes, tags, and
track-to-tag relationships are already present for future features.

The liked-tracks page stores its latest per-user snapshot in SQLite. Automatic
loads reuse snapshots up to five minutes old; **Refresh** always starts again
with the newest tracks from TIDAL. More pages are retrieved and appended to the
cache as the table reaches its scroll boundary. Its inspector uses the same
database to list every indexed playlist containing the selected TIDAL track ID.

## Setup

1. Install Python 3.10 or newer and run `pip install -r requirements.txt`.
2. Register a Spotify Web API app. Add
   `http://127.0.0.1:8888/callback` as a redirect URI. Port 8888 is reserved
   for the short-lived OAuth callback while Dash runs on port 8050.
3. Set `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and
   `SPOTIPY_REDIRECT_URI` in your user environment. `.env.example` shows the
   names; the program intentionally does not load or store secrets in JSON.
4. Run `python musicsync.py`, open `http://127.0.0.1:8050`, and connect both
   accounts. TIDAL uses a device-link login and saves refreshable credentials
   locally in `.tidal_session.json`.
5. Add playlist mappings, choose **Spotify → TIDAL** or **TIDAL → Spotify**,
   save, and click **Sync now**. Leave the target service ID blank to create a
   playlist during the first sync; the new ID is saved.

Changing to bidirectional support adds Spotify playlist-write permissions. Use
**Connect Spotify** again once after upgrading so the cached token receives the
new scopes.

Spotify playlists may be entered as IDs or URLs. TIDAL targets may likewise be
IDs or URLs. Matching prefers ISRC and falls back to normalized title + artist.
Unmatched counts are shown after every run.

For TIDAL → Spotify, `spotify_search_delay_seconds` in `music_sync.json`
controls the pause before each Spotify catalogue search (default `0.75`). This
reduces request bursts but does not reduce total daily quota consumption.

Tracks that fail catalogue matching are saved under the mapping's `unmatched`
object in `music_sync.json`. Later runs count them as unmatched but do not
search for them again. To retry after a catalogue or matching change, delete
that mapping's relevant `spotify_to_tidal` or `tidal_to_spotify` unmatched list.

After a successful mapping run, the app saves `last_sync` and `source_version`
in `music_sync.json`. Spotify's source version is its API `snapshot_id`; TIDAL's
is a local fingerprint of the ordered source tracks. Unchanged sources are
skipped before destination comparison or catalogue searches. Delete either
field to force a full sync of that mapping.

## Startup sync

After one successful interactive login to each service, run:

```powershell
python startup_sync.py
```

Use that command in Windows Task Scheduler with the script directory as the
working directory. Select “Run only when user is logged on” for the simplest
access to the same environment variables and token files. Output is written to
`music_sync.log`. The script runs every enabled mapping from `music_sync.json`,
does not start Dash, and exits with code 1 if authentication or any mapping
fails.

The TIDAL integration currently uses the unofficial `tidalapi` Python package.
Keep the dependency updated, and expect that TIDAL service changes can
occasionally require a package update.
