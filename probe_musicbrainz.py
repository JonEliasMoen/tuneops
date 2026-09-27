"""Read-only MusicBrainz metadata coverage probe for cached TIDAL tracks."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

import musicbrainzngs

from music_library.database import DATABASE_PATH, connect, initialize


def cached_tracks_with_isrc(limit: int) -> list[dict[str, str]]:
    initialize(DATABASE_PATH)
    with connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT provider_track_id AS id, title, artist, isrc
            FROM tracks
            WHERE provider='tidal' AND trim(COALESCE(isrc, '')) != ''
            ORDER BY refreshed_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def _names(items: list[dict[str, Any]], key: str = "name") -> list[str]:
    return list(dict.fromkeys(str(item.get(key) or "").strip() for item in items if str(item.get(key) or "").strip()))


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _recording_candidates(track: dict[str, str]) -> tuple[list[dict[str, Any]], str, list[str]]:
    warnings: list[str] = []
    try:
        response = musicbrainzngs.get_recordings_by_isrc(track["isrc"], includes=["artists", "releases"])
        recordings = response.get("isrc", {}).get("recording-list", [])
        if recordings:
            return recordings, "isrc", warnings
    except Exception as exc:
        if "404" not in str(exc):
            warnings.append(f"ISRC lookup: {type(exc).__name__}: {exc}")
    if not track.get("title") or not track.get("artist"):
        return [], "none", warnings
    try:
        searched = musicbrainzngs.search_recordings(
            recording=track["title"], artist=track["artist"], limit=5, strict=True
        ).get("recording-list", [])
    except Exception as exc:
        warnings.append(f"Title/artist search: {type(exc).__name__}: {exc}")
        return [], "none", warnings
    wanted_title = _normalized(track["title"])
    wanted_artist = _normalized(track["artist"])
    credible = []
    for item in searched:
        credits = " ".join(str(credit.get("artist", {}).get("name") or credit.get("name") or "") for credit in item.get("artist-credit", []))
        score = int(item.get("ext:score", item.get("score", 0)) or 0)
        if score >= 90 and _normalized(str(item.get("title") or "")) == wanted_title and wanted_artist in _normalized(credits):
            credible.append(item)
    return credible, "title_artist", warnings


def probe_track(track: dict[str, str]) -> dict[str, Any]:
    recordings, match_method, warnings = _recording_candidates(track)
    if not recordings:
        return {**track, "matched": False, "labels": [], "genres": [], "tags": [], "warnings": warnings}
    recording = recordings[0]
    try:
        recording = musicbrainzngs.get_recording_by_id(
            recording["id"], includes=["artists", "releases", "tags"]
        ).get("recording", recording)
    except Exception as exc:
        warnings.append(f"Recording enrichment: {type(exc).__name__}: {exc}")
    releases = recording.get("release-list", [])
    labels: list[str] = []
    for candidate_release in releases:
        try:
            release = musicbrainzngs.get_release_by_id(candidate_release["id"], includes=["labels"]).get("release", {})
            labels = _names([item.get("label", {}) for item in release.get("label-info-list", [])])
            if labels:
                break
        except Exception as exc:
            warnings.append(f"Release {candidate_release.get('id', '')}: {type(exc).__name__}: {exc}")
    tag_items = list(recording.get("tag-list", []))
    release_group_id = str((releases[0].get("release-group") or {}).get("id") or "") if releases else ""
    if release_group_id:
        try:
            release_group = musicbrainzngs.get_release_group_by_id(release_group_id, includes=["tags"]).get("release-group", {})
            tag_items.extend(release_group.get("tag-list", []))
        except Exception as exc:
            warnings.append(f"Release-group tags: {type(exc).__name__}: {exc}")
    tags = sorted(
        tag_items,
        key=lambda item: int(item.get("count", 0)),
        reverse=True,
    )
    return {
        **track,
        "matched": True,
        "match_method": match_method,
        "musicbrainz_recording_id": recording.get("id", ""),
        "musicbrainz_title": recording.get("title", ""),
        "labels": labels,
        "genres": _names(recording.get("genre-list", [])),
        "tags": _names(tags)[:10],
        "recording_candidates": len(recordings),
        "release_candidates": len(releases),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--isrc", help="Probe one explicitly supplied ISRC instead of reading the local library")
    args = parser.parse_args()
    musicbrainzngs.set_useragent("MusicSync", "0.1", "https://localhost.invalid/musicsync")
    tracks = [{"id": "", "title": "", "artist": "", "isrc": args.isrc.strip()}] if args.isrc else cached_tracks_with_isrc(args.limit)
    results = []
    for track in tracks:
        try:
            results.append(probe_track(track))
        except Exception as exc:
            results.append({**track, "matched": False, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    matched = sum(bool(item.get("matched")) for item in results)
    labels = sum(bool(item.get("labels")) for item in results)
    genres = sum(bool(item.get("genres") or item.get("tags")) for item in results)
    print(f"\nCoverage: matched={matched}/{len(results)} label={labels}/{len(results)} genre_or_tags={genres}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
