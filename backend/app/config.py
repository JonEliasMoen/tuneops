"""Small, defensive accessors for user-editable application settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def number_setting(
    settings: Mapping[str, Any],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Return a finite numeric setting or its default, optionally clamped."""
    raw = settings.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    if value != value or value in {float("inf"), float("-inf")}:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def integer_setting(
    settings: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Return an integer setting, accepting JSON numbers and numeric strings."""
    value = int(number_setting(settings, key, default))
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value
