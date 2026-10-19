from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import main as engine
from music_tools.youtube_analytics import service


def test_tidal_refresh_writes_database_not_legacy_file(monkeypatch, tmp_path):
    legacy = tmp_path / ".tidal_session.json"
    captured = {}
    monkeypatch.setattr(engine, "TIDAL_CACHE", legacy)
    monkeypatch.setattr(engine, "credential_storage_enabled", lambda: True)
    monkeypatch.setattr(
        engine, "save_credentials", lambda provider, payload, **metadata: captured.update(
            provider=provider, payload=payload, metadata=metadata
        )
    )
    session = SimpleNamespace(
        token_type="Bearer",
        access_token="access-secret",
        refresh_token="refresh-secret",
        expiry_time=datetime(2030, 1, 2, tzinfo=timezone.utc),
        user=SimpleNamespace(id="tidal-user"),
    )

    engine._save_tidal_session(session)

    assert not legacy.exists()
    assert captured["provider"] == "tidal"
    assert captured["payload"]["refresh_token"] == "refresh-secret"
    assert captured["metadata"]["provider_account_id"] == "tidal-user"


def test_youtube_refresh_preserves_refresh_token_in_database(monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "credential_storage_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "load_or_import_file_credentials",
        lambda *_args, **_kwargs: {"refresh_token": "keep-me"},
    )
    monkeypatch.setattr(
        service,
        "save_credentials",
        lambda provider, payload, **metadata: captured.update(
            provider=provider, payload=payload, metadata=metadata
        ),
    )

    service._write_token({"access_token": "fresh", "expires_at": 123})

    assert captured["provider"] == "youtube"
    assert captured["payload"]["access_token"] == "fresh"
    assert captured["payload"]["refresh_token"] == "keep-me"


def test_connection_badge_uses_selected_credential_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_connection_state", lambda: {"spotify": "Jon"})
    monkeypatch.setattr(
        engine,
        "credentials_available",
        lambda provider, legacy: provider == "spotify" and not legacy.exists(),
    )

    text, css_class = engine._connection_badge("spotify", tmp_path / "missing")

    assert "connected: Jon" in text
    assert css_class == "connection connected"
