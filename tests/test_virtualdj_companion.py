from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "frontend" / "public" / "downloads" / "virtualdj-companion"
    / "tuneops_virtualdj.py"
)
SPEC = importlib.util.spec_from_file_location("tuneops_virtualdj", SCRIPT)
assert SPEC and SPEC.loader
companion = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = companion
SPEC.loader.exec_module(companion)


def database(song: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<VirtualDJ_Database Version="2026">\n{song}\n</VirtualDJ_Database>\n'


def test_rating_patch_matches_exact_tidal_id_and_preserves_manual_comment():
    source = database(
        '  <Song FilePath="netsearch://td345534654">\n'
        '    <Tags Author="Sames" Title="Trésor"/>\n'
        '    <Comment>Explicit</Comment>\n'
        '    <Link NetSearch="td345534654"/>\n'
        '  </Song>'
    )

    patched, stats = companion.patch_database_text(source, {"345534654": 4})

    assert 'Stars="4"' in patched
    assert "<Comment>Explicit</Comment>" in patched
    assert stats.matched_tracks == 1
    assert stats.matched_song_entries == 1
    assert stats.changed_song_entries == 1


def test_rating_patch_replaces_existing_native_stars_attribute():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Tags Title="Track" Stars=\'2\' Flag="1"/>\n'
        '    <Comment>Keep me</Comment>\n'
        '  </Song>'
    )

    patched, _ = companion.patch_database_text(source, {"12": 5})

    assert "Stars='5'" in patched
    assert "Stars='2'" not in patched
    assert "<Comment>Keep me</Comment>" in patched


def test_rating_patch_adds_native_stars_without_adding_comment():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Tags Title="Track"/>\n'
        '    <Link NetSearch="td12"/>\n'
        '  </Song>'
    )

    patched, _ = companion.patch_database_text(source, {"12": 3})

    assert '<Tags Title="Track" Stars="3"/>' in patched
    assert "<Comment>" not in patched


def test_rating_patch_refuses_conflicting_virtualdj_ids():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Link NetSearch="td34"/>\n'
        '  </Song>'
    )

    patched, stats = companion.patch_database_text(source, {"12": 3, "34": 4})

    assert patched == source
    assert stats.conflicting_song_entries == 1
    assert stats.matched_tracks == 0


def test_load_export_accepts_only_valid_rating_rows(tmp_path):
    export = tmp_path / "ratings.json"
    export.write_text(json.dumps({
        "schema_version": 1,
        "type": "tuneops.virtualdj-ratings",
        "ratings": [
            {"tidal_track_id": "12", "rating": 5},
            {"tidal_track_id": "not-an-id", "rating": 4},
            {"tidal_track_id": "34", "rating": 0},
        ],
    }), encoding="utf-8")

    assert companion.load_ratings_export(export) == {"12": 5}
    assert companion.load_metadata_export(export)["12"].sync_comment is False


def test_load_export_reads_ratings_from_richer_metadata_contract(tmp_path):
    export = tmp_path / "metadata.json"
    export.write_text(json.dumps({
        "schema_version": 2,
        "type": "tuneops.virtualdj-metadata",
        "tracks": [
            {"tidal_track_id": "12", "rating": 4, "year": "2024", "dimensions": {"rating": ["4"], "vibe": ["Dark"]}},
            {"tidal_track_id": "34", "rating": None, "dimensions": {"vibe": ["Dreamy"]}},
        ],
    }), encoding="utf-8")

    assert companion.load_ratings_export(export) == {"12": 4}
    assert companion.load_metadata_export(export)["12"].sync_comment is True
    assert companion.load_metadata_export(export)["12"].year == "2024"


def test_tuneops_comment_formats_all_non_rating_metadata_as_one_line():
    item = companion.TrackMetadata(
        rating=5,
        dimensions={
            "rating": ["5"],
            "energy": ["4"],
            "tension": ["3"],
            "vibe": ["Dark", "Hypnotic"],
            "function": ["Vibe Flip"],
            "driver": ["Lead/Acid"],
        },
        tags=["Warehouse", "Dark"],
    )

    assert companion.tuneops_comment_line(item) == (
        "[TuneOps] #Energy4 #Tension3 #Dark #Hypnotic "
        "#VibeFlip #LeadAcid #Warehouse"
    )


def test_metadata_patch_preserves_manual_comment_and_replaces_tuneops_line():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Tags Title="Track" Stars="2"/>\n'
        '    <Comment>My own note\n[TuneOps] #OldTag</Comment>\n'
        '    <Link NetSearch="td12"/>\n'
        '  </Song>'
    )

    patched, stats = companion.patch_database_text(
        source, {"12": 4}, {"12": "[TuneOps] #Energy4 #Dark"},
    )

    assert 'Stars="4"' in patched
    assert "<Comment>My own note\n[TuneOps] #Energy4 #Dark</Comment>" in patched
    assert "#OldTag" not in patched
    assert stats.changed_song_entries == 1


def test_metadata_patch_adds_one_comment_before_link():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Tags Title="Track"/>\n'
        '    <Link NetSearch="td12"/>\n'
        '  </Song>'
    )

    patched, _ = companion.patch_database_text(
        source, {}, {"12": "[TuneOps] #Rolling #Peak"},
    )

    assert patched.index("<Comment>") < patched.index("<Link")
    assert "<Comment>[TuneOps] #Rolling #Peak</Comment>" in patched


def test_metadata_patch_writes_release_year_to_native_tags_attribute():
    source = database(
        '  <Song FilePath="netsearch://td12">\n'
        '    <Tags Title="Track" Year="2020"/>\n'
        '    <Link NetSearch="td12"/>\n'
        '  </Song>'
    )

    patched, stats = companion.patch_database_text(source, {}, {}, {"12": "2024"})

    assert 'Year="2024"' in patched
    assert 'Year="2020"' not in patched
    assert stats.changed_song_entries == 1
