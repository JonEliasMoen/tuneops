"""Short-lived process cache for the assembled sidebar navigation."""

from __future__ import annotations

from copy import deepcopy
import threading
import time
from typing import Any


NAVIGATION_CACHE_SECONDS = 45.0

_lock = threading.Lock()
_cached_at = 0.0
_cached_payload: dict[str, Any] | None = None


def get_navigation_snapshot() -> dict[str, Any] | None:
    """Return an isolated cached payload while its short TTL is valid."""
    global _cached_at, _cached_payload
    with _lock:
        if (
            _cached_payload is None
            or time.monotonic() - _cached_at >= NAVIGATION_CACHE_SECONDS
        ):
            _cached_at = 0.0
            _cached_payload = None
            return None
        return deepcopy(_cached_payload)


def store_navigation_snapshot(payload: dict[str, Any]) -> None:
    """Replace the cached payload after a complete navigation read."""
    global _cached_at, _cached_payload
    with _lock:
        _cached_payload = deepcopy(payload)
        _cached_at = time.monotonic()


def invalidate_navigation_snapshot() -> None:
    """Make the next navigation request rebuild from authoritative stores."""
    global _cached_at, _cached_payload
    with _lock:
        _cached_at = 0.0
        _cached_payload = None
