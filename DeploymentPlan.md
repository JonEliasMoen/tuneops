# MusicSync cloud deployment plan

Last reviewed: 2026-10-12.

This roadmap is intentionally separate from `Tasks.md`. The local application
should remain usable throughout the migration, and cloud work must not silently
change or migrate the existing local SQLite database.

## Proposed production shape

- React frontend served from a managed web host/CDN.
- FastAPI API and MCP server deployed as one service initially, with clear
  internal module boundaries so they can be separated later.
- Managed PostgreSQL for user, library, sync, job, and audit data.
- Managed object storage for permitted artwork and exported/imported files.
- Google as the first application sign-in provider.
- A managed secret store and key-management service for provider credentials.
- A durable job queue plus scheduled dispatcher for provider refresh/sync work.
- Public HTTPS MCP endpoint using OAuth 2.1 and per-tool authorization.

Keep the first deployment single-region and operationally boring. Split it into
more services only when actual load or reliability data justifies doing so.

## Phase 0 — decisions and boundaries

- [ ] Choose the first cloud platform and region. Evaluate Azure App Service or
  Container Apps for FastAPI, Static Web Apps/CDN for React, PostgreSQL, Blob
  Storage, Key Vault, and Application Insights.
- [ ] Choose the identity/OAuth platform. Prefer an established provider that
  supports Google sign-in for the web app and OAuth 2.1/OIDC requirements for
  the MCP connection; do not build an authorization server from scratch.
- [ ] Define environments: local, development cloud, and production. Give each
  separate databases, callback URLs, OAuth registrations, encryption keys, and
  provider credentials.
- [ ] Define the tenancy boundary: every user-owned row must carry an immutable
  internal `user_id`; provider IDs and email addresses are attributes, not
  authorization boundaries.
- [ ] Inventory all current local state and classify it as configuration,
  secret, relational data, cached/rebuildable data, or local-only media.
- [ ] Decide what the hosted product will deliberately not support in version
  one, especially local filesystem browsing and direct desktop-app control.
- [ ] Write a threat model covering account takeover, token disclosure,
  cross-user data access, malicious MCP calls, provider rate limits, and job
  replay/duplication.

## Phase 1 — application identity

- [ ] Add Google as the primary application sign-in using standard OIDC
  Authorization Code flow with PKCE and server-side callback validation.
- [ ] Add a cloud `users` model keyed by an internal UUID and store the Google
  issuer plus subject as the external identity. Do not use email as a primary
  key.
- [ ] Create secure server sessions using `HttpOnly`, `Secure`, `SameSite`
  cookies, CSRF protection for mutations, rotation on sign-in, and explicit
  sign-out/revocation.
- [ ] Add authorization dependencies to FastAPI and require a resolved user for
  every private API route, background job, download, image, and MCP operation.
- [ ] Add account/profile UI showing connected providers, scopes, credential
  health, last successful sync, and disconnect/delete controls.
- [ ] Add tests proving one user cannot enumerate, read, mutate, enqueue, or
  download another user's resources by changing route IDs.
- [ ] Define account deletion and data-export behavior before inviting another
  user.

## Phase 2 — per-user provider credentials

- [ ] Replace process-wide Spotify, TIDAL, YouTube, Last.fm, and future provider
  sessions with connections owned by `user_id` and provider name.
- [ ] Store only encrypted provider tokens/credentials. Use envelope encryption:
  a managed KMS/Key Vault key protects per-record data keys, while ciphertext
  and key version live in the database.
- [ ] Keep encryption keys and application secrets outside source control and
  outside the database. Grant decrypt permission only to the API/job workload
  identity.
- [ ] Never derive credential encryption directly from the Google user ID or
  email. Associate encrypted records with the authenticated internal user, and
  let managed key material perform the encryption.
- [ ] Add token refresh, expiry, rotation, re-consent, disconnect, and revoked-
  credential flows per provider.
- [ ] Encrypt particularly sensitive non-OAuth sessions such as TIDAL session
  material and document their limitations before supporting multiple users.
- [ ] Redact tokens, authorization headers, callback codes, and provider request
  URLs from application logs and job errors.
- [ ] Add audit events for connect, refresh, disconnect, sync mutation, MCP
  mutation, credential failure, and administrative access without recording
  secret values.

## Phase 3 — cloud data model

- [ ] Design the PostgreSQL schema with `user_id` ownership on playlists,
  mappings, liked snapshots, metadata, tags, setlists, watched mixes, pending
  tracks, listening history, jobs, and settings.
- [ ] Decide which canonical provider metadata may be shared and which data must
  remain user-scoped. Default to user-scoped until deduplication is proven safe.
- [ ] Replace SQLite-specific queries and connection assumptions with a tested
  repository layer supporting PostgreSQL transactions, paging, constraints,
  and migrations.
- [ ] Introduce a real migration tool and require reviewed forward migrations,
  backups, and rollback/roll-forward procedures for production schema changes.
- [ ] Preserve uniqueness guarantees for liked and playlist membership while
  including the owning user in every relevant unique key.
- [ ] Add database connection pooling, statement timeouts, retry rules for
  transient failures, and explicit transaction boundaries for provider-first
  mutations.
- [ ] Add retention and cleanup policies for jobs, OAuth state, temporary
  tracklist staging, cached artwork, and rebuildable provider metadata.
- [ ] Add backup, point-in-time recovery, restore testing, and alerts for backup
  failure.

### Local-to-cloud data migration — Jon-owned execution

- [ ] Build a read-only export/preflight command that reports row counts,
  duplicates, unresolved references, unsupported local paths, and the target
  cloud account without uploading anything.
- [ ] Build a versioned, resumable import format with stable source identifiers
  and idempotency keys so rerunning an interrupted import does not duplicate
  data.
- [ ] Provide a dry-run comparison of local versus cloud counts for every
  collection before committing an import.
- [ ] Require an explicit signed-in destination account and confirmation before
  importing. Never infer the destination user from an email string in the data.
- [ ] Keep provider credentials out of the library export; reconnect providers
  interactively in the hosted app.
- [ ] Document the final migration runbook. Jon performs the live export/import
  after stopping local writers and making an external SQLite backup.
- [ ] Verify post-import counts and sampled relationships, then keep the local
  backup untouched through an agreed rollback window.

## Phase 4 — reliable scheduled sync

- [ ] Move long-running imports, matching, and synchronization out of web
  request workers into durable background jobs.
- [ ] Persist job state, attempts, progress, idempotency key, owner, requested
  scope, provider checkpoints, and sanitized errors.
- [ ] Add a scheduler that enqueues due mappings rather than performing sync
  work itself. Azure Functions timer triggers are viable for dispatch; the jobs
  should still execute through the same queue/worker path as manual syncs.
- [ ] Add per-user schedules, time zones, enable/disable controls, minimum
  intervals, and a visible next-run time.
- [ ] Add distributed locking so the same user/mapping cannot run concurrently
  from a timer, manual request, and MCP request.
- [ ] Make jobs retry-safe and idempotent. Respect provider rate limits,
  `Retry-After`, exponential backoff, daily quotas, and circuit breaking.
- [ ] Preserve current source-version/diff/unmatched behavior and avoid full
  catalogue searches when neither source nor destination has changed.
- [ ] Add failure notifications and a dashboard for queued, running, delayed,
  successful, partial, and failed jobs.
- [ ] Ensure deployment shutdown drains or safely requeues active work.

## Phase 5 — My Mixes and local folders

- [ ] Separate a My Mix's cloud metadata from its local media location. Cloud
  identity must not depend on an absolute Windows folder path.
- [ ] Define a portable mix manifest containing a stable mix UUID, title,
  positions, provider links, artwork reference, and optional local audio
  fingerprint—never the audio file by default.
- [ ] Build browser upload/import for a manifest, `positions.txt`, and cover
  image so cloud My Mixes work without filesystem access.
- [ ] Decide whether audio files are permanently out of scope, uploaded to
  private object storage, or accessed only through an optional local companion.
  Treat licensing, cost, download authorization, and retention as blockers to
  silent audio upload.
- [ ] Prototype an optional local companion agent for folder discovery and
  manifest/artwork sync. It must use outbound authenticated HTTPS, expose no
  inbound home-network port, and require explicit folder allowlists.
- [ ] Reconcile edits using stable IDs and versions; surface conflicts instead
  of overwriting newer cloud or local changes.
- [ ] Keep YouTube/TIDAL metadata refresh server-side and preserve local-cover
  precedence after upload.

## Phase 5B — Android watched-mix companion

Build this as a deliberately small companion for discovering tracks while a
YouTube mix is playing, not as a second implementation of the complete web app.
All parsing, TIDAL search, liking, pending-track, and watched-mix association
rules remain in the hosted FastAPI service.

- [ ] Prototype the Android playback-position capability before choosing the
  full UI framework. With explicit notification-listener access, inspect active
  media sessions through Android's `MediaSessionManager`, filter for YouTube,
  and verify that real devices expose a sufficiently accurate playback state,
  position, speed, title, and session lifecycle.
- [ ] Choose React Native with a small Kotlin Turbo Native Module if the media-
  session prototype is reliable. A web-only/PWA implementation cannot inspect
  another Android app's active media session, and this feature therefore cannot
  run inside Expo Go without a custom native build. Prefer native Kotlin/Compose
  instead if most of the application becomes platform integration code.
- [ ] Register an Android Share target so **Share -> MusicSync** from YouTube
  opens or creates the corresponding watched mix from its URL. Confirm the mix
  and video identity before associating imported tracks.
- [ ] Add normal MusicSync sign-in and store only revocable application tokens
  in Android's encrypted credential storage. The mobile client never receives
  raw TIDAL, Spotify, Google, or MCP provider credentials.
- [ ] Implement the focused watched-mix screen: cached cover, title/channel,
  rating, current YouTube time, pasted tracklist, parsed rows, current-row
  highlight, candidate selection, Like, Watch, and association status.
- [ ] Use the YouTube media session as the stopwatch source while available.
  Calculate the live position from the reported position, playback speed, and
  last update time; follow play, pause, seek, video change, and session loss.
- [ ] Treat media-session access as optional and explain the sensitive Android
  notification-listener permission before opening system settings. Read only
  media-session state needed for this feature; never upload notification
  contents or enumerate them into logs.
- [ ] Provide a dependable fallback when YouTube does not publish a usable
  session: manual Start/Pause/Stop, editable start time, **Sync to YouTube now**,
  and a visible disconnected/stale indicator. Tracklist importing must continue
  to work without playback access.
- [ ] Reuse the web API's tracklist parser and TIDAL-search jobs rather than
  duplicating parsing or provider logic on Android. Persist temporary mobile
  drafts with the same expiry semantics as the web staging view.
- [ ] Avoid continuous backend polling for the stopwatch. Playback position and
  row highlighting are device-local; contact the backend only for watched-mix
  data, parsing, candidate search, Like/Watch mutations, and explicit refresh.
- [ ] Test notification permission denied/revoked, YouTube foreground and
  background playback, pause/seek, ads, casting, Bluetooth controls, screen
  rotation, process recreation, network loss, and multiple active media
  sessions on at least two Android versions.
- [ ] Distribute privately first through a signed APK or internal testing track.
  Review Google Play's notification-access disclosure and data-safety rules
  before considering public distribution.

## Phase 6 — production API and deployment hardening

- [ ] Containerize the FastAPI service and worker with pinned reproducible
  dependencies, non-root execution, health checks, and graceful shutdown.
- [ ] Add structured logs, request/job correlation IDs, metrics, traces, and
  alerts without exposing private track data or credentials unnecessarily.
- [ ] Add rate limits and quotas per user, endpoint, MCP tool, and provider.
- [ ] Configure HTTPS, trusted proxies, CORS, CSP, secure headers, upload size
  limits, dependency scanning, and secret scanning.
- [ ] Add CI gates for Python/React tests, migrations against an ephemeral
  PostgreSQL instance, production frontend build, container scan, and deploy
  smoke tests.
- [ ] Add staged deployment, database migration ordering, rollback procedures,
  and a maintenance/read-only mode.
- [ ] Define availability and recovery objectives before adding scheduled jobs
  users will depend on.
- [ ] Add usage/cost budgets and alerts for database, storage, egress, job
  execution, YouTube APIs, and any hosted AI inference.

## Phase 7 — hosted MCP server and ChatGPT plugin

- [ ] Define a small goal-oriented MCP tool inventory before implementation.
  Start read-only: search library, get track details, list collections, inspect
  memberships, find compatible tracks, and inspect sync/job status.
- [ ] Add mutating tools only after read-only tools are stable: update tags,
  add/remove playlist membership, manage set drafts, and request a sync.
- [ ] Give every tool strict schemas, bounded result sizes, pagination, useful
  errors, and accurate `readOnlyHint`/`destructiveHint` annotations.
- [ ] Host the MCP server at a stable public HTTPS streaming HTTP endpoint,
  normally `/mcp`, with health, latency, error, and initialization monitoring.
- [ ] Implement the MCP OAuth 2.1 authorization contract using the chosen
  identity provider: protected-resource metadata, authorization-server
  metadata, Authorization Code + PKCE (`S256`), audience/resource validation,
  scopes, refresh/revocation, and correct `WWW-Authenticate` challenges.
- [ ] Choose and test the ChatGPT client-registration mode—prefer CIMD when the
  identity provider supports it; use DCR or a predefined client only when
  required.
- [ ] Resolve the MusicSync `user_id` exclusively from the validated access
  token. Never accept a user ID, email, or credential reference supplied as a
  model-controlled tool argument.
- [ ] Define least-privilege scopes such as `library:read`, `metadata:write`,
  `playlists:write`, and `sync:run`; require explicit confirmation/approval for
  consequential provider mutations.
- [ ] Add an authenticated read-only profile tool so connected accounts can be
  distinguished consistently.
- [ ] Protect against prompt-injection-driven tool misuse with server-side
  authorization, validation, ownership checks, idempotency, and bounded
  mutations. The model is not an authorization layer.
- [ ] Test locally with MCP Inspector, then through a development deployment and
  a dedicated test account before connecting production data.
- [ ] Package the ChatGPT plugin metadata only after the MCP tools work without
  custom UI. Add an MCP App UI later only for workflows that genuinely benefit
  from an embedded visual surface.
- [ ] Complete domain verification, privacy policy, support information,
  reviewer access, tool safety review, and submission checks if publishing
  beyond private use.

## Phase 8 — cutover and operations

- [ ] Run a private single-user deployment first and compare cloud/local counts,
  sync outcomes, matching, tags, history, setlists, and watched mixes.
- [ ] Run scheduled sync in report-only/shadow mode before permitting provider
  writes.
- [ ] Exercise token expiry, provider outage, quota exhaustion, worker crash,
  duplicate job delivery, database restore, and MCP revocation scenarios.
- [ ] Add privacy, terms, support, incident response, data export, and account
  deletion documentation before inviting external users.
- [ ] Define a local fallback/rollback window. Do not remove the local app or
  SQLite support merely because the first cloud deployment succeeds.
- [ ] After stable private use, decide whether this remains a personal hosted
  service, becomes invite-only, or is prepared for public multi-user release.

## Non-negotiable safety rules

- Never place provider secrets or refresh tokens in React, MCP tool results,
  logs, job payloads, exports, or model-visible data.
- Every database query and object-storage key involving user data is scoped by
  the authenticated internal `user_id`.
- Provider mutations remain provider-first and database-second, with explicit
  partial-failure recovery.
- Scheduled and MCP-triggered writes use the same audited job path as manual
  writes; they do not bypass application authorization or locking.
- Existing local SQLite data is not modified or uploaded as a side effect of
  deploying infrastructure.
