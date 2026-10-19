import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Job } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'

type Mapping = Record<string, unknown> & {
  enabled?: boolean; name?: string; direction?: string; collection_type?: string; spotify?: string; tidal?: string; tidal_name?: string
}
type PlaylistChoice = { id: string; name: string; url: string }
type SaveState = 'loading' | 'saved' | 'dirty' | 'saving' | 'error'

function newMapping(): Mapping {
  const id = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `mapping-${Date.now()}`
  return { _mapping_id: id, enabled: true, name: '', direction: 'spotify_to_tidal', collection_type: 'playlist', spotify: '', tidal: '', tidal_name: '' }
}

function PlaylistPicker({ provider, value, choices, loading, error, onChange, onName }: { provider: 'spotify' | 'tidal'; value: string; choices: PlaylistChoice[]; loading: boolean; error?: string; onChange: (value: string) => void; onName: (name: string) => void }) {
  const [query, setQuery] = useState('')
  const label = provider === 'spotify' ? 'Spotify' : 'TIDAL'
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return needle ? choices.filter((choice) => choice.name.toLocaleLowerCase().includes(needle)) : choices
  }, [choices, query])
  return <div className="playlist-picker">
    <label>{label} playlist URL or ID<input value={value} onChange={(event) => onChange(event.target.value)} /></label>
    <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Filter ${label} playlists`} aria-label={`Filter ${label} playlists`} disabled={loading || Boolean(error)} />
    {error ? <span className="warning">{error}</span> : null}
    <select value="" aria-label={`${label} playlist results`} disabled={loading || Boolean(error) || !filtered.length} onChange={(event) => {
      const choice = choices.find((item) => item.id === event.target.value)
      if (!choice) return
      onChange(choice.url || choice.id)
      onName(choice.name)
    }}><option value="" disabled>{loading ? `Loading ${label} playlists…` : filtered.length ? `Select from ${filtered.length} playlists…` : 'No matching playlists'}</option>{filtered.map((choice) => <option value={choice.id} key={choice.id}>{choice.name}</option>)}</select>
  </div>
}

export function PlaylistSyncPage() {
  const client = useQueryClient()
  const mappings = useQuery({ queryKey: ['sync-mappings'], queryFn: () => api<{ playlists: Mapping[] }>('/sync/mappings') })
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ providers: Record<string, { connected: boolean; label: string }> }>('/health') })
  const spotifyPlaylists = useQuery({ queryKey: ['sync-playlists', 'spotify'], queryFn: () => api<PlaylistChoice[]>('/sync/playlists?provider=spotify'), staleTime: Infinity, gcTime: Infinity, retry: false })
  const tidalPlaylists = useQuery({ queryKey: ['sync-playlists', 'tidal'], queryFn: () => api<PlaylistChoice[]>('/sync/playlists?provider=tidal'), staleTime: Infinity, gcTime: Infinity, retry: false })
  const [rows, setRows] = useState<Mapping[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('loading')
  const rowsRef = useRef<Mapping[]>([])
  const hydrated = useRef(false)
  const lastSaved = useRef('')
  const failedSnapshot = useRef('')
  useEffect(() => { rowsRef.current = rows }, [rows])
  useEffect(() => {
    if (!mappings.data || hydrated.current) return
    const initialRows = mappings.data.playlists
    rowsRef.current = initialRows
    lastSaved.current = JSON.stringify(initialRows)
    hydrated.current = true
    setRows(initialRows)
    setSaveState('saved')
  }, [mappings.data])
  const save = useMutation({
    mutationFn: ({ snapshot }: { snapshot: Mapping[]; serialized: string }) => api<{ playlists: Mapping[] }>('/sync/mappings', { method: 'PUT', body: JSON.stringify({ playlists: snapshot }) }),
    retry: 2,
    onMutate: () => setSaveState('saving'),
    onSuccess: (data, variables) => {
      const persisted = JSON.stringify(data.playlists)
      lastSaved.current = persisted
      failedSnapshot.current = ''
      client.setQueryData(['sync-mappings'], data)
      if (JSON.stringify(rowsRef.current) === variables.serialized) {
        rowsRef.current = data.playlists
        setRows(data.playlists)
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
    if (!hydrated.current || save.isPending) return
    const serialized = JSON.stringify(rows)
    if (serialized === lastSaved.current) {
      if (saveState !== 'saved') setSaveState('saved')
      return
    }
    if (serialized === failedSnapshot.current) return
    setSaveState('dirty')
    const timer = window.setTimeout(() => save.mutate({ snapshot: rows, serialized }), 650)
    return () => window.clearTimeout(timer)
  }, [rows, save.isPending])
  const sync = useMutation({ mutationFn: () => api<Job>('/sync/run', { method: 'POST' }), onSuccess: (job) => setJobId(job.id) })
  function update(index: number, changes: Partial<Mapping>) { setRows((current) => current.map((row, position) => position === index ? { ...row, ...changes } : row)) }
  function retrySave() {
    const snapshot = rowsRef.current
    const serialized = JSON.stringify(snapshot)
    failedSnapshot.current = ''
    save.mutate({ snapshot, serialized })
  }
  return <section className="sync-page"><header><h1>Spotify ↔ TIDAL</h1><p>Existing backend credentials and session caches are reused unchanged.</p></header>
    <div className="connections">{Object.entries(health.data?.providers ?? {}).map(([provider, value]) => <span className={`connection ${value.connected ? 'connected' : 'disconnected'}`} key={provider}>{value.connected ? '●' : '○'} {provider} {value.label || (value.connected ? 'credentials saved' : 'not connected')}</span>)}</div>
    <p className="muted">Playlists: Spotify {spotifyPlaylists.isLoading ? 'loading…' : spotifyPlaylists.data ? `${spotifyPlaylists.data.length} loaded` : 'unavailable'} · TIDAL {tidalPlaylists.isLoading ? 'loading…' : tidalPlaylists.data ? `${tidalPlaylists.data.length} loaded` : 'unavailable'}</p>
    <div className="button-row"><span className={`mapping-save-status ${saveState}`}>{saveState === 'loading' ? 'Loading mappings…' : saveState === 'saving' ? 'Saving changes…' : saveState === 'dirty' ? 'Changes pending…' : saveState === 'error' ? 'Autosave failed.' : 'Saved automatically.'}</span>{saveState === 'error' ? <button type="button" onClick={retrySave} disabled={save.isPending}>Retry save</button> : null}<button type="button" className="primary" disabled={sync.isPending || saveState !== 'saved'} onClick={() => sync.mutate()}>Sync now</button></div>
    <JobStatus jobId={jobId} onComplete={() => client.invalidateQueries({ queryKey: ['navigation'] })} />
    {save.isError ? <div className="error-banner">{save.error.message}</div> : null}
    <div className="button-row"><button type="button" onClick={() => setRows((current) => [newMapping(), ...current])}>Add mapping</button></div>
    <div className="mapping-list">{rows.map((row, index) => <article className="mapping-card" key={String(row._mapping_id ?? index)}>
      <div className="mapping-head"><label>Mapping name<input value={String(row.name ?? '')} onChange={(event) => update(index, { name: event.target.value })} /></label><button className="danger" type="button" onClick={() => setRows((current) => current.filter((_, position) => position !== index))}>Remove</button></div>
      <label className="toggle-row"><input type="checkbox" checked={row.enabled !== false} onChange={(event) => update(index, { enabled: event.target.checked })} />Enabled</label>
      <div className="form-grid">
        <label>Sync direction<select value={String(row.direction ?? 'spotify_to_tidal')} onChange={(event) => update(index, { direction: event.target.value })}><option value="spotify_to_tidal">Spotify → TIDAL</option><option value="tidal_to_spotify">TIDAL → Spotify</option><option value="tidal_cache">TIDAL cache</option></select></label>
        <label>Library section<select value={String(row.collection_type ?? 'playlist')} onChange={(event) => update(index, { collection_type: event.target.value })}><option value="playlist">Playlist</option><option value="event">Event</option><option value="source">Source</option></select></label>
        <PlaylistPicker provider="spotify" value={String(row.spotify ?? '')} choices={spotifyPlaylists.data ?? []} loading={spotifyPlaylists.isLoading} error={spotifyPlaylists.error?.message} onChange={(spotify) => update(index, { spotify })} onName={(name) => { if (!String(row.name ?? '').trim()) update(index, { name }) }} />
        <PlaylistPicker provider="tidal" value={String(row.tidal ?? '')} choices={tidalPlaylists.data ?? []} loading={tidalPlaylists.isLoading} error={tidalPlaylists.error?.message} onChange={(tidal) => update(index, { tidal })} onName={(name) => { if (!String(row.name ?? '').trim()) update(index, { name }) }} />
      </div>
      <label>Target name override<input placeholder="Use source playlist name" value={String(row.tidal_name ?? '')} onChange={(event) => update(index, { tidal_name: event.target.value })} /></label>
    </article>)}</div>
  </section>
}
