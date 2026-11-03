"""Experimental 1001Tracklists parsing foundation.

This package is intentionally not wired into an API or page yet. Importing it
never performs network I/O; callers must instantiate ``Tracklist`` explicitly.
"""

from .tracklists import Artist, Label, Track, Tracklist
from .service import fetch_staging_tracklist

__all__ = ["Artist", "Label", "Track", "Tracklist", "fetch_staging_tracklist"]
