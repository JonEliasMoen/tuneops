from __future__ import annotations

from music_tools.watched_mixes.tracklist import parse_tracklist


def test_parse_tracklist_accepts_plain_and_bracketed_timestamps_and_stars():
    rows = parse_tracklist(
        "00:48 Sultan + Shepard & Prinze George - Centuries (Extended Mix) *\n"
        "[1:06:16] Above & Beyond - Sun In Your Eyes (Marsh Remix)\n"
        "12:00 Marsh - ID"
    )

    assert rows[0]["timestamp"] == "00:48"
    assert rows[0]["artist"] == "Sultan + Shepard & Prinze George"
    assert rows[0]["title"] == "Centuries (Extended Mix)"
    assert rows[0]["status"] == "unsearched"
    assert rows[1]["timestamp"] == "1:06:16"
    assert rows[1]["artist"] == "Above & Beyond"
    assert rows[2]["status"] == "unresolved"


def test_parse_tracklist_can_reverse_title_artist_order():
    row = parse_tracklist("03:20 Home - Marsh", "title_artist")[0]
    assert row["artist"] == "Marsh"
    assert row["title"] == "Home"


def test_parse_tracklist_expands_versus_mashup_into_searchable_tracks():
    rows = parse_tracklist(
        "32:30 Armin van Buuren & Sharon Den Adel vs. OTTAGON – "
        "In And Out Of Love vs. Fathers And Sons (Armin van Buuren Mashup)"
    )

    assert [(row["artist"], row["title"]) for row in rows] == [
        ("Armin van Buuren & Sharon Den Adel", "In And Out Of Love"),
        ("OTTAGON", "Fathers And Sons"),
    ]
    assert {row["timestamp"] for row in rows} == {"32:30"}
    assert len({row["row_id"] for row in rows}) == 2
    assert all(row["status"] == "unsearched" for row in rows)


def test_parse_tracklist_keeps_unbalanced_versus_text_as_one_track():
    row = parse_tracklist("01:00 Artist A vs. Artist B - One Song")[0]

    assert row["artist"] == "Artist A vs. Artist B"
    assert row["title"] == "One Song"
