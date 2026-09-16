"""Stable, tool-neutral API for the shared interactive track browser.

The implementation currently lives in ``liked_tracks`` for compatibility with
the original feature. New tools must import it through this package so the
implementation can move without changing every consumer.
"""

def content(*args, **kwargs):
    from music_tools.liked_tracks.page import content as implementation

    return implementation(*args, **kwargs)


def register_callbacks(*args, **kwargs):
    from music_tools.liked_tracks.page import register_callbacks as implementation

    return implementation(*args, **kwargs)

__all__ = ["content", "register_callbacks"]
