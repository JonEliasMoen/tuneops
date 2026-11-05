"""Small exact-key persistent cache for public provider responses."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.music_library.connection import TursoDatabaseError
from backend.music_library.database import DATABASE_PATH, connect, connect_readonly


LOGGER = logging.getLogger("musicsync")
PROVIDER_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_response_cache (
    provider TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (provider, cache_key)
);
"""


class ProviderResponseCache:
    """Store JSON objects behind a provider-scoped, exact primary key."""

    def __init__(self, provider: str, *, path: Path = DATABASE_PATH) -> None:
        self.provider = provider.strip().casefold()
        self.path = path
        self._warned_unavailable = False

    def _unavailable(self, operation: str, exc: Exception) -> None:
        if self._warned_unavailable:
            return
        self._warned_unavailable = True
        LOGGER.warning(
            "provider_cache.unavailable provider=%s operation=%s error=%s",
            self.provider,
            operation,
            type(exc).__name__,
        )

    def get(self, cache_key: str, *, now: int | None = None) -> dict[str, Any] | None:
        current = int(time.time()) if now is None else int(now)
        try:
            with connect_readonly(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT response_json
                    FROM provider_response_cache
                    WHERE provider=? AND cache_key=? AND expires_at>?
                    """,
                    (self.provider, cache_key, current),
                ).fetchone()
        except (sqlite3.DatabaseError, TursoDatabaseError) as exc:
            self._unavailable("read", exc)
            return None
        if row is None:
            return None
        try:
            payload = json.loads(str(row["response_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def set(
        self,
        cache_key: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
        now: int | None = None,
    ) -> None:
        current = int(time.time()) if now is None else int(now)
        expires = current + max(1, int(ttl_seconds))
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            with connect(self.path) as connection:
                connection.execute(
                    """
                    INSERT INTO provider_response_cache(
                        provider, cache_key, response_json, expires_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(provider, cache_key) DO UPDATE SET
                        response_json=excluded.response_json,
                        expires_at=excluded.expires_at,
                        updated_at=excluded.updated_at
                    """,
                    (self.provider, cache_key, encoded, expires, current),
                )
        except (sqlite3.DatabaseError, TursoDatabaseError) as exc:
            self._unavailable("write", exc)

