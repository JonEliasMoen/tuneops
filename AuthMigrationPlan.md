# MusicSync authentication storage migration plan

Last reviewed: 2026-10-18.

## Goal

Move user-specific provider sessions from ignored files into an encrypted,
user-scoped database store without changing provider behavior. The first
version remains a single-user local application. The same repository and data
model must later work behind a separate MusicSync application sign-in without
another credential migration.

This plan does not move application registration secrets into the database.
Client secrets and server API keys remain deployment secrets.

## Current state inventory

| Current location | Contents | Classification | Destination |
| --- | --- | --- | --- |
| `.spotify_cache` | Spotify access/refresh token, expiry and scopes | User credential | Encrypted `provider_connections` record |
| `.tidal_session.json` | TIDAL token type, access/refresh token and expiry | User credential | Encrypted `provider_connections` record |
| `.youtube_oauth.json` | Google/YouTube access/refresh token, expiry and scopes | User credential | Encrypted `provider_connections` record |
| `.connection_state.json` | Display labels for connected accounts | Non-secret derived metadata | Columns on `provider_connections` |
| `.env` | Client IDs/secrets, Last.fm key, redirects and runtime configuration | Deployment secret | Keep outside the database; later use managed secret storage |

The future Google **MusicSync sign-in** registration is distinct from the
Google/YouTube provider connection. Signing into MusicSync establishes who the
user is; connecting YouTube grants that user access to YouTube data. Keep their
registrations, callbacks, scopes, cookies and token records separate even if
both use Google.

## Target data model

### `app_users`

- Immutable UUID primary key.
- Optional display name, status, creation and update timestamps.
- Initially one stable local user.
- Never use email, provider username or provider account ID as the primary key.

When app sign-in is added, an `external_identities` table maps a Google
`(issuer, subject)` pair to the internal user. Email remains display metadata,
not an authorization boundary.

### `provider_connections`

One row represents one user's Spotify, TIDAL or YouTube connection:

- `id`, `user_id`, `provider`.
- Provider account/channel ID and a safe display label.
- Status: `connected`, `refresh_required`, `revoked`, `error`, or
  `disconnected`.
- Granted scopes, expiry, last refresh and last verification timestamps.
- Authenticated encrypted credential payload, encryption key/version reference
  and provider payload schema version.
- Creation and update timestamps.
- Initially unique on `(user_id, provider)`; this can later support multiple
  provider accounts by including the provider account ID.

Access and refresh tokens should not be separate queryable plaintext columns.
Store one encrypted, versioned JSON payload while keeping only safe operational
metadata outside it.

### `oauth_authorization_states`

For multi-instance hosting, store hashed single-use OAuth state, owning user,
provider, expiry and safe return path. Encrypt PKCE verifiers and other
sensitive flow material. Never store raw state values.

### `credential_audit_events`

Record connect, refresh, refresh failure, disconnect and revoke events without
tokens, authorization codes, headers or full provider request URLs.

## Encryption boundary

Putting tokens in SQLite is not sufficient. A copied database or backup must
not contain usable credentials.

Create a backend-only abstraction:

```text
CredentialCipher.encrypt(user_id, provider, plaintext) -> ciphertext + key_id
CredentialCipher.decrypt(user_id, provider, ciphertext, key_id) -> plaintext
```

- Use authenticated encryption and bind user ID, provider and connection ID as
  associated data, preventing ciphertext from being moved to another owner.
- Never keep the encryption key in the same database.
- Local Windows mode should use an OS-protected key source such as DPAPI or
  Windows Credential Manager. An environment development key is only an
  explicit fallback.
- Hosted mode uses envelope encryption through Azure Key Vault or the selected
  cloud KMS. PostgreSQL stores only ciphertext, wrapped data-key material and
  key version.
- Support key rotation by decrypting with the stored version and rewriting
  with the current version after a successful read or refresh.
- Never log decrypted payloads; retain them in memory only while constructing
  or refreshing a provider client.

## Repository and ownership boundary

Add a provider-neutral repository rather than letting provider SDKs read the
database directly:

```text
get_connection(user_id, provider)
save_credentials(user_id, provider, credential_payload, metadata)
update_metadata(user_id, provider, metadata)
disconnect(user_id, provider)
mark_refresh_required(user_id, provider, sanitized_error)
```

Every operation requires `user_id`. During the local transition,
`current_local_user_id()` returns the single stable local UUID. Later, the same
dependency resolves the authenticated browser session or background-job owner.

## Provider adapters

### Spotify

- Implement a Spotipy cache-handler backed by the repository instead of
  `cache_path=.spotify_cache`.
- Preserve the complete token object Spotipy expects, including expiry and
  scopes, and save refreshes immediately.
- Make `spotify_client(user_id)` and `spotify_auth_manager(user_id)` explicit.
- Bind callback state to the MusicSync user who initiated authorization.

### TIDAL

- Replace `.tidal_session.json` reads/writes with a payload containing token
  type, access token, refresh token and expiry.
- Continue loading through `session.load_oauth_session(...)`.
- Save after login and after a refreshed session is obtained.
- Store the TIDAL user ID/label as safe connection metadata.
- A device-login attempt belongs to one MusicSync user; concurrent users must
  never share its completion result.

### YouTube

- Replace `_read_token()` and `_write_token()` with repository operations.
- Preserve the existing refresh token when Google omits a new one on refresh.
- Bind OAuth state and callback to the signed-in MusicSync user.
- Keep YouTube consent separate from primary Google app sign-in consent.
- Disconnect should try remote revocation and then remove local ciphertext even
  when remote revocation fails visibly.

### Connection state

- Replace `.connection_state.json` and credential-file existence checks with
  safe `provider_connections` status, label and expiry metadata.
- Health endpoints must not decrypt credentials just to render badges.
- Explicit verification may call a provider and cache the safe result and time.

## Delivery phases

### Phase 1 — interfaces and local ownership

- [ ] Add `app_users`, `provider_connections` and audit tables through a
  reviewed migration.
- [ ] Create one stable local user and a backend dependency resolving it.
- [ ] Implement the repository plus an in-memory fake for tests.
- [ ] Implement the cipher using a local protected-key backend and a
  deterministic test-only cipher.
- [ ] Add token/authorization-header redaction helpers.
- [ ] Do not remove or modify existing credential files yet.

### Phase 2 — provider adapters and dual-read

- [ ] Make Spotify, TIDAL and YouTube factories accept `user_id`.
- [ ] Read encrypted DB credentials first.
- [ ] If absent, read the old file once, validate it, encrypt it into the DB
  transactionally, then compare safe metadata such as provider, expiry and
  account identity after reading it back.
- [ ] Keep original files untouched as rollback copies during this phase.
- [ ] Write newly issued/refreshed tokens only to the database once that
  connection has migrated successfully.
- [ ] Expose migration status as `file only`, `database`, `needs reconnect`, or
  `error`, without exposing token values.

### Phase 3 — controlled local cutover

- [ ] Announce the live-data migration and require the app/startup sync to be
  stopped under the existing database safety rule.
- [ ] Back up SQLite and all auth/state files outside the repository.
- [ ] Run a read-only preflight reporting which providers can be imported and
  which require reconnecting.
- [ ] Run an idempotent import for the stable local user.
- [ ] Verify health, Spotify reads, TIDAL reads/writes, YouTube analytics and
  `startup_sync.py` with DB credentials.
- [ ] Rename source files to timestamped `.migrated-backup` files rather than
  deleting them.
- [ ] After a rollback window, remove fallback code and manually securely
  delete credential backups.
- [ ] Remove `.connection_state.json` after every consumer uses DB metadata.

### Phase 4 — MusicSync application sign-in

- [ ] Create a separate Google OIDC registration using Authorization Code +
  PKCE for MusicSync sign-in.
- [ ] Add `external_identities` keyed by Google issuer and subject.
- [ ] Replace `current_local_user_id()` with a required authenticated-session
  dependency for browser requests.
- [ ] Use `HttpOnly`, `Secure`, `SameSite` cookies, CSRF protection, session
  rotation and explicit sign-out.
- [ ] Attach the resolved user ID to jobs when enqueued; workers load only that
  owner's credentials.
- [ ] Scope all library/config rows and queries by `user_id` before enabling a
  second account. Credential migration alone is not multi-user support.
- [ ] Each MusicSync user connects providers separately. Never copy the local
  user's tokens into another signed-in account.

### Phase 5 — hosted secrets and encryption

- [ ] Move `.env` app secrets to the platform secret manager—not to the user
  credential table.
- [ ] Replace the local cipher with managed envelope encryption while retaining
  the same repository contract and versioned payloads.
- [ ] Grant decrypt access only to API/worker workload identities.
- [ ] Add key rotation, credential refresh/age monitoring and audit alerts.
- [ ] Confirm exports, logs, jobs, frontend payloads and MCP results cannot
  contain plaintext credentials.

## Migration command

The future command should provide explicit modes:

```text
python migrate_auth.py inspect
python migrate_auth.py migrate --user <local-user-id>
python migrate_auth.py verify --user <local-user-id>
```

- `inspect` is read-only and reports provider, token presence, expiry and
  readiness—never token values.
- `migrate` refuses to overwrite a newer valid DB credential without an
  explicit recovery option.
- Provider imports are transactional and independently retryable.
- `verify` decrypts and structurally validates locally. Live provider calls are
  separate and opt-in to avoid accidental rate-limit use.
- The command never deletes or edits source credential files.

## Required tests

- Encrypt/decrypt round trip and associated-data mismatch rejection.
- Wrong/rotated key, corrupt ciphertext and missing-key behavior.
- File-to-DB import for every provider using fake tokens and temporary paths.
- Idempotent reruns and refusal to overwrite newer DB credentials.
- Spotify refresh persistence through the custom cache handler.
- TIDAL refreshed-session persistence.
- YouTube refresh preserving the original refresh token.
- Concurrent refresh protection so an older worker cannot overwrite a newer
  token.
- Disconnect, revoke and reconnect behavior.
- No secret values in logs, HTTP responses, audit rows or public errors.
- Cross-user isolation before application sign-in can be enabled.
- `startup_sync.py` resolving the intended local/job owner without browser
  state.

## Acceptance criteria before removing file storage

- Spotify, TIDAL and YouTube work after the original files are renamed.
- Token refreshes survive application restarts.
- Startup sync works without a browser when valid refresh/session credentials
  exist.
- Settings/health render connection state without checking credential files.
- Provider tokens are never plaintext in SQLite.
- Restoring SQLite without the external encryption key exposes no tokens.
- Failed migration leaves the database and original files usable.
- Provider factories/repositories already require `user_id`, so future sign-in
  changes identity resolution rather than credential format.

## Explicit non-goals

- Do not store Spotify/Google client secrets or Last.fm app keys in
  `provider_connections`.
- Do not use a hard-coded encryption key.
- Do not use Google email as the database owner key.
- Do not combine MusicSync sign-in and YouTube Analytics consent.
- Do not automatically delete source files during initial migration.
- Do not claim multi-user readiness until all user-owned library/config data is
  scoped and authorization-tested by `user_id`.
