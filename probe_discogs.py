"""Read-only Discogs label/style coverage probe for cached TIDAL tracks.

Set ``DISCOGS_USER_TOKEN`` in ``.env`` before running this script. It performs
search and release-detail requests only; it never changes Discogs or SQLite.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from music_library.database import DATABASE_PATH, connect, initialize


ROOT = Path(__file__).resolve().parent
API_ROOT = "https://api.discogs.com"
USER_AGENT = "MusicSync/0.1 +https://localhost.invalid/musicsync"


def _load_local_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def cached_tracks(limit: int) -> list[dict[str, Any]]:
    initialize(DATABASE_PATH)
    with connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT provider_track_id AS id, title, artist, remix, album,
                   duration_seconds, release_year AS year, isrc
            FROM tracks
            WHERE provider='tidal' AND trim(COALESCE(title, '')) != ''
              AND trim(COALESCE(artist, '')) != ''
            ORDER BY refreshed_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def _normalized(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\b(feat(?:uring)?|ft)\.?\b", " ", text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _similarity(left: Any, right: Any) -> float:
    a, b = _normalized(left), _normalized(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _artist_similarity(wanted: Any, candidate: Any) -> float:
    a, b = _normalized(wanted), _normalized(candidate)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    wanted_names = {part.strip() for part in re.split(r"\b(?:and|x)\b", a) if part.strip()}
    candidate_names = {part.strip() for part in re.split(r"\b(?:and|x)\b", b) if part.strip()}
    overlap = max((_similarity(x, y) for x in wanted_names for y in candidate_names), default=0.0)
    return max(SequenceMatcher(None, a, b).ratio(), overlap)


class DiscogsClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Discogs token={token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.discogs.v2.discogs+json",
        })

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{API_ROOT}{path}", params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def search(self, track: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        payload = self._get("/database/search", params={
            "type": "release",
            "artist": track["artist"],
            "track": track["title"],
            "per_page": limit,
            "page": 1,
        })
        return list(payload.get("results") or [])

    def release(self, release_id: int | str) -> dict[str, Any]:
        return self._get(f"/releases/{release_id}")


def _release_artists(release: dict[str, Any]) -> str:
    artists = release.get("artists") or []
    return ", ".join(str(item.get("name") or "") for item in artists) or str(release.get("artists_sort") or "")


def score_release(track: dict[str, Any], release: dict[str, Any]) -> tuple[float, dict[str, Any] | None]:
    wanted_titles = [str(track.get("title") or "")]
    if track.get("remix"):
        wanted_titles.insert(0, f"{track['title']} ({track['remix']})")
    release_artist = _release_artists(release)
    best_score = 0.0
    best_track: dict[str, Any] | None = None
    for item in release.get("tracklist") or []:
        title_score = max(_similarity(title, item.get("title")) for title in wanted_titles)
        if title_score < 0.78:
            continue
        item_artist = ", ".join(
            str(artist.get("name") or "") for artist in (item.get("artists") or [])
        ) or release_artist
        artist_score = _artist_similarity(track.get("artist"), item_artist)
        if artist_score < 0.62:
            continue
        score = title_score * 60 + artist_score * 30
        if track.get("album") and release.get("title"):
            score += _similarity(track["album"], release["title"]) * 7
        try:
            if track.get("year") and release.get("year"):
                difference = abs(int(track["year"]) - int(release["year"]))
                score += 3 if difference == 0 else (1 if difference == 1 else 0)
        except (TypeError, ValueError):
            pass
        if score > best_score:
            best_score, best_track = score, item
    return round(best_score, 2), best_track


def probe_track(client: DiscogsClient, track: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    try:
        candidates = client.search(track)
    except requests.RequestException as exc:
        return {**track, "matched": False, "error": f"Search failed: {type(exc).__name__}: {exc}"}
    for candidate in candidates:
        try:
            release = client.release(candidate["id"])
            score, release_track = score_release(track, release)
            if release_track:
                ranked.append((score, release, release_track))
        except (KeyError, requests.RequestException) as exc:
            warnings.append(f"Release {candidate.get('id', '')}: {type(exc).__name__}: {exc}")
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 82:
        return {
            **track, "matched": False, "candidate_count": len(candidates),
            "best_score": ranked[0][0] if ranked else 0, "warnings": warnings,
        }
    score, release, release_track = ranked[0]
    labels = list(dict.fromkeys(
        str(item.get("name") or "").strip()
        for item in (release.get("labels") or [])
        if str(item.get("name") or "").strip()
    ))
    return {
        **track,
        "matched": True,
        "confidence": score,
        "discogs_release_id": release.get("id"),
        "discogs_release_title": release.get("title", ""),
        "discogs_track_title": release_track.get("title", ""),
        "discogs_artists": _release_artists(release),
        "discogs_year": release.get("year"),
        "labels": labels,
        "genres": list(release.get("genres") or []),
        "styles": list(release.get("styles") or []),
        "candidate_count": len(candidates),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--id", help="Probe one cached TIDAL track ID")
    args = parser.parse_args()
    _load_local_env()
    token = os.getenv("DISCOGS_USER_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCOGS_USER_TOKEN in musicsync/.env before running the probe.")
    tracks = cached_tracks(max(1, args.limit))
    if args.id:
        tracks = [track for track in tracks if str(track["id"]) == args.id]
        if not tracks:
            initialize(DATABASE_PATH)
            with connect(DATABASE_PATH) as connection:
                row = connection.execute(
                    """SELECT provider_track_id AS id, title, artist, remix, album,
                              duration_seconds, release_year AS year, isrc
                       FROM tracks WHERE provider='tidal' AND provider_track_id=?""",
                    (args.id,),
                ).fetchone()
            tracks = [dict(row)] if row else []
    client = DiscogsClient(token)
    results = [probe_track(client, track) for track in tracks]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    matched = sum(bool(item.get("matched")) for item in results)
    labels = sum(bool(item.get("labels")) for item in results)
    styles = sum(bool(item.get("styles")) for item in results)
    print(f"\nCoverage: matched={matched}/{len(results)} label={labels}/{len(results)} styles={styles}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
