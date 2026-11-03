from __future__ import annotations

from backend.music_tools.watched_mixes.tracklist import parse_tracklist


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


def test_parse_1001tracklists_export_skips_notes_and_cleans_labels():
    rows = parse_tracklist(
        """John Summit & Subtronics @ Festival 2026-09-20

[00:00] John Summit & Subtronics - ID
[02:34] Walker & Royce ft. Nathan Nicholson - Multiply [EXPERTS ONLY]
w/ Doechii - Anxiety (Acappella) [TOP DAWG]
LEVEL UP on Stage
[1:00:24] Anyma vs. Da Hool - Voices vs. Meet Her (Live Mashup) [LABEL/A]

Please set a backlink to keep the tracklist up-to-date: https://1001.tl/example
"""
    )

    assert [(row["timestamp"], row["artist"], row["title"]) for row in rows] == [
        ("00:00", "John Summit & Subtronics", "ID"),
        ("02:34", "Walker & Royce ft. Nathan Nicholson", "Multiply"),
        ("02:34", "Doechii", "Anxiety (Acappella)"),
        ("1:00:24", "Anyma", "Voices"),
        ("1:00:24", "Da Hool", "Meet Her"),
    ]
    assert rows[0]["status"] == "unresolved"
    assert all("LABEL" not in row["title"] for row in rows)


def test_generic_tracklist_behavior_is_unchanged_by_1001_export_support():
    rows = parse_tracklist(
        "Mix heading\n[00:00] Artist - Track [Personal edit]\nw/ Other - Overlay"
    )

    assert rows[0]["status"] == "invalid"
    assert rows[1]["title"] == "Track [Personal edit]"
    assert rows[2]["artist"] == "w/ Other"
