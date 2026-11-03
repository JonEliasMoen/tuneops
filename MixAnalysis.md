# My Mix analysis plan

## Goal

Add an interactive **Analyze mix** panel to My Mix detail pages. The panel
should make the set's tempo, harmonic movement, and optional energy curve easy
to understand without pretending that unavailable timing data is exact.

## Visualization

- One point represents one track in set order.
- Y-axis is BPM.
- X-axis uses a real cue/timestamp when the setlist has one; otherwise it uses
  track number. Do not derive fake set time by summing full TIDAL durations,
  because DJ transitions overlap and tracks are often shortened.
- Connect track points with a restrained curve that passes through the real
  values. Avoid smoothing that invents additional BPM peaks or dips.
- Point fill uses TuneOps' existing Camelot color scale.
- A missing BPM or key remains visibly unknown rather than being interpolated.
- Optional Energy 1–5 is initially represented by point size. A later toggle
  may show a separate energy curve on the same X-axis.

### Tooltip

Hovering or focusing a point shows:

```text
Track title
Artist
06A · 128 BPM
Energy 4
Track 7 · 32:40
```

The tooltip omits unavailable fields. Keyboard focus must expose the same
information as mouse hover. Clicking a point selects that track in the existing
track inspector.

## Derived analysis

The first version can derive these values from the ordered track page without
new persistent aggregates:

- BPM range, start/end BPM, and largest adjacent BPM change.
- Camelot sequence and compatible/neutral/high-risk adjacent transitions.
- Energy start, peak, end, and largest adjacent change when Energy is tagged.
- Track position or known set timestamp for every observation.

Keep the calculation shared between the frontend visualization and future MCP
analysis output. Do not scan unrelated library tracks or fetch providers when a
mix page opens.

## MCP foundation

The read-only MCP tools are:

- `list_my_mixes`: bounded, cursor-paginated My Mix metadata and cached YouTube
  analytics.
- `get_my_mix`: one exact mix plus a bounded, cursor-paginated ordered track
  page containing BPM, Camelot key, Energy, and known mix positions.

Both require `library:read`. They use only cached TuneOps data and make no live
YouTube or TIDAL calls.

## Future review field

A future, separately approved phase may add an MCP-generated review. Store it
in a new `mix_reviews` table rather than altering the existing setlist table.
That phase needs a dedicated write tool, approval semantics, review history,
and a database backup/migration review. It is intentionally out of scope for
the current read-only implementation.

## Delivery phases

1. Read-only MCP mix discovery and detail tools.
2. Shared analysis data model and unit tests.
3. React chart, tooltip, keyboard access, and track selection integration.
4. Optional review persistence and approval-gated MCP write after explicit
   authorization.
