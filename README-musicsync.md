# Spotify → TIDAL music sync

This is a local React/FastAPI music-library app that copies missing tracks in
either direction between Spotify and TIDAL playlists. It is deliberately
non-destructive: existing tracks are kept and tracks are never removed.

The **TIDAL cache** mapping direction only indexes the specified TIDAL playlist
in SQLite. It performs no Spotify reads or writes, participates in normal
manual and startup runs, and uses TIDAL's `last_updated` value to avoid fetching
unchanged playlist contents.

## Running the web application

Build the React frontend and start FastAPI:

```powershell
cd frontend
npm run build
cd ..
python react_app.py
```

`main.py` is an equivalent launcher and also owns the headless sync engine:

```powershell
python main.py
python main.py --sync
```

Both web launchers default to `http://127.0.0.1:8081`.

To measure the read-only SQLite preparation path for a large React collection,
without calling a provider or changing the library, run:

```powershell
python profile_library.py --collection search --limit 5000
```

The table keeps 200-row pages and restores at most 1,000 rows per view; this
probe helps decide when browser-side virtualization would become worthwhile.

## Project structure

- `main.py` contains the reusable sync engine and provider authentication.
- `react_app.py` launches the FastAPI API and built React SPA.
- `startup_sync.py` runs that engine without loading the web interface.
- `frontend/src/` owns the application shell, sidebar and feature UI.
- `backend/app/` owns the FastAPI routes and background jobs.
- `music_tools/liked_tracks/` owns provider-neutral TIDAL retrieval services.
- `music_library/database.py` owns the local SQLite catalogue, playlist
  membership index, and user-owned metadata schema.
- `backups/dash_app/` contains the retired Dash frontend for source reference;
  active code must not import it.

New browser tools live in `frontend/src/features`; reusable provider/service
logic remains in Python outside the presentation layer.

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

## Last.fm listening history

Add `LASTFM_API_KEY=...` to `.env`, restart the app, then open **Settings** and
enter your Last.fm username. **Import listening history** performs a complete
first import and incremental later imports. Scrobbles remain in their own
SQLite table with their original timestamps, enabling track play counts, last
played dates, and future monthly Top X views. Last.fm identities are matched
conservatively to indexed TIDAL tracks; ambiguous matches remain unmatched.

**Play count** and **Last played** are available in the Fields and Quick View
selectors on every shared track table. The selected-track panel also shows the
current count. Importing history reads Last.fm only and does not modify TIDAL.

## Setup

1. Install Python 3.10 or newer and run `pip install -r requirements.txt`.
2. Register a Spotify Web API app. Add
   `http://127.0.0.1:8888/callback` as a redirect URI. Port 8888 is reserved
   for the short-lived OAuth callback while the app runs on port 8081.
3. Set `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and
   `SPOTIPY_REDIRECT_URI` in your user environment. `.env.example` shows the
   names; the program intentionally does not load or store secrets in JSON.
4. Run `python react_app.py`, open `http://127.0.0.1:8081`, and connect both
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

For TIDAL → Spotify, `spotify_search_delay_seconds` stored in SQLite controls
the pause before each Spotify catalogue search (default `0.75`). This
reduces request bursts but does not reduce total daily quota consumption.

Tracks that fail catalogue matching are saved as mapping-specific unmatched
state in SQLite. Later runs count them as unmatched but do not
search for them again. To retry after a catalogue or matching change, delete
that mapping's relevant `spotify_to_tidal` or `tidal_to_spotify` unmatched list.

After a successful mapping run, the app saves `last_sync` and `source_version`
in SQLite. Spotify's source version is its API `snapshot_id`; TIDAL's
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
`music_sync.log`. The script runs every enabled mapping from SQLite,
does not start the web application, and exits with code 1 if authentication or any mapping
fails.

The TIDAL integration currently uses the unofficial `tidalapi` Python package.
Keep the dependency updated, and expect that TIDAL service changes can
occasionally require a package update.

## Hosted Google sign-in

Vercel deployments require a Google login before serving the application or
private API routes. Add the production callback to the Google Cloud Web OAuth
client's **Authorized redirect URIs**:

```text
https://YOUR-VERCEL-DOMAIN/api/v1/auth/google/callback
```

Configure these Vercel environment variables (Production and Preview as
appropriate):

```dotenv
GOOGLE_SIGNIN_CLIENT_ID=...
GOOGLE_SIGNIN_CLIENT_SECRET=...
GOOGLE_SIGNIN_REDIRECT_URI=https://YOUR-VERCEL-DOMAIN/api/v1/auth/google/callback
TUNEOPS_SESSION_SECRET=at-least-32-random-characters
TUNEOPS_ALLOWED_EMAILS=your-google-account@example.com
```

The existing `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are accepted as a
temporary fallback, but a separate sign-in client is clearer once YouTube
authorization and user login diverge. Google sign-in requests only
`openid email profile`; YouTube Analytics remains a separate connection.
Authentication turns on automatically on Vercel. Set
`TUNEOPS_AUTH_REQUIRED=true` only when testing the same behavior locally.

## YouTube Analytics for My Mixes

Enable the YouTube Data API v3 and YouTube Analytics API in Google Cloud, then
configure a Web OAuth client with this exact redirect URI:

```text
http://localhost:8081/api/v1/youtube/callback
```

The local `.env` values are:

```dotenv
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8081/api/v1/youtube/callback
```

Restart the backend, open **Settings**, and choose **Connect YouTube**. OAuth
tokens stay in the ignored `.youtube_oauth.json` file. Opening **My mixes →
Overview** refreshes the owner analytics automatically; the overview also keeps
a manual refresh button for retries. Returned analytics are cached in SQLite.

## Discogs metadata probe

To test Discogs coverage for labels, genres, and electronic styles, generate a
personal token under **Discogs Settings → Developers**, then add it to the local
`.env` file:

```dotenv
DISCOGS_USER_TOKEN=your_personal_token
```

Run a small read-only sample:

```powershell
python probe_discogs.py --limit 5
```

Or probe a particular cached TIDAL track:

```powershell
python probe_discogs.py --id 107839319
```

The probe searches Discogs releases and verifies the release tracklist before
accepting label, genre, or style metadata. It does not modify SQLite or either
music service.
