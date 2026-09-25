import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Job } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'

type Mapping = Record<string, unknown> & {
  enabled?: boolean; name?: string; direction?: string; collection_type?: string; spotify?: string; tidal?: string; tidal_name?: string
}

export function PlaylistSyncPage() {
  const client = useQueryClient()
  const mappings = useQuery({ queryKey: ['sync-mappings'], queryFn: () => api<{ playlists: Mapping[] }>('/sync/mappings') })
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ providers: Record<string, { connected: boolean; label: string }> }>('/health') })
  const [rows, setRows] = useState<Mapping[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  useEffect(() => { if (mappings.data) setRows(mappings.data.playlists) }, [mappings.data])
  const save = useMutation({
    mutationFn: () => api<{ playlists: Mapping[] }>('/sync/mappings', { method: 'PUT', body: JSON.stringify({ playlists: rows }) }),
    onSuccess: (data) => { setRows(data.playlists); client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  const sync = useMutation({ mutationFn: () => api<Job>('/sync/run', { method: 'POST' }), onSuccess: (job) => setJobId(job.id) })
  function update(index: number, changes: Partial<Mapping>) { setRows((current) => current.map((row, position) => position === index ? { ...row, ...changes } : row)) }
  return <section className="sync-page"><header><h1>Spotify ↔ TIDAL</h1><p>Existing backend credentials and session caches are reused unchanged.</p></header>
    <div className="connections">{Object.entries(health.data?.providers ?? {}).map(([provider, value]) => <span className={`connection ${value.connected ? 'connected' : 'disconnected'}`} key={provider}>{value.connected ? '●' : '○'} {provider} {value.label || (value.connected ? 'credentials saved' : 'not connected')}</span>)}</div>
    <div className="button-row"><button type="button" className="primary" disabled={save.isPending} onClick={() => save.mutate()}>Save mappings</button><button type="button" disabled={sync.isPending} onClick={() => sync.mutate()}>Sync now</button></div>
    <JobStatus jobId={jobId} onComplete={() => client.invalidateQueries({ queryKey: ['navigation'] })} />
    {save.isError ? <div className="error-banner">{save.error.message}</div> : null}
    <div className="mapping-list">{rows.map((row, index) => <article className="mapping-card" key={index}>
      <div className="mapping-head"><label>Mapping name<input value={String(row.name ?? '')} onChange={(event) => update(index, { name: event.target.value })} /></label><button className="danger" type="button" onClick={() => setRows((current) => current.filter((_, position) => position !== index))}>Remove</button></div>
      <label className="toggle-row"><input type="checkbox" checked={row.enabled !== false} onChange={(event) => update(index, { enabled: event.target.checked })} />Enabled</label>
      <div className="form-grid">
        <label>Sync direction<select value={String(row.direction ?? 'spotify_to_tidal')} onChange={(event) => update(index, { direction: event.target.value })}><option value="spotify_to_tidal">Spotify → TIDAL</option><option value="tidal_to_spotify">TIDAL → Spotify</option><option value="tidal_cache">TIDAL cache</option></select></label>
        <label>Library section<select value={String(row.collection_type ?? 'playlist')} onChange={(event) => update(index, { collection_type: event.target.value })}><option value="playlist">Playlist</option><option value="event">Event</option><option value="source">Source</option></select></label>
        <label>Spotify playlist URL or ID<input value={String(row.spotify ?? '')} onChange={(event) => update(index, { spotify: event.target.value })} /></label>
        <label>TIDAL playlist URL or ID<input value={String(row.tidal ?? '')} onChange={(event) => update(index, { tidal: event.target.value })} /></label>
      </div>
      <label>Target name override<input placeholder="Use source playlist name" value={String(row.tidal_name ?? '')} onChange={(event) => update(index, { tidal_name: event.target.value })} /></label>
    </article>)}</div>
    <button type="button" onClick={() => setRows((current) => [...current, { enabled: true, name: '', direction: 'spotify_to_tidal', collection_type: 'playlist', spotify: '', tidal: '', tidal_name: '' }])}>Add mapping</button>
  </section>
}
