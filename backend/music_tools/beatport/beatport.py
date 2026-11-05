"""Read-only client for Beatport's public catalogue endpoints."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import ssl
import sys
import threading
import time
from typing import Any, Literal, cast

import requests
from requests.adapters import HTTPAdapter

from backend.music_library.provider_cache import ProviderResponseCache


EntityType = Literal["genres", "labels", "artists", "tracks"]
ALLOWED_ENTITY_TYPES = frozenset({"genres", "labels", "artists", "tracks"})
BEATPORT_CACHE_SECONDS = 3600.0
LOGGER = logging.getLogger("musicsync")
PUBLIC_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.beatport.com/",
    # Beatport's public anonymous-token endpoint is protected by Cloudflare and
    # rejects the default python-requests identity. This identifies TuneOps as
    # an ordinary browser client; it does not spoof a signed-in Beatport user.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36"
    ),
}


class BeatportError(RuntimeError):
    """A sanitized provider failure suitable for an API boundary."""


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: dict[str, Any]


class _TrustStoreAdapter(HTTPAdapter):
    """Use the native Windows CA store without disabling TLS verification."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        try:
            import truststore
        except ImportError:
            return super().init_poolmanager(*args, **kwargs)
        kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return super().init_poolmanager(*args, **kwargs)


def _default_session() -> requests.Session:
    session = requests.Session()
    if sys.platform == "win32":
        session.mount("https://", _TrustStoreAdapter())
    return session


class BeatportClient:
    """Type-driven catalogue client with a small process-local anti-spam cache."""

    def __init__(self, *, session: requests.Session | None = None,
                 timeout_seconds: float = 8.0, cache_seconds: float = 300.0,
                 persistent_cache: ProviderResponseCache | None = None) -> None:
        self.session = session or _default_session()
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self.persistent_cache = persistent_cache
        self._token = ""
        self._token_expires_at = 0.0
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _entity_type(value: str) -> EntityType:
        if value not in ALLOWED_ENTITY_TYPES:
            raise ValueError(f"Unsupported Beatport entity type: {value}")
        return cast(EntityType, value)

    def _access_token(self, *, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            try:
                response = self.session.get(
                    "https://www.beatport.com/api/auth/refresh-anon-token",
                    headers=PUBLIC_HEADERS,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                token = str(payload.get("access_token") or "")
                if not token:
                    raise ValueError("missing access token")
                lifetime = max(60, int(payload.get("expires_in") or 600))
            except (requests.RequestException, ValueError, TypeError) as exc:
                LOGGER.warning("beatport.auth_failed error=%s", type(exc).__name__)
                raise BeatportError("Beatport authentication is temporarily unavailable.") from exc
            self._token = token
            self._token_expires_at = time.monotonic() + lifetime - 20
            return token

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean_params = {key: str(value) for key, value in (params or {}).items() if value is not None}
        cache_key = (path, tuple(sorted(clean_params.items())))
        persistent_key = hashlib.sha256(
            json.dumps(
                [path.lstrip("/"), clean_params],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.value
        if self.persistent_cache is not None:
            persisted = self.persistent_cache.get(persistent_key)
            if persisted is not None:
                with self._lock:
                    self._cache[cache_key] = _CacheEntry(
                        now + self.cache_seconds,
                        persisted,
                    )
                return persisted
        url = f"https://api.beatport.com/v4/catalog/{path.lstrip('/')}"
        for attempt in range(2):
            try:
                response = self.session.get(
                    url,
                    params=clean_params,
                    headers={
                        **PUBLIC_HEADERS,
                        "Authorization": f"Bearer {self._access_token(force=attempt > 0)}",
                    },
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 401 and attempt == 0:
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("unexpected response")
            except (requests.RequestException, ValueError, TypeError) as exc:
                LOGGER.warning(
                    "beatport.catalog_failed path=%s error=%s",
                    path, type(exc).__name__,
                )
                raise BeatportError("Beatport catalogue data could not be retrieved.") from exc
            with self._lock:
                self._cache[cache_key] = _CacheEntry(now + self.cache_seconds, payload)
            if self.persistent_cache is not None:
                self.persistent_cache.set(
                    persistent_key,
                    payload,
                    ttl_seconds=max(1, round(self.cache_seconds)),
                )
            return payload
        raise BeatportError("Beatport catalogue data could not be retrieved.")

    def search(self, entity_type: str, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        kind = self._entity_type(entity_type)
        needle = query.strip()
        if not needle:
            return []
        # Beatport's general search payload exposes labels/artists/tracks but
        # currently omits genres even when `type=genres` is requested. The
        # genre catalogue is small, so fetch its bounded first page once and
        # filter that cached response locally.
        if kind == "genres":
            rows = self._get("genres/", params={"page": 1, "per_page": 100}).get("results") or []
            normalized = needle.casefold()
            rows = [row for row in rows if isinstance(row, dict) and normalized in str(row.get("name") or "").casefold()]
        else:
            rows = self._get("search/", params={"q": needle, "type": kind}).get(kind) or []
        return [{"id": str(row["id"]), "name": str(row["name"]).strip(),
                 "type": kind, "slug": str(row.get("slug") or "")}
                for row in rows[:max(1, min(50, limit))]
                if isinstance(row, dict) and row.get("id") and row.get("name")]

    def top_tracks(
        self,
        entity_type: str,
        entity_id: str,
        *,
        page: int = 1,
        chart_size: int = 100,
    ) -> dict[str, Any]:
        """Return one provider page from a bounded Beatport Top chart.

        The final path segment selects the chart size, not the response page
        size. Beatport currently returns ten rows per page and exposes the
        remaining pages through its normal ``next`` metadata.
        """
        kind = self._entity_type(entity_type)
        if kind == "tracks" and entity_id != "top":
            raise ValueError("The global tracks chart must use the 'top' identifier.")
        size = max(1, min(100, chart_size))
        requested_page = max(1, page)
        path = (
            f"tracks/top/{size}"
            if kind == "tracks"
            else f"{kind}/{entity_id}/top/{size}"
        )
        payload = self._get(
            path,
            params={"page": requested_page},
        )
        raw_page = str(payload.get("page") or requested_page).strip()
        current_page = (
            int(raw_page.split("/", 1)[0])
            if raw_page.split("/", 1)[0].isdigit()
            else requested_page
        )
        return {
            "items": self._tracks(payload.get("results") or []),
            "has_more": bool(payload.get("next")),
            "total": max(0, int(payload.get("count") or 0)),
            "page": max(1, current_page),
            "per_page": max(1, int(payload.get("per_page") or 10)),
        }

    def releases(self, entity_type: str, entity_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        kind = self._entity_type(entity_type)
        payload = self._get(f"{kind}/{entity_id}/releases/",
                            params={"page": 1, "per_page": max(1, min(100, limit))})
        return self._releases(payload.get("results") or [])

    def recent_tracks(
        self,
        entity_type: str,
        entity_id: str,
        *,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        kind = self._entity_type(entity_type)
        filter_name = {"genres": "genre_id", "labels": "label_id", "artists": "artist_id"}[kind]
        size = max(1, min(50, per_page))
        payload = self._get("tracks/", params={
            "order_by": "-publish_date",
            filter_name: entity_id,
            "page": max(1, page),
            "per_page": size,
        })
        raw_page = str(payload.get("page") or page).strip()
        current_page = int(raw_page.split("/", 1)[0]) if raw_page.split("/", 1)[0].isdigit() else max(1, page)
        return {
            "items": self._tracks(payload.get("results") or []),
            "has_more": bool(payload.get("next")),
            "total": max(0, int(payload.get("count") or 0)),
            "page": max(1, current_page),
            "per_page": size,
        }

    @staticmethod
    def _artists(row: dict[str, Any]) -> str:
        return ", ".join(str(artist.get("name") or "").strip()
                         for artist in row.get("artists") or []
                         if isinstance(artist, dict) and artist.get("name"))

    @staticmethod
    def _artist_refs(row: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"id": str(artist["id"]), "name": str(artist["name"]).strip()}
            for artist in row.get("artists") or []
            if isinstance(artist, dict) and artist.get("id") and artist.get("name")
        ]

    @classmethod
    def _tracks(cls, rows: list[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for position, raw in enumerate(rows, start=1):
            if not isinstance(raw, dict):
                continue
            release = raw.get("release") if isinstance(raw.get("release"), dict) else {}
            label = release.get("label") if isinstance(release.get("label"), dict) else {}
            key = raw.get("key") if isinstance(raw.get("key"), dict) else {}
            genre = raw.get("genre") if isinstance(raw.get("genre"), dict) else {}
            camelot = ""
            if key.get("camelot_number") and key.get("camelot_letter"):
                camelot = f"{int(key['camelot_number']):02d}{key['camelot_letter']}"
            result.append({
                "position": position, "id": str(raw.get("id") or ""),
                "title": str(raw.get("name") or ""), "mix": str(raw.get("mix_name") or ""),
                "artists": cls._artists(raw), "artist_refs": cls._artist_refs(raw),
                "bpm": raw.get("bpm"), "key": camelot,
                "label": str(label.get("name") or ""),
                "label_id": str(label.get("id") or ""),
                "genre": str(genre.get("name") or ""),
                "genre_id": str(genre.get("id") or ""),
                "isrc": str(raw.get("isrc") or ""),
                "release_date": str(raw.get("publish_date") or raw.get("new_release_date") or ""),
                "length_ms": raw.get("length_ms") or raw.get("length"),
                "exclusive": bool(raw.get("exclusive")),
            })
        return result

    @classmethod
    def _releases(cls, rows: list[Any]) -> list[dict[str, Any]]:
        return [{"position": position, "id": str(row.get("id") or ""),
                 "title": str(row.get("name") or ""), "artists": cls._artists(row),
                 "release_date": str(row.get("new_release_date") or row.get("publish_date") or ""),
                 "exclusive": bool(row.get("exclusive"))}
                for position, row in enumerate(rows, start=1) if isinstance(row, dict)]


client = BeatportClient(
    cache_seconds=BEATPORT_CACHE_SECONDS,
    persistent_cache=ProviderResponseCache("beatport"),
)
