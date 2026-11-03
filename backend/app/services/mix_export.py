"""One-shot exports of persisted My Mix setlists to provider playlists."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import main as engine
from backend.music_tools.mixes.service import Mix


def export_mix_to_spotify(
    mix: Mix,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create a private Spotify playlist without persisting a sync mapping."""
    report = progress or (lambda _message: None)
    tidal_reference = mix.tidal_playlist_id or mix.tidal_url
    if not tidal_reference:
        raise ValueError("Import a TIDAL setlist before exporting this mix to Spotify")

    report("Connecting to Spotify")
    spotify = engine.spotify_client()
    report("Connecting to TIDAL")
    tidal = engine.tidal_client(interactive=False)

    # This mapping is deliberately transient. It is never passed to
    # save_sync_mappings(), so the export cannot silently enter Playlist Sync.
    transient_mapping: dict[str, Any] = {
        "name": mix.folder_name,
        "direction": "tidal_to_spotify",
        "tidal": tidal_reference,
        "tidal_name": mix.tidal_playlist_name or f"djset {mix.folder_name}",
        "spotify": "",
        "unmatched": {},
    }
    report(f"Exporting {mix.folder_name} to a new Spotify playlist")
    result = engine.sync_tidal_to_spotify(
        spotify,
        tidal,
        transient_mapping,
        engine.load_runtime_settings(),
    )
    playlist_id = str(transient_mapping.get("spotify") or "")
    if not playlist_id:
        raise RuntimeError("Spotify did not return the created playlist ID")
    report(
        f"Spotify export complete: {result.added} added, "
        f"{result.unmatched} unmatched"
    )
    return {
        **asdict(result),
        "spotify_playlist_id": playlist_id,
        "spotify_playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
    }
