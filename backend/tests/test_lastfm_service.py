from __future__ import annotations

from backend.music_tools.lastfm import service


def test_lastfm_matching_uses_only_the_indexed_tuneops_library(monkeypatch):
    monkeypatch.setattr(
        service,
        "tidal_library_tracks_page",
        lambda limit: [
            {
                "id": "tidal-1",
                "title": "A Track",
                "artist": "Local Artist",
                "remix": "",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "tidal_artists_for_tracks",
        lambda track_ids: {"tidal-1": [{"name": "Local Artist"}]},
    )
    records = [
        {
            "played_at": 1,
            "artist": "Local Artist",
            "title": "A Track",
            "normalized_artist": "local artist",
            "normalized_title": "a track",
        },
        {
            "played_at": 2,
            "artist": "Unknown Artist",
            "title": "Missing Track",
            "normalized_artist": "unknown artist",
            "normalized_title": "missing track",
        },
    ]

    matched, identity_count = service._match_records_to_indexed_tracks(records)

    assert identity_count == 1
    assert [(row["played_at"], row["track_id"]) for row in matched] == [
        (1, "tidal-1")
    ]


def test_ambiguous_indexed_matches_are_discarded(monkeypatch):
    monkeypatch.setattr(
        service,
        "_indexed_matcher",
        lambda: ({("artist", "track"): {"one", "two"}}, {}),
    )

    matched, identity_count = service._match_records_to_indexed_tracks(
        [
            {
                "played_at": 1,
                "artist": "Artist",
                "title": "Track",
                "normalized_artist": "artist",
                "normalized_title": "track",
            }
        ]
    )

    assert matched == []
    assert identity_count == 0
