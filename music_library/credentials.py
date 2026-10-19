"""Encrypted, user-scoped provider credentials stored in the library DB."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from music_library.database import DATABASE_PATH, connect, initialize


SUPPORTED_PROVIDERS = frozenset({"spotify", "tidal", "youtube"})
CREDENTIAL_SCHEMA_VERSION = 1


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
            (resolved, str(display_name or ""), now, now),
        )
    return resolved


def _provider(value: str) -> str:
    provider = str(value or "").strip().casefold()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported credential provider: {provider or '(empty)'}")
    return provider


def _connection_id(user_id: str, provider: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tuneops:{user_id}:{provider}"))


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
    resolved = user_id or current_user_id()
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT id, user_id, provider, provider_account_id, display_label,
                   status, scopes_json, expires_at, last_refreshed_at,
                   last_verified_at, credential_key_id,
                   credential_schema_version, credential_version,
                   created_at, updated_at
            FROM provider_connections
            WHERE user_id=? AND provider=?
            """,
            (resolved, provider),
        ).fetchone()
    return dict(row) if row else None


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
    resolved = ensure_user(user_id, path=path)
    connection_id = _connection_id(resolved, provider)
    credential_cipher = cipher or CredentialCipher()
    ciphertext = credential_cipher.encrypt(resolved, provider, connection_id, payload)
    now = _now()
    expiry = str(expires_at) if expires_at not in (None, "") else None
    with connect(path) as connection:
        connection.execute(
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
            """,
            (
                connection_id, resolved, provider, provider_account_id,
                display_label, json.dumps(list(scopes), separators=(",", ":")),
                expiry, now, ciphertext, credential_cipher.key_id,
                CREDENTIAL_SCHEMA_VERSION, now, now,
            ),
        )
        connection.execute(
            """
            INSERT INTO credential_audit_events(
                id, user_id, provider, event_type, detail, created_at
            ) VALUES(?, ?, ?, ?, '', ?)
            """,
            (str(uuid.uuid4()), resolved, provider, event_type, now),
        )
    return connection_metadata(provider, user_id=resolved, path=path) or {}


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


class SpotifyDatabaseCacheHandler:
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
