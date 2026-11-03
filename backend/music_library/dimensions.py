"""Shared catalog for user-owned track classification dimensions."""

from __future__ import annotations


DIMENSION_VALUES: dict[str, list[str]] = {
    "rating": ["1", "2", "3", "4", "5"],
    "energy": ["1", "2", "3", "4", "5"],
    "tension": ["1", "2", "3", "4", "5"],
    "vibe": [
        "Dreamy", "Dark", "Hypnotic", "Emotional", "Euphoric",
        "Atmospheric", "Warm", "Sexy", "Playful", "Mysterious",
        "Tense", "Cinematic",
    ],
    "movement": [
        "Rolling", "Groovy", "Driving", "Bouncy", "Pumping", "Flowing",
        "Minimal", "Swinging", "Stomping", "Chugging", "Tribal",
    ],
    "driver": [
        "Groove", "Bass", "Percussion", "Melody", "Vocal", "Atmosphere",
        "Lead/Acid",
    ],
    "function": [
        "Opener", "Warmup", "Builder", "Peak", "Breather", "Bridge",
        "Reset", "Closer", "Vibe Flip", "Anthem",
    ],
    "structure": [
        "Groove-led", "Progressive", "Loop-led", "Drop", "Big Drop",
        "Breakdown-heavy", "Vocal-led", "Journey", "Tool",
    ],
    "texture": [
        "Organic", "Tribal", "Aquatic", "Airy", "Mechanical", "Industrial",
        "Acidic", "Dubby", "Percussive", "Cinematic", "Raw", "Polished",
    ],
    "scale": ["Intimate", "Backroom", "Club", "Mainroom", "Festival", "Outdoor"],
}

DIMENSION_LABELS = {
    dimension: dimension.title() for dimension in DIMENSION_VALUES
}

# One means radio-button semantics. Driver and Scale intentionally support a
# primary choice plus one optional secondary choice.
DIMENSION_MAX_VALUES = {
    "rating": 1,
    "energy": 1,
    "tension": 1,
    "driver": 2,
    "scale": 2,
}

SINGLE_VALUE_DIMENSIONS = {
    dimension for dimension, maximum in DIMENSION_MAX_VALUES.items() if maximum == 1
}
