"""Encrypted, user-scoped provider credentials stored in the library DB."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from spotipy.cache_handler import CacheHandler

from music_library.database import DATABASE_PATH, connect, connect_readonly, initialize


SUPPORTED_PROVIDERS = frozenset({"spotify", "tidal", "youtube"})
CREDENTIAL_SCHEMA_VERSION = 1
CONNECTION_METADATA_CACHE_SECONDS = 15.0


_CONNECTION_METADATA_CACHE: dict[
    tuple[str, str], tuple[float, dict[str, dict[str, Any]]]
] = {}


class CredentialConfigurationError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_enabled() -> bool:
    return os.getenv("TUNEOPS_CREDENTIAL_STORAGE", "files").strip().casefold() in {
        "database", "db", "sqlite", "turso"
    }


def current_user_id() -> str:
    value = os.getenv("TUNEOPS_LOCAL_USER_ID", "").strip()
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise CredentialConfigurationError(
            "TUNEOPS_LOCAL_USER_ID must be a UUID"
        ) from exc


def ensure_user(
    user_id: str | None = None,
    *,
    display_name: str = "Jon",
    path: Path = DATABASE_PATH,
) -> str:
    resolved = str(uuid.UUID(user_id or current_user_id()))
    now = _now()
    initialize(path)
    with connect(path) as connection:
        _ensure_user(connection, resolved, display_name, now)
    return resolved


def _ensure_user(
    connection: Any,
    user_id: str,
    display_name: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO app_users(id, display_name, status, created_at, updated_at)
        VALUES(?, ?, 'active', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            display_name=CASE
                WHEN excluded.display_name != '' THEN excluded.display_name
                ELSE app_users.display_name
            END,
            updated_at=excluded.updated_at
        """,
        (user_id, str(display_name or ""), now, now),
    )


def _provider(value: str) -> str:
    provider = str(value or "").strip().casefold()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported credential provider: {provider or '(empty)'}")
    return provider


def _connection_id(user_id: str, provider: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tuneops:{user_id}:{provider}"))


def _metadata_cache_key(path: Path, user_id: str) -> tuple[str, str]:
    return str(Path(path).resolve()), user_id


def _invalidate_connection_metadata(
    user_id: str,
    *,
    path: Path = DATABASE_PATH,
) -> None:
    _CONNECTION_METADATA_CACHE.pop(_metadata_cache_key(path, user_id), None)


class CredentialCipher:
    def __init__(self, secret: str | None = None):
        supplied = (secret or os.getenv("TUNEOPS_CREDENTIAL_KEY", "")).strip()
        if len(supplied) < 32:
            raise CredentialConfigurationError(
                "TUNEOPS_CREDENTIAL_KEY must contain at least 32 characters"
            )
        self._key = hashlib.sha256(
            b"tuneops/provider-credentials/v1\0" + supplied.encode("utf-8")
        ).digest()
        self.key_id = "env-v1-" + hashlib.sha256(self._key).hexdigest()[:12]

    @staticmethod
    def _aad(user_id: str, provider: str, connection_id: str) -> bytes:
        return f"tuneops:v1:{user_id}:{provider}:{connection_id}".encode("utf-8")

    def encrypt(
        self, user_id: str, provider: str, connection_id: str, payload: dict[str, Any]
    ) -> str:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        encrypted = AESGCM(self._key).encrypt(
            nonce, plaintext, self._aad(user_id, provider, connection_id)
        )
        return base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")

    def decrypt(
        self, user_id: str, provider: str, connection_id: str, ciphertext: str
    ) -> dict[str, Any]:
        try:
            packed = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
            plaintext = AESGCM(self._key).decrypt(
                packed[:12], packed[12:], self._aad(user_id, provider, connection_id)
            )
            payload = json.loads(plaintext)
        except Exception as exc:
            raise CredentialDecryptionError(
                "Provider credentials could not be decrypted"
            ) from exc
        if not isinstance(payload, dict):
            raise CredentialDecryptionError("Provider credential payload is invalid")
        return payload


def connection_metadata(
    provider: str,
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    provider = _provider(provider)
    return connection_metadata_for_providers(
        (provider,), user_id=user_id, path=path
    ).get(provider)


def connection_metadata_for_providers(
    providers: tuple[str, ...] | list[str] | frozenset[str] = tuple(SUPPORTED_PROVIDERS),
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
) -> dict[str, dict[str, Any]]:
    """Return non-secret provider metadata using one read-only query.

    The short process-local cache contains connection status only. Decrypted
    credential payloads never enter it.
    """
    requested = tuple(dict.fromkeys(_provider(item) for item in providers))
    if not requested:
        return {}
    resolved = user_id or current_user_id()
    cache_key = _metadata_cache_key(path, resolved)
    cached = _CONNECTION_METADATA_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < CONNECTION_METADATA_CACHE_SECONDS:
        return {
            provider: dict(cached[1][provider])
            for provider in requested
            if provider in cached[1]
        }
    initialize(path)
    with connect_readonly(path) as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, provider, provider_account_id, display_label,
                   status, scopes_json, expires_at, last_refreshed_at,
                   last_verified_at, credential_key_id,
                   credential_schema_version, credential_version,
                   created_at, updated_at
            FROM provider_connections
            WHERE user_id=?
            """,
            (resolved,),
        ).fetchall()
    all_metadata = {str(row["provider"]): dict(row) for row in rows}
    _CONNECTION_METADATA_CACHE[cache_key] = (now, all_metadata)
    return {
        provider: dict(all_metadata[provider])
        for provider in requested
        if provider in all_metadata
    }


def credential_availability(
    providers: dict[str, Path | None],
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
) -> dict[str, bool]:
    """Check several providers without multiplying database transactions."""
    normalized = {_provider(provider): legacy for provider, legacy in providers.items()}
    if not storage_enabled():
        return {
            provider: bool(legacy_file and legacy_file.exists())
            for provider, legacy_file in normalized.items()
        }
    metadata = connection_metadata_for_providers(
        tuple(normalized), user_id=user_id, path=path
    )
    return {provider: provider in metadata for provider in normalized}


def credentials_available(
    provider: str,
    legacy_file: Path | None = None,
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
) -> bool:
    if storage_enabled():
        return connection_metadata(provider, user_id=user_id, path=path) is not None
    return bool(legacy_file and legacy_file.exists())


def load_credentials(
    provider: str,
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
    cipher: CredentialCipher | None = None,
) -> dict[str, Any] | None:
    provider = _provider(provider)
    resolved = user_id or current_user_id()
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT id, credential_ciphertext, credential_schema_version
            FROM provider_connections
            WHERE user_id=? AND provider=? AND status != 'disconnected'
            """,
            (resolved, provider),
        ).fetchone()
    if row is None:
        return None
    if int(row["credential_schema_version"]) != CREDENTIAL_SCHEMA_VERSION:
        raise CredentialDecryptionError("Provider credential version is unsupported")
    return (cipher or CredentialCipher()).decrypt(
        resolved, provider, row["id"], row["credential_ciphertext"]
    )


def save_credentials(
    provider: str,
    payload: dict[str, Any],
    *,
    user_id: str | None = None,
    provider_account_id: str = "",
    display_label: str = "",
    scopes: list[str] | tuple[str, ...] = (),
    expires_at: str | float | int | None = None,
    event_type: str = "credentials_saved",
    path: Path = DATABASE_PATH,
    cipher: CredentialCipher | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Credential payload must be a non-empty object")
    provider = _provider(provider)
    resolved = str(uuid.UUID(user_id or current_user_id()))
    connection_id = _connection_id(resolved, provider)
    credential_cipher = cipher or CredentialCipher()
    ciphertext = credential_cipher.encrypt(resolved, provider, connection_id, payload)
    now = _now()
    expiry = str(expires_at) if expires_at not in (None, "") else None
    initialize(path)
    with connect(path) as connection:
        _ensure_user(connection, resolved, "Jon", now)
        metadata = connection.execute(
            """
            INSERT INTO provider_connections(
                id, user_id, provider, provider_account_id, display_label,
                status, scopes_json, expires_at, last_refreshed_at,
                credential_ciphertext, credential_key_id,
                credential_schema_version, credential_version,
                created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, 'connected', ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                provider_account_id=CASE
                    WHEN excluded.provider_account_id != ''
                    THEN excluded.provider_account_id
                    ELSE provider_connections.provider_account_id
                END,
                display_label=CASE
                    WHEN excluded.display_label != '' THEN excluded.display_label
                    ELSE provider_connections.display_label
                END,
                status='connected', scopes_json=excluded.scopes_json,
                expires_at=excluded.expires_at,
                last_refreshed_at=excluded.last_refreshed_at,
                credential_ciphertext=excluded.credential_ciphertext,
                credential_key_id=excluded.credential_key_id,
                credential_schema_version=excluded.credential_schema_version,
                credential_version=provider_connections.credential_version + 1,
                updated_at=excluded.updated_at
            RETURNING id, user_id, provider, provider_account_id, display_label,
                      status, scopes_json, expires_at, last_refreshed_at,
                      last_verified_at, credential_key_id,
                      credential_schema_version, credential_version,
                      created_at, updated_at
            """,
            (
                connection_id, resolved, provider, provider_account_id,
                display_label, json.dumps(list(scopes), separators=(",", ":")),
                expiry, now, ciphertext, credential_cipher.key_id,
                CREDENTIAL_SCHEMA_VERSION, now, now,
            ),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO credential_audit_events(
                id, user_id, provider, event_type, detail, created_at
            ) VALUES(?, ?, ?, ?, '', ?)
            """,
            (str(uuid.uuid4()), resolved, provider, event_type, now),
        )
    _invalidate_connection_metadata(resolved, path=path)
    return dict(metadata) if metadata else {}


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} does not contain valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{path.name} does not contain a credential object")
    return payload


def load_or_import_file_credentials(
    provider: str,
    source: Path,
    *,
    user_id: str | None = None,
    path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    stored = load_credentials(provider, user_id=user_id, path=path)
    if stored is not None:
        return stored
    if not source.exists():
        return None
    payload = read_json_file(source)
    scopes = payload.get("scope") or payload.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    expires_at = payload.get("expires_at") or payload.get("expiry_time")
    save_credentials(
        provider,
        payload,
        user_id=user_id,
        scopes=[str(item) for item in scopes] if isinstance(scopes, list) else [],
        expires_at=expires_at,
        event_type="credentials_imported_from_file",
        path=path,
    )
    return load_credentials(provider, user_id=user_id, path=path)


class SpotifyDatabaseCacheHandler(CacheHandler):
    """Spotipy cache handler preserving the complete provider token object."""

    def __init__(
        self,
        source: Path,
        *,
        user_id: str | None = None,
        path: Path = DATABASE_PATH,
    ):
        self.source = source
        self.user_id = user_id or current_user_id()
        self.path = path

    def get_cached_token(self) -> dict[str, Any] | None:
        return load_or_import_file_credentials(
            "spotify", self.source, user_id=self.user_id, path=self.path
        )

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        current = load_credentials(
            "spotify", user_id=self.user_id, path=self.path
        ) or {}
        payload = dict(token_info)
        if not payload.get("refresh_token") and current.get("refresh_token"):
            payload["refresh_token"] = current["refresh_token"]
        save_credentials(
            "spotify",
            payload,
            user_id=self.user_id,
            scopes=str(payload.get("scope") or "").split(),
            expires_at=payload.get("expires_at"),
            event_type="credentials_refreshed",
            path=self.path,
        )
