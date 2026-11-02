# TuneOps MCP server and ChatGPT plugin plan

Last reviewed: 2026-10-26.

## Goal

Connect TuneOps to ChatGPT as a private plugin backed by a remote MCP server.
The user signs in to TuneOps during the ChatGPT connection flow, can safely
explore their indexed music library, and can approve narrowly scoped additive
actions such as adding selected TIDAL tracks to an owned playlist.

Version one is deliberately small:

- Read TuneOps profile, tracks, artists, collections, memberships and metadata.
- Search the complete indexed TuneOps library rather than one current playlist.
- Add explicitly identified tracks to one explicitly identified TIDAL playlist.
- Use ChatGPT's native write-tool confirmation before the additive action.
- Do not expose delete, remove, move, sync, provider-connect or credential tools.
- Do not build a custom MCP App UI until the tool-only workflow is proven.

This plan follows the current OpenAI plugin/MCP documentation:

- <https://developers.openai.com/plugins/build/mcp-server>
- <https://developers.openai.com/plugins/build/auth>
- <https://developers.openai.com/plugins/plan/tools>
- <https://developers.openai.com/api/docs/guides/custom-mcp-server>

## Decisions

### One TuneOps identity, separate authorization roles

Keep these three concepts separate:

1. **TuneOps application identity** identifies the human as an internal
   `app_users.id`.
2. **MCP OAuth authentication** uses a dedicated Google OAuth client to prove
   the same Google identity to ChatGPT; TuneOps assigns capabilities internally.
3. **Provider connections** are the encrypted Spotify, TIDAL and YouTube
   credentials TuneOps already owns for that internal user.

ChatGPT must never receive provider tokens, `TUNEOPS_CREDENTIAL_KEY`, Turso
credentials or browser session cookies. The dedicated Google OAuth client secret
is entered only in ChatGPT's connection setup and is never served by TuneOps. A
validated MCP access token resolves an internal user; TuneOps then loads that
user's provider connection on the server.

### Use the existing Google identity directly for private dogfooding

Do not turn TuneOps into a general OAuth authorization server. For the private,
single-user connection, configure ChatGPT with a dedicated Google Web OAuth
client from the existing Google Cloud project. Request only `openid email
profile`. Google does not issue custom TuneOps scopes, so tool descriptors use
empty OAuth scope lists and TuneOps grants capabilities after resolving the
linked Google `sub` to an active `app_users.id`.

The dedicated client ID is mandatory. Do not reuse a broader Google/YouTube
client: a Google access token for this exact client is the MCP credential.
TuneOps verifies the opaque access token with Google's token-info endpoint,
checks client ID, expiry and `openid`, and resolves the already-linked Google
identity. This is a pragmatic private-deployment tradeoff: Google does not bind
the token to the TuneOps MCP `resource` value. Before multi-user/public release,
replace it with an established provider that issues resource-bound tokens and
supports first-class TuneOps scopes.

Use ChatGPT's predefined/provided-client registration mode. The exact callback
URL shown by ChatGPT must be allowlisted on the dedicated Google client. Keep
Auth0/Stytch as future options, not current dependencies.

### Native approval for additive writes

ChatGPT treats tools without `readOnlyHint: true` as write actions and asks for
confirmation by default. The initial write tool must use accurate annotations:

```json
{
  "readOnlyHint": false,
  "destructiveHint": false,
  "openWorldHint": false,
  "idempotentHint": true
}
```

Adding tracks is a write but is additive, so marking it destructive merely to
force a scarier dialog would be inaccurate. The confirmation payload must show
the exact destination playlist and track IDs/titles. Users who require approval
for every call must not choose ChatGPT's conversation-level "remember approval"
option.

Tool annotations affect host behavior but are not an authorization boundary.
TuneOps still validates the token, scope, ownership, IDs, limits and provider
result for every call.

## Target architecture

```text
ChatGPT
  |  Streamable HTTP MCP + OAuth bearer token
  v
https://tuneops.vercel.app/mcp
  |-- validate Google client audience, expiry and linked subject
  |-- resolve external identity -> app_users.id
  |-- MCP tool adapter (small schemas and bounded results)
  v
existing TuneOps services/repositories
  |-- Turso library and configuration
  |-- encrypted per-user provider credentials
  `-- provider-first TIDAL mutation, database-second cache update
```

The MCP layer is an adapter. It must call shared TuneOps application services;
it must not duplicate SQL, matching, playlist mutation or provider auth logic.

## Initial tool contract

All identifiers are opaque strings. Results use bounded arrays, a cursor where
needed, and absolute user-openable TuneOps links. Never return raw SQL rows,
provider credentials or unbounded track collections.

### `get_tuneops_profile`

- Purpose: identify the connected TuneOps account and provider health.
- Internal capability: `profile:read` (not requested as a Google OAuth scope).
- Input: none.
- Output: stable opaque user ID, display name, TuneOps URL and safe provider
  connection labels/statuses.
- Metadata: authenticated profile tool with `_meta["openai/profile"]: true`.
- Annotations: read-only, non-destructive, not open-world.

### `search_tracks`

- Purpose: search the complete indexed library by title, remix and artist with
  optional key, BPM, rating, tags and collection filters.
- Internal capability: `library:read` (not requested as a Google OAuth scope).
- Input: query plus allowlisted filters, `limit <= 50`, optional cursor.
- Output: canonical TIDAL track ID, title, artists, relevant metadata,
  memberships and absolute TuneOps track/artist links.
- Annotations: read-only, non-destructive, not open-world.
- Reuse the same database-first query semantics as Global Search.

### `get_track`

- Purpose: inspect one exact indexed track after search or user reference.
- Internal capability: `library:read`.
- Input: canonical TIDAL track ID.
- Output: metadata, dimensions/tags/rating, memberships, My Mix and watched-mix
  relationships, Last.fm play count and absolute TuneOps links.
- Annotations: read-only, non-destructive, not open-world.

### `list_collections`

- Purpose: find an exact destination or inspect available collections.
- Internal capability: `library:read`.
- Input: optional type (`playlist`, `event`, `source`, `setlist`,
  `watched_mix`) and text query; bounded page.
- Output: stable collection ID, name, type, track count, writability and URL.
- Annotations: read-only, non-destructive, not open-world.

### `get_collection_tracks`

- Purpose: inspect a selected collection using TuneOps sorting/filtering.
- Internal capability: `library:read`.
- Input: collection type and ID, allowlisted sort/filter, `limit <= 50`, cursor.
- Output: bounded track summaries and next cursor.
- Annotations: read-only, non-destructive, not open-world.

### `get_track_memberships`

- Purpose: answer which playlists/events/sources/mixes contain one or more
  tracks before proposing an action.
- Internal capability: `library:read`.
- Input: at most 50 canonical track IDs.
- Output: memberships grouped by track.
- Annotations: read-only, non-destructive, not open-world.

### `add_tracks_to_playlist`

- Purpose: add exact indexed TIDAL tracks to one exact writable TIDAL playlist.
- Internal capability: `playlists:write`; Google grants identity only.
- Input: destination playlist ID, 1-50 canonical TIDAL track IDs and an
  idempotency key generated for this intended operation.
- Output: destination name, requested/added/already-present/failed counts,
  per-track safe status and playlist URL.
- Annotations: write, additive/non-destructive, not open-world, idempotent.
- Reuse `backend.app.services.actions.mutate_playlist_tracks("add", ...)`.
- Preserve provider-first/database-second behavior. Partial success must be
  explicit; never report an unverified success.

Deferred tools: like tracks, edit ratings/tags, create playlists, remove/move
tracks, run sync, manage mappings, delete data, connect providers, import
history and trigger broad background jobs. Add each only after a separate
permission and safety review.

## OAuth and identity flow

### Connection sequence

1. ChatGPT discovers `/.well-known/oauth-protected-resource` from the MCP host.
2. Resource metadata points to Google's OIDC issuer and advertises only
   `openid email profile`.
3. ChatGPT uses the dedicated, manually supplied Google client ID/secret and
   the exact callback URL allowlisted in Google Cloud.
4. ChatGPT opens Authorization Code + PKCE. The user signs in with Google and
   consents to `openid email profile`.
5. Google issues a short-lived opaque access token for the dedicated client.
6. ChatGPT sends `Authorization: Bearer ...` to `/mcp`.
7. TuneOps validates the token through Google's token-info endpoint, requiring
   the exact MCP Google client ID, a live expiry and the `openid` scope.
8. The validated `(issuer, subject)` resolves through `external_identities` to
   exactly one active `app_users.id`.
9. Tool services receive only the resolved internal ID; TuneOps applies its
   internal capabilities and ownership checks server-side.

Missing, invalid or insufficient tokens return `401` with the correct
`WWW-Authenticate` challenge and MCP `_meta["mcp/www_authenticate"]`, allowing
ChatGPT to display the linking/reauthorization UI.

### Private Google connection configuration

Vercel/TuneOps environment:

- `TUNEOPS_MCP_AUTH_PROVIDER=google`
- `GOOGLE_MCP_CLIENT_ID=<dedicated ChatGPT OAuth client ID>`
- `TUNEOPS_PUBLIC_URL=https://tuneops.vercel.app`

The MCP Google client secret is not required by TuneOps or Vercel. Enter it
only in ChatGPT's private connection setup. Configure ChatGPT with provided
client credentials, `client_secret_post`, authorization endpoint
`https://accounts.google.com/o/oauth2/v2/auth`, token endpoint
`https://oauth2.googleapis.com/token`, authorization-server base
`https://accounts.google.com`, resource `https://tuneops.vercel.app/mcp/`, and
base scopes `openid`, `email`, `profile`. Leave default/tool scopes empty.
Enable OIDC discovery at
`https://accounts.google.com/.well-known/openid-configuration` and UserInfo at
`https://openidconnect.googleapis.com/v1/userinfo`. Add the exact callback URL
shown by ChatGPT to the dedicated Google Web client's redirect allowlist.

### Identity-linking cutover

The current web session contains a signed Google `sub` but does not yet resolve
an internal database user. Complete this before MCP writes:

- Persist the current Google `(issuer, subject)` in `external_identities`.
- Resolve the browser session to the same stable `app_users.id` currently used
  by `TUNEOPS_LOCAL_USER_ID` and encrypted provider connections.
- Reuse the already-linked Google `(issuer, subject)`; do not create a second
  identity merely because ChatGPT uses a separate OAuth client ID.
- Reject unknown identities even when their email happens to match an allowlist.
- Add a visible Settings page listing linked application identities and a way
  to revoke the ChatGPT/MCP link without deleting provider credentials.

## Authorization policy

Initial internal capabilities (not Google OAuth scopes):

| Scope | Permits |
| --- | --- |
| `profile:read` | Safe TuneOps account/profile identification |
| `library:read` | Tracks, artists, collections, tags, ratings and relationships |
| `playlists:write` | Add tracks to an owned writable TIDAL playlist |

Rules:

- Declare OAuth security per MCP tool with an empty scope list in Google mode;
  the connection's base scopes are always `openid email profile`.
- Resolve `user_id` only from a validated token. It is never a tool argument.
- Verify every requested track and playlist belongs to or is visible to the
  resolved user before provider access.
- `playlists:write` does not imply remove, move, delete, create or sync rights.
- A read-only connection must still be useful. Enabling a future write tool is
  an explicit TuneOps server-side policy change and does not widen Google data
  access.
- If a future provider supports resource-bound custom scopes, restore
  per-tool incremental authorization before public/multi-user release.

## Write safety and idempotency

- Let ChatGPT present its native confirmation for `add_tracks_to_playlist`.
- Keep one coherent mutation per tool call; never hide several playlist writes
  or a sync behind one generic executor.
- Limit one call to 50 tracks and one destination playlist.
- Require IDs returned by TuneOps read tools or exact canonical provider IDs;
  never fuzzy-match the destination during a write.
- Reject events, sources, setlists and watched mixes as destinations unless a
  future tool explicitly supports their provider semantics.
- Store an idempotency record keyed by internal user, tool name and opaque key,
  including a hash of normalized arguments and the final safe result.
- Repeating the same key and arguments returns the stored result; reusing a key
  with different arguments is rejected.
- Use the existing membership preflight so already-present tracks are skipped.
- Audit actor, tool, destination, track count, outcome, timestamp and request
  correlation ID. Never audit tokens or raw conversation text.
- Rate-limit write calls per user and playlist.

New independent tables such as `mcp_idempotency_keys` and `mcp_audit_events`
may be introduced with `CREATE TABLE IF NOT EXISTS`. Any migration that alters
existing live identity/library tables still follows the stop-and-backup rule.

## Server layout

Suggested modules:

```text
backend/app/mcp/
  server.py          # MCP initialization and Streamable HTTP transport
  auth.py            # bearer challenge and validated principal dependency
  tools_profile.py   # authenticated profile tool
  tools_library.py   # read-only library tools
  tools_playlists.py # additive playlist write tool
  schemas.py         # explicit MCP input/output models
  links.py           # absolute TuneOps URLs
  audit.py           # bounded audit/idempotency repository
```

Mount the state-light Streamable HTTP endpoint at `/mcp`. OAuth discovery and
MCP transport routes must be exempt from the existing browser-cookie redirect
middleware, but not from their own bearer validation. Do not redirect MCP
clients to HTML login pages.

Vercel instances are ephemeral. Keep no authorization state, idempotency state,
jobs or protocol-critical session state only in process memory. Persist required
state in Turso. Google owns its normal OAuth grant and refresh-token lifecycle.

## Delivery phases

### Phase 0 — contracts and provider spike

- [ ] Confirm private custom MCP plugins are available in the target ChatGPT
  account/workspace.
- [x] Choose direct Google OIDC with a dedicated predefined OAuth client for
  private dogfooding; record the missing resource-bound-token tradeoff.
- [x] Use `https://tuneops.vercel.app/mcp/` as the production MCP resource.
- [ ] Record privacy, retention and support URLs even for private dogfooding.
- [ ] Freeze the version-one tool inventory and schemas above.

Exit: ChatGPT can complete Google OAuth against a protected tool, and TuneOps
verifies that the access token belongs to the dedicated Google client and the
linked internal user.

### Phase 1 — persistent application identity

- [x] Map the existing Google web identity to the current internal user.
- [x] Make browser/API identity resolution return `app_users.id`.
- [x] Reuse the existing stable Google identity link for MCP authentication.
- [ ] Add cross-user isolation tests before accepting a second identity.
- [ ] Add Settings visibility and revocation for linked MCP identity.

Exit: web, local jobs, provider credentials and an MCP token all resolve the
same internal user without using email as the authorization key.

### Phase 2 — MCP/auth skeleton

- [x] Add the official Python MCP SDK.
- [x] Mount stateless Streamable HTTP at `/mcp/`, feature-gated by complete
  OAuth resource-server configuration.
- [x] Publish protected-resource metadata.
- [x] Support generic JWT validation and direct Google opaque-token validation;
  require exact client audience, expiry, `openid`, and linked identity for the
  private Google connection.
- [x] Register `get_tuneops_profile` with per-tool security schemes.
- [ ] Add health/initialization telemetry without exposing tool inputs.
- [ ] Verify stateless behavior across separate Vercel function instances.

Exit: MCP Inspector and ChatGPT can connect, sign in, call the profile tool and
distinguish authentication failure from application failure.

### Phase 3 — read-only library tools

- [x] Implement the five read tools over existing database services.
- [x] Add cursor pagination and strict maximum result sizes.
- [x] Return concise structured output plus user-openable TuneOps paths.
- [ ] Add query budgets/timeouts suitable for remote Turso.
- [ ] Test empty results, Unicode, duplicate names, stale provider caches and
  invalid IDs.

Exit: representative natural-language questions can be answered without any
provider mutation or secret-bearing result.

### Phase 4 — additive playlist action

- [ ] Add persistent idempotency and MCP audit repositories.
- [ ] Adapt the existing provider-first playlist action to require explicit
  internal user ownership instead of implicit process-global identity.
- [ ] Register `add_tracks_to_playlist` with `playlists:write` and accurate
  annotations.
- [ ] Verify ChatGPT displays confirmation with the complete tool arguments.
- [ ] Test success, already-present, partial provider failure, retry, token
  expiry during execution and cache-update failure.

Exit: an approved call adds only the displayed tracks to only the displayed
playlist, and retries cannot duplicate the action.

### Phase 5 — ChatGPT plugin dogfood

- [ ] Add the custom MCP server as a private ChatGPT plugin.
- [ ] Review every discovered tool, schema, annotation and requested scope.
- [ ] Run an evaluation set covering direct/indirect reads, ambiguous tracks,
  ambiguous playlists, write confirmations, denied confirmations, remembered
  approvals, prompt injection and unsupported destructive requests.
- [ ] Keep the plugin private to the allowed TuneOps account initially.
- [ ] Monitor tool selection, latency, auth failures, provider failures and
  confirmation behavior using safe correlation IDs.

Exit: at least one week of private use without unauthorized, surprising or
duplicate writes.

### Phase 6 — optional UI and publication

- [ ] Add an MCP App component only if selecting many search results or
  reviewing playlist changes is materially better visually.
- [ ] If strict per-call approval is required even after a user chooses
  ChatGPT's remembered approval, design an explicit TuneOps-hosted approval
  screen or MCP App confirmation control before expanding write tools.
- [ ] Complete domain verification, current MCP scan, privacy policy, support
  contact and reviewer credentials before directory submission.
- [ ] Add broader tools one at a time with separate scopes and threat review.

## Test matrix

### Protocol and schemas

- Initialize, list tools, call tool, malformed JSON-RPC and unsupported method.
- Every tool has explicit input/output schemas and all required annotations.
- Pagination is stable and cannot exceed server limits.

### Authentication and authorization

- Missing token, invalid Google token, wrong OAuth client audience, expired
  token, missing `openid`, and revoked/unlinked identity.
- Correct `WWW-Authenticate` and MCP auth metadata on failures.
- Google OAuth requests only `openid email profile`; internal TuneOps
  capabilities and ownership checks remain server-enforced.
- Unknown identity and disabled TuneOps user.
- Cross-user track, collection, credential and idempotency access attempts.

### Read tools

- Exact and fuzzy search, Unicode artist/title, empty query, no matches.
- Playlist/event/source/setlist/watched-mix distinction.
- Tags, ratings, Last.fm counts and memberships remain user-scoped.
- Results contain no credentials, internal SQL, filesystem paths or raw errors.

### Additive write

- ChatGPT confirmation appears before the provider mutation.
- Denial produces no provider call and no database change.
- Exact playlist ownership/writability validation.
- Already-present tracks are safely skipped.
- Same idempotency key/same body returns the prior result.
- Same key/different body is rejected.
- Provider success plus cache failure reports partial state and remediation.
- Provider partial failure reports each outcome without retrying successes.
- Prompt-injected track metadata cannot alter tool selection or arguments.

## Acceptance criteria

- The ChatGPT connection visibly authenticates to TuneOps and resolves the same
  internal account used by the web application.
- Read-only tools are useful without granting `playlists:write`.
- Every tool call is scoped by validated identity and internal TuneOps policy.
- ChatGPT shows a confirmation before `add_tracks_to_playlist`.
- The confirmed payload names one destination and the exact tracks.
- Duplicate/retried calls cannot add duplicate tracks.
- Provider credentials and database secrets never leave TuneOps.
- No remove, move, delete or broad sync action exists in version one.
- MCP Inspector, automated auth/isolation tests and the ChatGPT evaluation set
  pass before production credentials are used.

## Explicit non-goals for version one

- Building a custom OAuth authorization server.
- Giving ChatGPT TIDAL, Spotify, YouTube Analytics or Turso credentials. The
  dedicated Google identity-only OAuth client is intentionally used for MCP.
- Letting the model choose an unbounded action from a generic executor.
- Mutating playlists without native ChatGPT confirmation.
- Supporting anonymous access.
- Publishing publicly before private dogfooding is stable.
- Replacing the TuneOps web UI or background synchronization system.
