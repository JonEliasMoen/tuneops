from __future__ import annotations

from profile_library import _percentile


def test_profile_percentile_interpolates_sorted_values():
    assert _percentile([40, 10, 30, 20], 0.5) == 25
    assert _percentile([100], 0.95) == 100
    assert _percentile([], 0.95) == 0
