#!/usr/bin/env python3
"""Apply TuneOps ratings and tags to TIDAL tracks in VirtualDJ's database.xml.

This utility intentionally uses only Python's standard library. It matches the
numeric TIDAL track ID exported by TuneOps to VirtualDJ identities such as
``netsearch://td345534654``. Artist/title fallback matching is never attempted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET


SONG_RE = re.compile(r"(?ms)^[ \t]*<Song\b.*?</Song>")
TIDAL_FILE_RE = re.compile(r"^netsearch://td(\d+)$", re.IGNORECASE)
TIDAL_LINK_RE = re.compile(r"^td(\d+)$", re.IGNORECASE)
TAGS_RE = re.compile(r"(?s)<Tags\b[^>]*?/?>")
STARS_RE = re.compile(r"(?s)(\sStars\s*=\s*)(['\"])(.*?)\2", re.IGNORECASE)
YEAR_RE = re.compile(r"(?s)(\sYear\s*=\s*)(['\"])(.*?)\2", re.IGNORECASE)
COMMENT_RE = re.compile(r"(?s)(<Comment(?:\s[^>]*)?>)(.*?)(</Comment>)")
TUNEOPS_LINE_RE = re.compile(r"(?:^|\r?\n)\[TuneOps\][^\r\n]*", re.IGNORECASE)


@dataclass
class PatchStats:
    exported_tracks: int = 0
    matched_tracks: int = 0
    matched_song_entries: int = 0
    changed_song_entries: int = 0
    conflicting_song_entries: int = 0
    missing_track_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackMetadata:
    rating: int | None
    dimensions: dict[str, list[str]]
    tags: list[str]
    year: str | None = None
    sync_comment: bool = True


def default_database_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return Path.home() / "AppData" / "Local" / "VirtualDJ" / "database.xml"
    return Path(local_app_data) / "VirtualDJ" / "database.xml"


def load_metadata_export(path: Path) -> dict[str, TrackMetadata]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the TuneOps export: {exc}") from exc
    export_type = payload.get("type")
    version = payload.get("schema_version")
    if (export_type, version) == ("tuneops.virtualdj-ratings", 1):
        items = payload.get("ratings", [])
    elif (export_type, version) == ("tuneops.virtualdj-metadata", 2):
        items = payload.get("tracks", [])
    else:
        raise ValueError("This is not a supported TuneOps VirtualDJ metadata export.")
    metadata: dict[str, TrackMetadata] = {}
    for item in items:
        track_id = str(item.get("tidal_track_id") or "").strip()
        try:
            rating = int(item.get("rating"))
        except (TypeError, ValueError):
            rating = None
        if rating is not None and not 1 <= rating <= 5:
            rating = None
        year = str(item.get("year") or "").strip()
        if not re.fullmatch(r"\d{4}", year):
            year = None
        if not track_id.isdigit():
            continue
        dimensions = {
            str(dimension).strip().lower(): [str(value).strip() for value in values if str(value).strip()]
            for dimension, values in (item.get("dimensions") or {}).items()
            if isinstance(values, list)
        }
        tags = [str(value).strip() for value in (item.get("tags") or []) if str(value).strip()]
        metadata[track_id] = TrackMetadata(
            rating=rating,
            year=year,
            dimensions=dimensions,
            tags=tags,
            sync_comment=export_type == "tuneops.virtualdj-metadata",
        )
    return metadata


def load_ratings_export(path: Path) -> dict[str, int]:
    return {
        track_id: item.rating
        for track_id, item in load_metadata_export(path).items()
        if item.rating is not None
    }


def tidal_id_for_song(song: ET.Element) -> tuple[str | None, bool]:
    """Return (TIDAL ID, conflict) from a parsed VirtualDJ Song element."""
    identities: set[str] = set()
    file_match = TIDAL_FILE_RE.fullmatch(str(song.attrib.get("FilePath") or ""))
    if file_match:
        identities.add(file_match.group(1))
    for link in song.findall("Link"):
        link_match = TIDAL_LINK_RE.fullmatch(str(link.attrib.get("NetSearch") or ""))
        if link_match:
            identities.add(link_match.group(1))
    if len(identities) > 1:
        return None, True
    return (next(iter(identities)), False) if identities else (None, False)


def _patch_native_rating(block: str, rating: int | None) -> str:
    if rating is None:
        return block
    tags = TAGS_RE.search(block)
    if not tags:
        return block
    element = tags.group(0)
    if STARS_RE.search(element):
        updated = STARS_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{rating}{match.group(2)}",
            element,
            count=1,
        )
    else:
        closing = re.search(r"\s*/?>$", element)
        if not closing:
            return block
        updated = element[:closing.start()] + f' Stars="{rating}"' + closing.group(0)
    return block[:tags.start()] + updated + block[tags.end():]


def _patch_native_year(block: str, year: str | None) -> str:
    if year is None:
        return block
    tags = TAGS_RE.search(block)
    if not tags:
        return block
    element = tags.group(0)
    if YEAR_RE.search(element):
        updated = YEAR_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{year}{match.group(2)}",
            element,
            count=1,
        )
    else:
        closing = re.search(r"\s*/?>$", element)
        if not closing:
            return block
        updated = element[:closing.start()] + f' Year="{year}"' + closing.group(0)
    return block[:tags.start()] + updated + block[tags.end():]


def _hashtag(value: str) -> str:
    token = "".join(character for character in str(value).strip() if character.isalnum() or character == "_")
    return f"#{token}" if token else ""


def tuneops_comment_line(item: TrackMetadata) -> str:
    values: list[str] = []
    for dimension, selected in item.dimensions.items():
        if dimension == "rating":
            continue
        for value in selected:
            tagged_value = f"{dimension.title()}{value}" if dimension in {"energy", "tension"} else value
            tag = _hashtag(tagged_value)
            if tag:
                values.append(tag)
    values.extend(tag for tag in (_hashtag(value) for value in item.tags) if tag)
    unique = list(dict.fromkeys(value.casefold() for value in values))
    original_by_key = {value.casefold(): value for value in values}
    return "[TuneOps] " + " ".join(original_by_key[key] for key in unique) if unique else ""


def _patch_tuneops_comment(block: str, line: str) -> str:
    comment = COMMENT_RE.search(block)
    if comment:
        manual = TUNEOPS_LINE_RE.sub("", comment.group(2)).strip("\r\n")
        content = f"{manual}\n{line}" if manual and line else manual or line
        updated = comment.group(1) + content + comment.group(3)
        return block[:comment.start()] + updated + block[comment.end():]
    if not line:
        return block
    newline = "\r\n" if "\r\n" in block else "\n"
    closing = re.search(r"(?m)^(?P<indent>[ \t]*)</Song>", block)
    if not closing:
        return block
    link = re.search(r"(?m)^(?P<indent>[ \t]*)<Link\b", block)
    child_indent = link.group("indent") if link else closing.group("indent") + "  "
    insertion_at = link.start() if link else closing.start()
    comment_line = f"{child_indent}<Comment>{line}</Comment>{newline}"
    return block[:insertion_at] + comment_line + block[insertion_at:]


def patch_database_text(
    xml_text: str,
    ratings: dict[str, int],
    comments: dict[str, str] | None = None,
    years: dict[str, str] | None = None,
) -> tuple[str, PatchStats]:
    comments = comments or {}
    years = years or {}
    target_ids = set(ratings) | set(comments) | set(years)
    matched_ids: set[str] = set()
    matched_entries = 0
    changed_entries = 0
    conflicts = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal matched_entries, changed_entries, conflicts
        block = match.group(0)
        try:
            song = ET.fromstring(block)
        except ET.ParseError:
            return block
        track_id, conflict = tidal_id_for_song(song)
        if conflict:
            conflicts += 1
            return block
        if not track_id or track_id not in target_ids:
            return block
        matched_ids.add(track_id)
        matched_entries += 1
        patched = _patch_native_rating(block, ratings.get(track_id))
        patched = _patch_native_year(patched, years.get(track_id))
        if track_id in comments:
            patched = _patch_tuneops_comment(patched, comments[track_id])
        if patched != block:
            changed_entries += 1
        return patched

    patched = SONG_RE.sub(replace, xml_text)
    return patched, PatchStats(
        exported_tracks=len(target_ids),
        matched_tracks=len(matched_ids),
        matched_song_entries=matched_entries,
        changed_song_entries=changed_entries,
        conflicting_song_entries=conflicts,
        missing_track_ids=tuple(sorted(target_ids - matched_ids, key=int)),
    )


def write_database(database: Path, patched_text: str, had_bom: bool) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database.with_name(f"{database.name}.tuneops-{stamp}.bak")
    shutil.copy2(database, backup)
    data = patched_text.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".tuneops-", suffix=".xml", dir=database.parent, delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        ET.parse(temporary_name)
        os.replace(temporary_name, database)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise
    return backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply TuneOps metadata to VirtualDJ's database.xml.",
    )
    parser.add_argument("export", type=Path, help="TuneOps *-virtualdj-metadata.json file")
    parser.add_argument(
        "--database", type=Path, default=default_database_path(),
        help="VirtualDJ database.xml path (the normal Windows path is detected automatically)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write changes. Without this flag the command is a read-only preview.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metadata = load_metadata_export(args.export)
        ratings = {
            track_id: item.rating for track_id, item in metadata.items()
            if item.rating is not None
        }
        comments = {
            track_id: tuneops_comment_line(item)
            for track_id, item in metadata.items()
            if item.sync_comment
        }
        years = {
            track_id: item.year for track_id, item in metadata.items()
            if item.year is not None
        }
        raw = args.database.read_bytes()
        had_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        ET.fromstring(text)
        patched, stats = patch_database_text(text, ratings, comments, years)
    except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Exported tracks:        {stats.exported_tracks}")
    print(f"Matched TIDAL tracks:   {stats.matched_tracks}")
    print(f"Matched database songs: {stats.matched_song_entries}")
    print(f"Song entries changed:   {stats.changed_song_entries}")
    if stats.conflicting_song_entries:
        print(f"Skipped ID conflicts:   {stats.conflicting_song_entries}")
    if stats.missing_track_ids:
        preview = ", ".join(stats.missing_track_ids[:10])
        suffix = " ..." if len(stats.missing_track_ids) > 10 else ""
        print(f"Not found in VirtualDJ: {len(stats.missing_track_ids)} ({preview}{suffix})")
    if not args.apply:
        print("\nPreview only. Close VirtualDJ, then rerun with --apply to write changes.")
        return 0
    if not stats.changed_song_entries:
        print("\nNothing needed changing; database.xml was left untouched.")
        return 0
    try:
        backup = write_database(args.database, patched, had_bom)
    except (OSError, ET.ParseError) as exc:
        print(f"Error while writing: {exc}", file=sys.stderr)
        return 3
    print(f"\nUpdated {args.database}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
