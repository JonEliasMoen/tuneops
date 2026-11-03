"""Experimental 1001Tracklists parsing foundation.

This package is intentionally not wired into an API or page yet. Importing it
never performs network I/O; callers must instantiate ``Tracklist`` explicitly.
"""

from .tracklists import Artist, Label, Track, Tracklist

__all__ = ["Artist", "Label", "Track", "Tracklist"]
