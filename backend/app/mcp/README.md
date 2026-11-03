# TuneOps MCP

TuneOps exposes a bounded MCP API for ChatGPT. Read tools inspect TuneOps or
search TIDAL; the single write tool requires explicit approval and updates
TIDAL before mirroring the result into TuneOps.

## Tools

| Tool | Scope | Purpose |
| --- | --- | --- |
| `get_tuneops_profile` | `profile:read` | Returns the connected TuneOps account and safe provider connection statuses. |
| `search_tracks` | `library:read` | Searches the live TIDAL catalogue by track, remix, artist, or album. Supports a bounded result limit, cursor, and optional BPM range. |
| `get_track` | `library:read` | Returns metadata and TuneOps information for one exact TIDAL track ID. |
| `list_collections` | `library:read` | Lists indexed collections, optionally filtered by collection type and name. Includes Playlists, Events, Sources, mixes, and other supported collection types. |
| `get_collection_tracks` | `library:read` | Returns one bounded page from an exact TuneOps collection, with cursor-based pagination and optional sorting. `kind=liked`, `collection_id=liked` reads Liked Tracks newest-first by default. |
| `get_track_memberships` | `library:read` | Shows which TuneOps collections contain up to 50 exact TIDAL track IDs. |
| `list_my_mixes` | `library:read` | Lists a bounded, cursor-paginated page of My Mixes with cached YouTube metadata and analytics. No provider calls. |
| `get_my_mix` | `library:read` | Returns one exact My Mix and a bounded ordered page of its cached tracks, including BPM, key, tags, and known mix position. |
| `add_tracks_to_playlist` | `playlists:write` | Adds exact TIDAL track IDs to an indexed TIDAL-backed Playlist, Event, or Source. TIDAL is updated first; TuneOps is updated only after provider success. |
| `remove_tracks_from_collection` | `playlists:write` | Removes exact TIDAL track IDs from an indexed TIDAL-backed Playlist, Event, or Source. This is destructive and requires approval. |
| `move_tracks_between_playlists` | `playlists:write` | Adds tracks to a destination, removes them from the source, and rolls the destination addition back if source removal fails. This is destructive and requires approval. |

## Write behavior

All three playlist actions change the user's TIDAL account and require ChatGPT
approval. Add is additive. Remove and move are marked destructive; move uses
the existing compensating rollback when source removal fails after a successful
destination add. Search results provide the exact IDs needed by these tools.

## Authentication

ChatGPT authenticates against TuneOps' OAuth broker. Google is used upstream
for identity verification; TuneOps issues its own short-lived access tokens and
rotating refresh tokens. Supported scopes are:

```text
openid
email
profile
profile:read
library:read
playlists:write
```

The MCP resource URL is the trailing-slash URL:

```text
https://tuneops.vercel.app/mcp/
```

OAuth and OIDC discovery are available at:

```text
https://tuneops.vercel.app/.well-known/oauth-protected-resource/mcp/
https://tuneops.vercel.app/.well-known/oauth-authorization-server/mcp
https://tuneops.vercel.app/mcp/.well-known/openid-configuration
```

## Limits

- Collection and search results are bounded and cursor-paginated.
- Liked Tracks returns at most 50 rows per call and never materializes the complete catalogue.
- Membership lookup accepts at most 50 track IDs.
- Tools identify tracks by exact TIDAL IDs rather than title/artist guessing.
- MCP access is currently restricted to the linked TuneOps library owner.
