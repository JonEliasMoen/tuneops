"""Stable, tool-neutral API for the shared interactive track browser.

The implementation currently lives in ``liked_tracks`` for compatibility with
the original feature. New tools must import it through this package so the
implementation can move without changing every consumer.
"""

def content(*args, **kwargs):
    from backend.music_tools import content as implementation

    return implementation(*args, **kwargs)


def register_callbacks(*args, **kwargs):
    from backend.music_tools import register_callbacks as implementation

    return implementation(*args, **kwargs)

__all__ = ["content", "register_callbacks"]
