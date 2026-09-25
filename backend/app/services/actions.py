"""Provider-first track actions shared by the React API.

The existing cached TIDAL session remains the only authentication mechanism.
SQLite is updated only after the corresponding provider mutation succeeds.
"""

from __future__ import annotations

import logging
from typing import Literal

import main as engine
from music_library.database import (
    add_tidal_playlist_membership,
    remove_tidal_playlist_membership,
    tidal_indexed_playlists,
    tidal_playlists_for_tracks,
)


LOGGER = logging.getLogger("musicsync")
PlaylistActionName = Literal["add", "remove", "move"]


class TrackActionError(RuntimeError):
    """A safe, user-facing action failure."""


def _indexed_playlist(playlist_id: str) -> dict[str, object]:
    playlist = next(
        (item for item in tidal_indexed_playlists() if str(item.get("id") or "") == playlist_id),
        None,
    )
    if playlist is None:
        raise TrackActionError("That destination is not an indexed TIDAL playlist.")
    return playlist


def mutate_playlist_tracks(
    action: PlaylistActionName,
    track_ids: list[str],
    playlist_id: str,
    source_playlist_id: str | None = None,
) -> dict[str, object]:
    unique_ids = [value for value in dict.fromkeys(str(item).strip() for item in track_ids) if value]
    if not unique_ids:
        raise TrackActionError("Select at least one track.")
    destination_record = _indexed_playlist(playlist_id)
    if action == "move":
        if not source_playlist_id:
            raise TrackActionError("Move requires the currently viewed source playlist.")
        if source_playlist_id == playlist_id:
            raise TrackActionError("Choose a different destination playlist.")
        source_record = _indexed_playlist(source_playlist_id)
        if str(source_record.get("collection_type") or "playlist") != "playlist":
            raise TrackActionError("Move is only available from a normal Playlist collection.")

    memberships = tidal_playlists_for_tracks(unique_ids)
    actionable: list[str] = []
    for track_id in unique_ids:
        current = {str(item.get("id") or "") for item in memberships.get(track_id, [])}
        if action == "add" and playlist_id in current:
            continue
        if action == "remove" and playlist_id not in current:
            continue
        if action == "move" and source_playlist_id not in current:
            continue
        actionable.append(track_id)

    if not actionable:
        verb = {"add": "already in", "remove": "not in", "move": "not in the source"}[action]
        return {
            "action": action,
            "changed": 0,
            "skipped": len(unique_ids),
            "failed": 0,
            "message": f"All selected tracks were {verb} that playlist.",
        }

    try:
        session = engine.tidal_client(interactive=False)
        destination = engine._call(
            "tidal",
            "get_writable_playlist",
            lambda: session.playlist(playlist_id),
            playlist_id=playlist_id,
        )
        required = "add" if action in {"add", "move"} else "remove_by_id"
        if not hasattr(destination, required):
            raise TrackActionError("That playlist is not writable by the connected TIDAL account.")
        source = None
        if action == "move":
            source = engine._call(
                "tidal",
                "get_move_source_playlist",
                lambda: session.playlist(source_playlist_id),
                playlist_id=source_playlist_id,
            )
            if not hasattr(source, "remove_by_id"):
                raise TrackActionError("The source playlist is not writable by the connected TIDAL account.")

        changed = 0
        failed = 0
        for track_id in actionable:
            try:
                if action == "add":
                    engine._call(
                        "tidal",
                        "playlist_add_from_react",
                        lambda current=track_id: destination.add([current], allow_duplicates=False),
                        playlist_id=playlist_id,
                        track_id=track_id,
                    )
                    add_tidal_playlist_membership(playlist_id, track_id)
                elif action == "remove":
                    removed = engine._call(
                        "tidal",
                        "playlist_remove_from_react",
                        lambda current=track_id: destination.remove_by_id(current),
                        playlist_id=playlist_id,
                        track_id=track_id,
                    )
                    if not removed:
                        raise TrackActionError("TIDAL did not find a selected track in that playlist.")
                    remove_tidal_playlist_membership(playlist_id, track_id)
                else:
                    added = engine._call(
                        "tidal",
                        "playlist_move_add_from_react",
                        lambda current=track_id: destination.add([current], allow_duplicates=False),
                        playlist_id=playlist_id,
                        track_id=track_id,
                    )
                    try:
                        removed = engine._call(
                            "tidal",
                            "playlist_move_remove_from_react",
                            lambda current=track_id: source.remove_by_id(current),
                            playlist_id=source_playlist_id,
                            track_id=track_id,
                        )
                        if not removed:
                            raise TrackActionError("TIDAL did not find a selected track in the source playlist.")
                    except Exception:
                        if added:
                            try:
                                engine._call(
                                    "tidal",
                                    "playlist_move_rollback_from_react",
                                    lambda current=track_id: destination.remove_by_id(current),
                                    playlist_id=playlist_id,
                                    track_id=track_id,
                                )
                            except Exception:
                                LOGGER.exception(
                                    "react.track_action rollback_failed track_id=%s playlist_id=%s",
                                    track_id,
                                    playlist_id,
                                )
                        raise
                    add_tidal_playlist_membership(playlist_id, track_id)
                    remove_tidal_playlist_membership(str(source_playlist_id), track_id)
                changed += 1
            except Exception:
                failed += 1
                LOGGER.exception(
                    "react.track_action track_failed action=%s playlist_id=%s track_id=%s",
                    action,
                    playlist_id,
                    track_id,
                )
    except TrackActionError:
        raise
    except Exception as exc:
        LOGGER.exception(
            "react.track_action failed action=%s playlist_id=%s tracks=%d",
            action,
            playlist_id,
            len(actionable),
        )
        raise TrackActionError("TIDAL could not complete the playlist action. Check the log for details.") from exc

    skipped = len(unique_ids) - changed - failed
    destination_name = str(destination_record.get("name") or playlist_id)
    past = {"add": "Added", "remove": "Removed", "move": "Moved"}[action]
    LOGGER.info(
        "react.track_action ok action=%s playlist=%r changed=%d skipped=%d",
        action,
        destination_name,
        changed,
        skipped,
    )
    message = f"{past} {changed} track{'s' if changed != 1 else ''} {'to' if action != 'remove' else 'from'} {destination_name}."
    if failed:
        message += f" {failed} track{'s' if failed != 1 else ''} could not be changed; successful changes were kept."
    elif skipped:
        message += f" {skipped} already matched the requested state."
    return {
        "action": action,
        "changed": changed,
        "skipped": skipped,
        "failed": failed,
        "message": message,
    }
