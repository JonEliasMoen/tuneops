import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Job, OrphanedTracksClearResult, OrphanedTracksPage, PublicSettings, YouTubeStatus } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'
import { COLUMNS, DEFAULT_FIELDS } from '../track-browser/columns'
import { DEFAULT_MIX_FIELDS, MIX_FIELD_OPTIONS } from '../mixes/mixOverview'

type SaveState = 'loading' | 'saved' | 'dirty' | 'saving' | 'error'
const EMPTY_CELL = '\u2014'

export function SettingsPage() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const youtube = useQuery({ queryKey: ['youtube-status'], queryFn: () => api<YouTubeStatus>('/youtube/status') })
  const orphaned = useQuery({ queryKey: ['orphaned-tracks'], queryFn: () => api<OrphanedTracksPage>('/settings/orphaned-tracks') })
  const [draft, setDraft] = useState<PublicSettings | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('loading')
  const [removingTrackId, setRemovingTrackId] = useState<string | null>(null)
  const draftRef = useRef<PublicSettings | null>(null)
  const hydrated = useRef(false)
  const lastSaved = useRef('')
  const failedSnapshot = useRef('')
  useEffect(() => { draftRef.current = draft }, [draft])
  useEffect(() => {
    if (!settings.data || hydrated.current) return
    draftRef.current = settings.data
    lastSaved.current = JSON.stringify(settings.data)
    hydrated.current = true
    setDraft(settings.data)
    setSaveState('saved')
  }, [settings.data])
  const save = useMutation({
    mutationFn: ({ snapshot }: { snapshot: PublicSettings; serialized: string }) => api<PublicSettings>('/settings', { method: 'PATCH', body: JSON.stringify(snapshot) }),
    retry: 2,
    onMutate: () => setSaveState('saving'),
    onSuccess: (value, variables) => {
      const persisted = JSON.stringify(value)
      lastSaved.current = persisted
      failedSnapshot.current = ''
      client.setQueryData(['settings'], value)
      if (JSON.stringify(draftRef.current) === variables.serialized) {
        draftRef.current = value
        setDraft(value)
        setSaveState('saved')
      } else {
        setSaveState('dirty')
      }
      void client.invalidateQueries({ queryKey: ['navigation'] })
    },
    onError: (_error, variables) => {
      failedSnapshot.current = variables.serialized
      setSaveState('error')
    },
  })
  useEffect(() => {
    if (!draft || !hydrated.current || save.isPending) return
    const serialized = JSON.stringify(draft)
    if (serialized === lastSaved.current) {
      if (saveState !== 'saved') setSaveState('saved')
      return
    }
    if (serialized === failedSnapshot.current) return
    setSaveState('dirty')
    const timer = window.setTimeout(() => save.mutate({ snapshot: draft, serialized }), 650)
    return () => window.clearTimeout(timer)
  }, [draft, save.isPending])
  const startJob = useMutation({
    mutationFn: (path: string) => api<Job>(path, { method: 'POST' }),
    onSuccess: (job) => setJobId(job.id),
  })
  const clearOrphaned = useMutation({
    mutationFn: () => api<OrphanedTracksClearResult>('/settings/orphaned-tracks', { method: 'DELETE' }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['orphaned-tracks'] })
      void client.invalidateQueries({ queryKey: ['navigation'] })
      void client.invalidateQueries({ queryKey: ['tracks'] })
    },
  })
  const removeOrphaned = useMutation({
    mutationFn: (trackId: string) => api<OrphanedTracksClearResult>(`/settings/orphaned-tracks/${encodeURIComponent(trackId)}`, { method: 'DELETE' }),
    onMutate: (trackId) => setRemovingTrackId(trackId),
    onSettled: () => setRemovingTrackId(null),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['orphaned-tracks'] })
      void client.invalidateQueries({ queryKey: ['tracks'] })
    },
  })
  function confirmClearOrphaned() {
    const count = orphaned.data?.total ?? 0
    if (!count || !window.confirm(`Permanently remove ${count} orphaned tracks from the local database? Ratings, tags, and dimensions attached only to these tracks will also be removed. Last.fm matches will be reset. Nothing is deleted from TIDAL.`)) return
    clearOrphaned.mutate()
  }
  function confirmRemoveOrphaned(trackId: string, title: string, artist: string) {
    if (!window.confirm(`Remove "${title}" by ${artist} from the local database? Nothing is deleted from TIDAL.`)) return
    removeOrphaned.mutate(trackId)
  }
  function addQuickView() {
    if (!draft) return
    const id = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `view-${Date.now()}`
    setDraft({
      ...draft,
      quick_views: [...draft.quick_views, { id, name: 'New view', fields: [...DEFAULT_FIELDS], default: draft.quick_views.length === 0 }],
    })
  }
  function updateQuickView(id: string, change: Partial<PublicSettings['quick_views'][number]>) {
    if (!draft) return
    setDraft({ ...draft, quick_views: draft.quick_views.map((view) => view.id === id ? { ...view, ...change } : view) })
  }
  function makeDefault(id: string) {
    if (!draft) return
    setDraft({ ...draft, quick_views: draft.quick_views.map((view) => ({ ...view, default: view.id === id })) })
  }
  function addMixQuickView() {
    if (!draft) return
    const id = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `mix-view-${Date.now()}`
    setDraft({ ...draft, mix_quick_views: [...draft.mix_quick_views, { id, name: 'New view', fields: [...DEFAULT_MIX_FIELDS], default: draft.mix_quick_views.length === 0 }] })
  }
  function updateMixQuickView(id: string, change: Partial<PublicSettings['mix_quick_views'][number]>) {
    if (!draft) return
    setDraft({ ...draft, mix_quick_views: draft.mix_quick_views.map((view) => view.id === id ? { ...view, ...change } : view) })
  }
  function makeMixDefault(id: string) {
    if (!draft) return
    setDraft({ ...draft, mix_quick_views: draft.mix_quick_views.map((view) => ({ ...view, default: view.id === id })) })
  }
  function retrySave() {
    const snapshot = draftRef.current
    if (!snapshot) return
    const serialized = JSON.stringify(snapshot)
    failedSnapshot.current = ''
    save.mutate({ snapshot, serialized })
  }
  if (!draft) return <p>Loading settings…</p>
  return <section className="settings-page">
    <header><h1>Settings</h1><p>These preferences are stored by the Python backend. Provider credentials never enter React.</p><div className="button-row"><span className={`mapping-save-status ${saveState}`}>{saveState === 'loading' ? 'Loading settings…' : saveState === 'saving' ? 'Saving changes…' : saveState === 'dirty' ? 'Changes pending…' : saveState === 'error' ? 'Autosave failed.' : 'Saved automatically.'}</span>{saveState === 'error' ? <button type="button" onClick={retrySave} disabled={save.isPending}>Retry save</button> : null}</div></header>
    <div className="settings-grid">
      <section className="settings-card"><h2>Appearance</h2>
        <label className="toggle-row"><input type="checkbox" checked={draft.dark_mode} onChange={(event) => setDraft({ ...draft, dark_mode: event.target.checked })} />Dark mode</label>
        <label className="toggle-row"><input type="checkbox" checked={draft.tags_collapsed_by_default} onChange={(event) => setDraft({ ...draft, tags_collapsed_by_default: event.target.checked })} />Tags collapsed by default</label>
        <label>Default column sort direction<select value={draft.default_sort_direction} onChange={(event) => setDraft({ ...draft, default_sort_direction: event.target.value as 'asc' | 'desc' })}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
      </section>
      <section className="settings-card"><h2>Last.fm</h2>
        <label>Username<input value={draft.lastfm_username} onChange={(event) => setDraft({ ...draft, lastfm_username: event.target.value })} /></label>
        <label>Top tracks per month<input type="number" min="1" max="100" value={draft.history_top_tracks} onChange={(event) => setDraft({ ...draft, history_top_tracks: Number(event.target.value) })} /></label>
        <p className={draft.lastfm_api_key_configured ? 'good' : 'warning'}>{draft.lastfm_api_key_configured ? 'API key configured in .env' : 'LASTFM_API_KEY is missing from .env'}</p>
        <div className="button-row"><button type="button" disabled={saveState !== 'saved' || startJob.isPending} onClick={() => startJob.mutate('/lastfm/import')}>Import plays</button><button type="button" disabled={saveState !== 'saved' || startJob.isPending} onClick={() => startJob.mutate('/lastfm/reconcile')}>Reconcile cached plays</button></div>
        <JobStatus jobId={jobId} />
      </section>
      <section className="settings-card"><h2>YouTube Analytics</h2>
        <p>Connect the Google account that owns your My Mixes videos. Credentials and tokens stay in the Python backend. Cover click rate also requires the YouTube Reporting API to be enabled in Google Cloud.</p>
        {!youtube.data ? <p>Checking connection…</p> : !youtube.data.configured ? <p className="warning">Google OAuth credentials or the redirect URI are missing from .env.</p> : youtube.data.connected ? <><p className="good">YouTube is connected.</p><a className="button-link" href="/api/v1/youtube/connect">Reconnect YouTube</a></> : <a className="button-link primary" href="/api/v1/youtube/connect">Connect YouTube</a>}
      </section>
      <section className="settings-card"><h2>Spotify matching</h2>
        <label>Search delay (seconds)<input type="number" min="0" step="0.05" value={draft.spotify_search_delay_seconds} onChange={(event) => setDraft({ ...draft, spotify_search_delay_seconds: Number(event.target.value) })} /></label>
      </section>
      <section className="settings-card"><h2>VirtualDJ companion</h2>
        <p>Download the standalone companion, then use a metadata export from any track table to import TuneOps ratings and tags into VirtualDJ.</p>
        <p className="muted">Downloading is safe and does not run anything. The companion previews changes by default; it writes only when you close VirtualDJ and explicitly run it with <code>--apply</code>.</p>
        <div className="button-row">
          <a className="button-link primary" href="/downloads/virtualdj-companion/tuneops_virtualdj.py" download="tuneops_virtualdj.py">Download VirtualDJ companion</a>
          <a className="button-link" href="/downloads/virtualdj-companion/README.txt" download="TuneOps-VirtualDJ-instructions.txt">Download instructions</a>
        </div>
      </section>
      <section className="settings-card quick-view-settings"><div className="settings-card-heading"><div><h2>Quick Views</h2><p>Named field sets for every track table. The default applies when no session view has been chosen yet.</p></div><button type="button" onClick={addQuickView}>Add Quick View</button></div>
        {draft.quick_views.length ? <div className="quick-view-list">{draft.quick_views.map((view) => <article className="quick-view-editor" key={view.id}>
          <div className="quick-view-head">
            <label>Name<input value={view.name} onChange={(event) => updateQuickView(view.id, { name: event.target.value })} /></label>
            <label className="toggle-row"><input type="radio" name="default-quick-view" checked={Boolean(view.default)} onChange={() => makeDefault(view.id)} />Default</label>
            <button type="button" className="danger" onClick={() => setDraft({ ...draft, quick_views: draft.quick_views.filter((item) => item.id !== view.id) })}>Remove</button>
          </div>
          <div className="quick-view-fields">{COLUMNS.filter((column) => column.key !== 'mix_position').map((column) => <label key={column.key}><input type="checkbox" checked={view.fields.includes(column.key)} onChange={(event) => updateQuickView(view.id, { fields: event.target.checked ? [...view.fields, column.key] : view.fields.filter((field) => field !== column.key) })} />{column.label}</label>)}</div>
        </article>)}</div> : <p>No Quick Views configured yet.</p>}
      </section>
      <section className="settings-card quick-view-settings"><div className="settings-card-heading"><div><h2>My Mixes Quick Views</h2><p>Named field sets used only by the My Mixes overview table.</p></div><button type="button" onClick={addMixQuickView}>Add Quick View</button></div>
        {draft.mix_quick_views.length ? <div className="quick-view-list">{draft.mix_quick_views.map((view) => <article className="quick-view-editor" key={view.id}>
          <div className="quick-view-head">
            <label>Name<input value={view.name} onChange={(event) => updateMixQuickView(view.id, { name: event.target.value })} /></label>
            <label className="toggle-row"><input type="radio" name="default-mix-quick-view" checked={Boolean(view.default)} onChange={() => makeMixDefault(view.id)} />Default</label>
            <button type="button" className="danger" onClick={() => setDraft({ ...draft, mix_quick_views: draft.mix_quick_views.filter((item) => item.id !== view.id) })}>Remove</button>
          </div>
          <div className="quick-view-fields">{MIX_FIELD_OPTIONS.map(([field, label]) => <label key={field}><input type="checkbox" checked={view.fields.includes(field)} onChange={(event) => updateMixQuickView(view.id, { fields: event.target.checked ? [...view.fields, field] : view.fields.filter((item) => item !== field) })} />{label}</label>)}</div>
        </article>)}</div> : <p>No My Mixes Quick Views configured yet.</p>}
      </section>
      <section className="settings-card orphaned-track-settings">
        <div className="settings-card-heading"><div><h2>Orphaned tracks</h2><p>TIDAL tracks that are no longer in Liked tracks, an indexed playlist, My Mixes, or a watched mix.</p></div><button type="button" className="danger" disabled={!orphaned.data?.total || clearOrphaned.isPending} onClick={confirmClearOrphaned}>{clearOrphaned.isPending ? 'Clearing...' : 'Clear orphaned tracks'}</button></div>
        {orphaned.isLoading ? <p>Checking the local library...</p> : orphaned.isError ? <div className="error-banner">{orphaned.error.message}</div> : orphaned.data?.total ? <>
          <p>{orphaned.data.total} orphaned track{orphaned.data.total === 1 ? '' : 's'}. Removing them also removes their local ratings and tags; it never changes TIDAL.</p>
          <div className="orphaned-track-table-wrap"><table className="orphaned-track-table"><thead><tr><th>Title</th><th>Artist</th><th>Album</th><th>Rating</th><th>Tags</th><th>Last.fm plays</th><th>Action</th></tr></thead><tbody>{orphaned.data.items.map((track) => <tr key={track.id}><td>{track.title || EMPTY_CELL}</td><td>{track.artist || EMPTY_CELL}</td><td>{track.album || EMPTY_CELL}</td><td>{track.rating || EMPTY_CELL}</td><td>{track.tag_count + track.dimension_count || EMPTY_CELL}</td><td>{track.lastfm_plays || EMPTY_CELL}</td><td><button type="button" className="danger compact-button" disabled={removeOrphaned.isPending} onClick={() => confirmRemoveOrphaned(track.id, track.title || 'Untitled track', track.artist || 'Unknown artist')}>{removingTrackId === track.id ? 'Removing...' : 'Remove'}</button></td></tr>)}</tbody></table></div>
          {orphaned.data.has_more ? <p className="muted">Showing the first {orphaned.data.items.length} tracks.</p> : null}
        </> : <p className="good">No orphaned tracks.</p>}
        {clearOrphaned.isSuccess ? <p className="good">Removed {clearOrphaned.data.deleted_tracks} local tracks and reset {clearOrphaned.data.cleared_lastfm_matches} Last.fm matches.</p> : null}
        {clearOrphaned.isError ? <div className="error-banner">{clearOrphaned.error.message}</div> : null}
        {removeOrphaned.isError ? <div className="error-banner">{removeOrphaned.error.message}</div> : null}
      </section>
    </div>
    {save.isError ? <div className="error-banner">{save.error.message}</div> : null}
  </section>
}
