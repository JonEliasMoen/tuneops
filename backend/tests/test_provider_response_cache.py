from __future__ import annotations

from backend.music_library.database import initialize
from backend.music_library.provider_cache import ProviderResponseCache


def test_provider_response_cache_exact_key_and_expiry(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    cache = ProviderResponseCache("beatport", path=database)

    cache.set("request-a", {"results": [{"id": 1}]}, ttl_seconds=60, now=100)

    assert cache.get("request-a", now=159) == {"results": [{"id": 1}]}
    assert cache.get("request-b", now=159) is None
    assert cache.get("request-a", now=160) is None


def test_provider_response_cache_upserts_same_key(tmp_path):
    database = tmp_path / "library.sqlite3"
    initialize(database)
    cache = ProviderResponseCache("beatport", path=database)

    cache.set("request-a", {"value": "old"}, ttl_seconds=60, now=100)
    cache.set("request-a", {"value": "new"}, ttl_seconds=60, now=110)

    assert cache.get("request-a", now=169) == {"value": "new"}
