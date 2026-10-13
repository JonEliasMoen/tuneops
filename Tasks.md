# MusicSync tasks

Last reviewed: 2026-10-11.

## Controller input

- [ ] Add optional DDJ-FLX4 MIDI navigation alongside keyboard navigation.
  Start with a Settings MIDI monitor/device selector, then map the BROWSE
  encoder to Up/Down and its press to Enter through the shared navigation
  command layer. Ignore MIDI while editing form controls, handle rapid encoder
  input cleanly, and verify whether VirtualDJ/Rekordbox can share the MIDI port.

## Sync providers and lifecycle

- [ ] Investigate and add YouTube Music as a playlist-sync source for tracks
  discovered while searching there. First determine a maintainable
  authentication/API approach, then support YouTube Music -> TIDAL without
  weakening the existing diffing, throttling, unmatched-track, and logging
  behavior.
- [ ] Add a safe way to remove a playlist mapping from Playlist Sync. Define
  and test the lifecycle first: removing a mapping should stop future syncing
  but retain its indexed playlist and track memberships by default. Offer a
  separate, explicit **Remove cached library data** operation if cleanup is
  wanted; never delete tracks that are still liked or referenced by another
  playlist, event, source, mix, watched mix, or history record.

## Set planning

- [ ] Add a **Compatible tracks** view/action for a selected seed track. Rank
  the complete indexed library primarily by BPM proximity, then Camelot-key
  compatibility, then shared tags/dimensions. Show the score components rather
  than one unexplained score, and allow filtering the candidate collections.
- [ ] Design a **Set Builder** with an ordered working list, compatible-track
  suggestions based on the last selected/placed track, reorder/remove controls,
  saved drafts, and an export format VirtualDJ can consume (prefer M3U first).
- [ ] Prototype VirtualDJ SideList interoperability. First test read-only import
  from a SideList saved as M3U. Separately investigate whether a small VirtualDJ
  plugin can expose the live SideList safely; do not write to VirtualDJ's
  `database.xml` from MusicSync.

## Future

- [ ] Future: optionally materialize a Last.fm Top X history view as a TIDAL
  playlist; the current history views are read-only.
- [ ] Future: VirtualDJ export.
- [ ] Future: label-confidence metadata.
- [ ] Future: compatible BPM/key/tag/artist exploration.
- [ ] Future: scheduled cache/sync UI.

## Safety notes

- Auth remains Python-only: `.env`, Spotify/TIDAL caches, and connection state
  must never enter React.
- Normal browsing, sorting, filtering, and paging remain SQLite-only; provider
  work is explicit background work or a bounded entry refresh.
- Provider writes are provider-first and SQLite-second. Never test them live
  without explicit approval.
- Before changing, copying, rebuilding, backing up, or cleaning an existing
  SQLite table: stop the app and startup sync, tell Jon, and make an external
  backup first. Independent new tables are okay.
