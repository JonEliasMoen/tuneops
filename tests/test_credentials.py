from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from spotipy.cache_handler import CacheHandler

from music_library.credentials import (
    CredentialCipher,
    CredentialConfigurationError,
    CredentialDecryptionError,
    SpotifyDatabaseCacheHandler,
    connection_metadata,
    load_credentials,
    load_or_import_file_credentials,
    save_credentials,
)


USER_ID = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
SECRET = "test-only-credential-key-with-at-least-32-characters"


def test_cipher_round_trip_and_context_binding():
    cipher = CredentialCipher(SECRET)
    payload = {"access_token": "secret-access", "refresh_token": "secret-refresh"}
    encrypted = cipher.encrypt(USER_ID, "spotify", "connection-a", payload)

    assert "secret-access" not in encrypted
    assert cipher.decrypt(USER_ID, "spotify", "connection-a", encrypted) == payload
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(USER_ID, "youtube", "connection-a", encrypted)
    with pytest.raises(CredentialDecryptionError):
        CredentialCipher(SECRET + "different").decrypt(
            USER_ID, "spotify", "connection-a", encrypted
        )


def test_cipher_requires_a_real_external_secret():
    with pytest.raises(CredentialConfigurationError):
        CredentialCipher("too-short")


def test_repository_encrypts_and_versions_credentials(tmp_path):
    path = tmp_path / "library.sqlite3"
    cipher = CredentialCipher(SECRET)
    save_credentials(
        "tidal",
        {"access_token": "first", "token_type": "Bearer"},
        user_id=USER_ID,
        path=path,
        cipher=cipher,
    )
    save_credentials(
        "tidal",
        {"access_token": "second", "token_type": "Bearer"},
        user_id=USER_ID,
        path=path,
        cipher=cipher,
    )

    assert load_credentials(
        "tidal", user_id=USER_ID, path=path, cipher=cipher
    )["access_token"] == "second"
    metadata = connection_metadata("tidal", user_id=USER_ID, path=path)
    assert metadata["credential_version"] == 2
    with sqlite3.connect(path) as connection:
        ciphertext = connection.execute(
            "SELECT credential_ciphertext FROM provider_connections"
        ).fetchone()[0]
        events = connection.execute(
            "SELECT COUNT(*) FROM credential_audit_events"
        ).fetchone()[0]
    assert "first" not in ciphertext and "second" not in ciphertext
    assert events == 2


def test_file_import_is_idempotent_and_does_not_modify_source(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite3"
    source = tmp_path / ".youtube_oauth.json"
    original = json.dumps({"access_token": "one", "refresh_token": "refresh"})
    source.write_text(original, encoding="utf-8")
    monkeypatch.setenv("TUNEOPS_CREDENTIAL_KEY", SECRET)

    first = load_or_import_file_credentials(
        "youtube", source, user_id=USER_ID, path=path
    )
    assert source.read_text(encoding="utf-8") == original
    changed = json.dumps({"access_token": "changed", "refresh_token": "changed"})
    source.write_text(changed, encoding="utf-8")
    second = load_or_import_file_credentials(
        "youtube", source, user_id=USER_ID, path=path
    )

    assert first == second
    assert second["access_token"] == "one"
    assert source.read_text(encoding="utf-8") == changed


def test_spotify_cache_handler_preserves_refresh_token(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite3"
    source = tmp_path / ".spotify_cache"
    source.write_text(
        json.dumps({"access_token": "old", "refresh_token": "keep-me"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TUNEOPS_CREDENTIAL_KEY", SECRET)
    monkeypatch.setenv("MUSICSYNC_DATABASE", str(path))
    handler = SpotifyDatabaseCacheHandler(source, user_id=USER_ID, path=path)
    assert isinstance(handler, CacheHandler)
    assert handler.get_cached_token()["refresh_token"] == "keep-me"
    handler.save_token_to_cache({"access_token": "new", "expires_at": 123})

    stored = load_credentials(
        "spotify", user_id=USER_ID, path=path, cipher=CredentialCipher(SECRET)
    )
    assert stored["access_token"] == "new"
    assert stored["refresh_token"] == "keep-me"
