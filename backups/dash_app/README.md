# Archived Dash frontend

This directory contains the retired Dash presentation layer moved out of the
active application on 2026-10-19. The production/local web UI is now the React
SPA served by FastAPI.

The files here are retained as source reference only. They are not imported by
the active backend and are not expected to run in-place: their original package
layout and the shared sync engine can be recovered from Git history if the Dash
application ever needs to be reconstructed.

Active service code remains under `music_tools/*/service.py` and
`music_tools/watched_mixes/tracklist.py`. `main.py` remains the shared sync and
provider engine, but launching it now starts FastAPI/React; `--sync` remains the
headless sync entry point.
