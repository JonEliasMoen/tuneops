"""Local Ollama-assisted classification for cached track metadata."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from music_library.dimensions import DIMENSION_MAX_VALUES, DIMENSION_VALUES


AUTO_DIMENSIONS = tuple(dimension for dimension in DIMENSION_VALUES if dimension != "rating")


def _json_object(value: Any) -> dict[str, Any]:
    """Decode strict, fenced, or explanation-prefixed model JSON."""
    text = str(value or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        parsed, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed


def _validated_dimensions(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for dimension in AUTO_DIMENSIONS:
        values = raw.get(dimension, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        allowed = DIMENSION_VALUES[dimension]
        clean = [value for value in dict.fromkeys(values) if value in allowed]
        maximum = DIMENSION_MAX_VALUES.get(dimension)
        if maximum:
            clean = clean[:maximum]
        if clean:
            result[dimension] = clean
    return result


def auto_tag_tracks(
    tracks: list[dict[str, Any]],
    model: str = "qwen3:4b",
    base_url: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 300,
) -> dict[str, dict[str, list[str]]]:
    """Ask a local Ollama model for catalog-constrained track dimensions."""
    input_tracks = [
        {
            "id": str(track.get("id") or ""),
            "title": str(track.get("title") or ""),
            "artist": str(track.get("artist") or ""),
            "remix": str(track.get("remix") or ""),
            "album": str(track.get("album") or ""),
            "bpm": str(track.get("bpm") or ""),
            "key": str(track.get("key") or ""),
            "year": str(track.get("year") or ""),
        }
        for track in tracks
        if str(track.get("id") or "")
    ]
    if not input_tracks:
        return {}
    catalog = {
        dimension: values
        for dimension, values in DIMENSION_VALUES.items()
        if dimension in AUTO_DIMENSIONS
    }
    prompt = (
        "You classify electronic/DJ tracks for library preparation. Infer only from "
        "the supplied metadata and your musical knowledge. Return conservative useful "
        "tags; omit a dimension when uncertain. Never invent values outside the catalog. "
        "Energy and tension require exactly one value when supplied. Driver and scale "
        "allow at most two values, ordered primary then secondary. Return JSON only with "
        "this shape: {\"tracks\":[{\"id\":\"...\",\"dimensions\":{...}}]}.\n\n"
        f"Allowed catalog:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        f"Tracks:\n{json.dumps(input_tracks, ensure_ascii=False)}"
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")
    endpoint = f"{base_url.rstrip('/')}/api/chat"
    http_request = request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=float(timeout_seconds)) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(
            f"Could not reach local Ollama at {base_url}. Is Ollama running?"
        ) from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama timed out or returned an invalid response") from exc
    message = envelope.get("message") if isinstance(envelope.get("message"), dict) else {}
    raw_result = (
        message.get("content")
        or message.get("thinking")
        or envelope.get("response")
        or envelope.get("thinking")
        or ""
    )
    try:
        result = _json_object(raw_result)
    except (json.JSONDecodeError, ValueError) as exc:
        detail = str(envelope.get("error") or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"The Ollama model returned invalid tagging JSON{suffix}"
        ) from exc
    wanted_ids = {track["id"] for track in input_tracks}
    tagged: dict[str, dict[str, list[str]]] = {}
    for item in result.get("tracks", []) if isinstance(result, dict) else []:
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id") or "")
        if track_id in wanted_ids:
            tagged[track_id] = _validated_dimensions(item.get("dimensions"))
    return tagged
