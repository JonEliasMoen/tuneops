import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Job, PublicSettings, YouTubeStatus } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'
import { COLUMNS, DEFAULT_FIELDS } from '../track-browser/columns'
import { DEFAULT_MIX_FIELDS, MIX_FIELD_OPTIONS } from '../mixes/mixOverview'

export function SettingsPage() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const youtube = useQuery({ queryKey: ['youtube-status'], queryFn: () => api<YouTubeStatus>('/youtube/status') })
  const [draft, setDraft] = useState<PublicSettings | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  useEffect(() => { if (settings.data) setDraft(settings.data) }, [settings.data])
  const save = useMutation({
    mutationFn: (value: PublicSettings) => api<PublicSettings>('/settings', { method: 'PATCH', body: JSON.stringify(value) }),
    onSuccess: (value) => { client.setQueryData(['settings'], value); setDraft(value); void client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  const startJob = useMutation({
    mutationFn: (path: string) => api<Job>(path, { method: 'POST' }),
    onSuccess: (job) => setJobId(job.id),
  })
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
  if (!draft) return <p>Loading settings…</p>
  return <section className="settings-page">
    <header><h1>Settings</h1><p>These preferences are stored by the Python backend. Provider credentials never enter React.</p></header>
    <div className="settings-grid">
      <section className="settings-card"><h2>Appearance</h2>
        <label className="toggle-row"><input type="checkbox" checked={draft.dark_mode} onChange={(event) => setDraft({ ...draft, dark_mode: event.target.checked })} />Dark mode</label>
        <label className="toggle-row"><input type="checkbox" checked={draft.tags_collapsed_by_default} onChange={(event) => setDraft({ ...draft, tags_collapsed_by_default: event.target.checked })} />Tags collapsed by default</label>
      </section>
      <section className="settings-card"><h2>Local Qwen tagging</h2>
        <label>Ollama model<input value={draft.ollama_model} onChange={(event) => setDraft({ ...draft, ollama_model: event.target.value })} /></label>
        <label>Ollama URL<input value={draft.ollama_url} onChange={(event) => setDraft({ ...draft, ollama_url: event.target.value })} /></label>
      </section>
      <section className="settings-card"><h2>Last.fm</h2>
        <label>Username<input value={draft.lastfm_username} onChange={(event) => setDraft({ ...draft, lastfm_username: event.target.value })} /></label>
        <label>Top tracks per month<input type="number" min="1" max="100" value={draft.history_top_tracks} onChange={(event) => setDraft({ ...draft, history_top_tracks: Number(event.target.value) })} /></label>
        <p className={draft.lastfm_api_key_configured ? 'good' : 'warning'}>{draft.lastfm_api_key_configured ? 'API key configured in .env' : 'LASTFM_API_KEY is missing from .env'}</p>
        <div className="button-row"><button type="button" onClick={() => startJob.mutate('/lastfm/import')}>Import plays</button><button type="button" onClick={() => startJob.mutate('/lastfm/reconcile')}>Reconcile cached plays</button></div>
        <JobStatus jobId={jobId} />
      </section>
      <section className="settings-card"><h2>YouTube Analytics</h2>
        <p>Connect the Google account that owns your My Mixes videos. Credentials and tokens stay in the Python backend.</p>
        {!youtube.data ? <p>Checking connection…</p> : !youtube.data.configured ? <p className="warning">Google OAuth credentials or the redirect URI are missing from .env.</p> : youtube.data.connected ? <><p className="good">YouTube is connected.</p><a className="button-link" href="/api/v1/youtube/connect">Reconnect YouTube</a></> : <a className="button-link primary" href="/api/v1/youtube/connect">Connect YouTube</a>}
      </section>
      <section className="settings-card"><h2>Spotify matching</h2>
        <label>Search delay (seconds)<input type="number" min="0" step="0.05" value={draft.spotify_search_delay_seconds} onChange={(event) => setDraft({ ...draft, spotify_search_delay_seconds: Number(event.target.value) })} /></label>
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
    </div>
    {save.isError ? <div className="error-banner">{save.error.message}</div> : null}
    <button type="button" className="primary save-settings" disabled={save.isPending} onClick={() => save.mutate(draft)}>{save.isPending ? 'Saving…' : 'Save settings'}</button>
  </section>
}
