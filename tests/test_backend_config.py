from __future__ import annotations

import math

from backend.app.config import integer_setting, number_setting


def test_number_setting_accepts_numbers_and_numeric_strings():
    assert number_setting({"delay": 0.25}, "delay", 1) == 0.25
    assert number_setting({"delay": "0.75"}, "delay", 1) == 0.75


def test_number_setting_falls_back_for_user_editable_invalid_values():
    for value in (None, "", "later", math.nan, math.inf, -math.inf):
        assert number_setting({"delay": value}, "delay", 0.35) == 0.35


def test_number_setting_clamps_provider_delays():
    assert number_setting({"delay": -4}, "delay", 0.35, minimum=0) == 0
    assert number_setting({"delay": 99}, "delay", 0.35, maximum=2) == 2


def test_integer_setting_applies_history_limits():
    assert integer_setting({"count": "24"}, "count", 20, minimum=1, maximum=100) == 24
    assert integer_setting({"count": 0}, "count", 20, minimum=1, maximum=100) == 1
    assert integer_setting({"count": 200}, "count", 20, minimum=1, maximum=100) == 100
