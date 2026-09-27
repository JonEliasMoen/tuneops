import { useEffect, useLayoutEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { Job } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'
import { TrackBrowser } from '../track-browser/TrackBrowser'
import { MixStopwatch } from '../track-browser/MixStopwatch'
import { loadTemporaryState, saveTemporaryState } from './watchedMixState'

type Mix = { folder_name: string; youtube_url: string; tidal_url: string; tidal_playlist_name: string; cover_url: string; youtube_title?: string; youtube_channel?: string; youtube_views?: number | null; youtube_upload_date?: string; youtube_metadata_error?: string }
type WatchedMix = { video_id: string; title: string; channel_name: string; upload_date: string; youtube_url: string; cover_url?: string; live_title?: string; live_channel_name?: string; live_view_count?: number | null; live_upload_date?: string; live_metadata_error?: string }
type Candidate = Record<string, unknown> & { id: string; label: string; score: number }
type Pending = { id: number; artist: string; title: string; mix_position: string; mix_title: string; channel_name: string; status: string; candidates: Candidate[] }
type StagingRow = { row_id: number; raw_line: string; timestamp: string; artist: string; title: string; status: string; matches: Candidate[]; selected_id: string }

export function MixesPage() {
  const mixes = useQuery({ queryKey: ['mixes'], queryFn: () => api<Mix[]>('/mixes') })
  return <section><h1>My mixes</h1><p>Local mixes discovered from your DJ folder.</p><div className="media-grid">{mixes.data?.map((mix) => <Link className="media-card" to={`/mixes/${encodeURIComponent(mix.folder_name)}`} key={mix.folder_name}>{mix.cover_url ? <img src={mix.cover_url} alt="" /> : <div className="cover-placeholder">♪</div>}<div><h2>{mix.folder_name}</h2><p>{mix.tidal_playlist_name || 'No TIDAL setlist imported'}</p></div></Link>)}</div></section>
}

export function MixDetailPage() {
  const { id = '' } = useParams()
  const folderName = decodeURIComponent(id)
  const mix = useQuery({ queryKey: ['mix', folderName], queryFn: () => api<Mix>(`/mixes/${encodeURIComponent(folderName)}`) })
  const client = useQueryClient()
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [tidalUrl, setTidalUrl] = useState('')
  const [importJobId, setImportJobId] = useState<string | null>(null)
  const [importError, setImportError] = useState('')
  useEffect(() => { if (mix.data) { setYoutubeUrl(mix.data.youtube_url); setTidalUrl(mix.data.tidal_url) } }, [mix.data?.youtube_url, mix.data?.tidal_url])
  const saveUrls = useMutation({ mutationFn: () => api<Mix>(`/mixes/${encodeURIComponent(folderName)}/urls`, { method: 'PUT', body: JSON.stringify({ youtube_url: youtubeUrl, tidal_url: tidalUrl }) }), onSuccess: (saved) => { client.setQueryData(['mix', folderName], saved); void client.invalidateQueries({ queryKey: ['mixes'] }) } })
  const importTidal = useMutation({
    mutationFn: () => api<Job>(`/mixes/${encodeURIComponent(folderName)}/import-tidal`, { method: 'POST', body: JSON.stringify({ tidal_url: tidalUrl }) }),
    onSuccess: (job) => { setImportError(''); setImportJobId(job.id) },
  })
  return <div>
    {mix.data ? <section className="watched-mix-header mix-detail-header">
      {mix.data.cover_url ? <img src={mix.data.cover_url} alt="" /> : null}
      <div><p className="eyebrow">My mix</p><h1>{mix.data.folder_name}{mix.data.youtube_title ? <span className="mix-youtube-heading">{mix.data.youtube_title}</span> : null}</h1>{[mix.data.youtube_channel, mix.data.youtube_views !== null && mix.data.youtube_views !== undefined ? `${mix.data.youtube_views.toLocaleString()} views` : '', mix.data.youtube_upload_date ? `Uploaded ${mix.data.youtube_upload_date}` : ''].some(Boolean) ? <p className="mix-youtube-facts">{[mix.data.youtube_channel, mix.data.youtube_views !== null && mix.data.youtube_views !== undefined ? `${mix.data.youtube_views.toLocaleString()} views` : '', mix.data.youtube_upload_date ? `Uploaded ${mix.data.youtube_upload_date}` : ''].filter(Boolean).join(' · ')}</p> : null}{mix.data.tidal_playlist_name ? <p className="good">TIDAL setlist: {mix.data.tidal_playlist_name}</p> : null}<div className="event-media-fields"><label>YouTube URL<input value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} /></label><label>TIDAL playlist URL<input value={tidalUrl} onChange={(event) => setTidalUrl(event.target.value)} /></label><div className="button-row"><button className="primary" type="button" onClick={() => saveUrls.mutate()} disabled={saveUrls.isPending}>Save URLs</button><button type="button" onClick={() => importTidal.mutate()} disabled={!tidalUrl.trim() || importTidal.isPending}>Sync playlist</button>{saveUrls.isError || importTidal.isError ? <span className="warning">{saveUrls.error?.message || importTidal.error?.message}</span> : null}</div><JobStatus jobId={importJobId} onComplete={() => { setImportJobId(null); void client.invalidateQueries({ queryKey: ['mix', folderName] }); void client.invalidateQueries({ queryKey: ['tracks', 'setlist', folderName] }) }} onFailed={(message) => { setImportJobId(null); setImportError(message) }} />{importError ? <p className="warning">{importError}</p> : null}</div></div>
    </section> : null}
    <TrackBrowser collectionType="setlist" collectionId={folderName} />
  </div>
}

export function WatchedMixesPage() {
  const client = useQueryClient()
  const mixes = useQuery({ queryKey: ['watched-mixes'], queryFn: () => api<WatchedMix[]>('/watched-mixes') })
  const [url, setUrl] = useState('')
  const add = useMutation({
    mutationFn: () => api<WatchedMix>('/watched-mixes', { method: 'POST', body: JSON.stringify({ youtube_url: url }) }),
    onSuccess: () => { setUrl(''); client.invalidateQueries({ queryKey: ['watched-mixes'] }); client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  return <section><h1>Watched mixes</h1><p>Save mixes where you discovered tracks.</p>
    <form className="add-mix" onSubmit={(event) => { event.preventDefault(); add.mutate() }}><label>YouTube mix URL<input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://youtube.com/watch?v=…" /></label><button className="primary" disabled={!url || add.isPending}>Add mix</button></form>
    {add.isError ? <div className="error-banner">{add.error.message}</div> : null}
    <div className="media-grid">{mixes.data?.map((mix) => <Link className="media-card" to={`/watched-mixes/${encodeURIComponent(mix.video_id)}`} key={mix.video_id}><img src={mix.cover_url || `/api/v1/watched-mixes/${encodeURIComponent(mix.video_id)}/cover`} alt="" /><div><h2>{mix.title || 'Untitled watched mix'}</h2><p>{[mix.channel_name, mix.upload_date].filter(Boolean).join(' · ')}</p></div></Link>)}</div>
  </section>
}

export function PendingPage() {
  const client = useQueryClient()
  const pending = useQuery({ queryKey: ['pending-tracks'], queryFn: () => api<Pending[]>('/pending-tracks') })
  const [jobId, setJobId] = useState<string | null>(null)
  const [recheckJobId, setRecheckJobId] = useState<string | null>(null)
  const [recheckError, setRecheckError] = useState('')
  const [selections, setSelections] = useState<Record<number, string>>({})
  const refresh = useMutation({ mutationFn: () => api<Job>('/pending-tracks/refresh', { method: 'POST' }), onSuccess: (job) => setJobId(job.id) })
  const recheck = useMutation({
    mutationFn: (id: number) => api<Job>(`/pending-tracks/${id}/refresh`, { method: 'POST' }),
    onSuccess: (job) => { setRecheckError(''); setRecheckJobId(job.id) },
    onError: (error) => setRecheckError(error.message),
  })
  const like = useMutation({
    mutationFn: ({ id, trackId }: { id: number; trackId: string }) => api(`/pending-tracks/${id}/like`, { method: 'POST', body: JSON.stringify({ track_id: trackId }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['pending-tracks'] }); void client.invalidateQueries({ queryKey: ['tracks'] }) },
  })
  const remove = useMutation({ mutationFn: (id: number) => api(`/pending-tracks/${id}`, { method: 'DELETE' }), onSuccess: () => void client.invalidateQueries({ queryKey: ['pending-tracks'] }) })
  return <section><header className="tool-heading"><div><h1>Pending tracks</h1><p>Unreleased or unresolved tracks saved from watched mixes.</p></div><button type="button" className="primary" onClick={() => refresh.mutate()} disabled={refresh.isPending}>Refresh from TIDAL</button></header>
    <JobStatus jobId={jobId} onComplete={() => { void client.invalidateQueries({ queryKey: ['pending-tracks'] }); setJobId(null) }} />
    <JobStatus jobId={recheckJobId} onComplete={() => { void client.invalidateQueries({ queryKey: ['pending-tracks'] }); setRecheckJobId(null) }} onFailed={(message) => { setRecheckError(message); setRecheckJobId(null) }} />
    {refresh.isError || recheckError || like.isError || remove.isError ? <div className="error-banner">{refresh.error?.message || recheckError || like.error?.message || remove.error?.message}</div> : null}
    <div className="pending-list">{pending.data?.map((track) => {
      const selectedId = selections[track.id] || String(track.candidates?.[0]?.id || '')
      const candidate = track.candidates.find((item) => String(item.id) === selectedId) ?? track.candidates[0]
      const score = Number(candidate?.score ?? 0)
      const confidence = !candidate ? 'Not found' : score >= 8 ? 'Strong match' : score >= 5 ? 'Possible match' : 'Weak match'
      return <article key={track.id}><span className="pending-position">{track.mix_position || '—'}</span><div><h2>{track.title}</h2><p>{track.artist} · {track.channel_name || track.mix_title}</p>{track.candidates?.length ? <select value={selectedId} onChange={(event) => setSelections((current) => ({ ...current, [track.id]: event.target.value }))}>{track.candidates.map((item) => <option key={String(item.id)} value={String(item.id)}>{item.label} ({Number(item.score ?? 0)}/10)</option>)}</select> : <small>No TIDAL candidate yet. Recheck when the track is released.</small>}</div><span className={`status-badge ${track.status}`}>{confidence}</span><div className="button-row"><button type="button" disabled={!selectedId || like.isPending} onClick={() => like.mutate({ id: track.id, trackId: selectedId })}>Like</button><button type="button" onClick={() => recheck.mutate(track.id)} disabled={recheck.isPending || Boolean(recheckJobId)}>Recheck TIDAL</button><button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate(track.id)}>Remove</button></div></article>
    })}</div>
  </section>
}

export function WatchedMixDetailPage() {
  const { id = '' } = useParams()
  const videoId = decodeURIComponent(id)
  const navigate = useNavigate()
  const client = useQueryClient()
  const mix = useQuery({ queryKey: ['watched-mix', videoId], queryFn: () => api<WatchedMix & { thumbnail_url: string }>(`/watched-mixes/${encodeURIComponent(videoId)}`) })
  const stagingKey = `musicsync.watched-mix-staging:${videoId}`
  const initialStaging = loadTemporaryState<{ rows: StagingRow[]; order: 'artist_title' | 'title_artist'; message: string }>(stagingKey, { rows: [], order: 'artist_title', message: '' })
  const [text, setText] = useState('')
  const [order, setOrder] = useState<'artist_title' | 'title_artist'>(initialStaging.order)
  const [rows, setRows] = useState<StagingRow[]>(initialStaging.rows)
  const [message, setMessage] = useState(initialStaging.message)
  const [loadedStagingKey, setLoadedStagingKey] = useState(stagingKey)
  const [activeStagingId, setActiveStagingId] = useState<string | null>(null)
  const [searchJobId, setSearchJobId] = useState<string | null>(null)
  const [thumbnailFailed, setThumbnailFailed] = useState(false)
  const [storedTitle, setStoredTitle] = useState('')
  const [storedChannel, setStoredChannel] = useState('')
  const [storedUploadDate, setStoredUploadDate] = useState('')
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [videoId])
  useEffect(() => {
    const restored = loadTemporaryState<{ rows: StagingRow[]; order: 'artist_title' | 'title_artist'; message: string }>(stagingKey, { rows: [], order: 'artist_title', message: '' })
    setRows(restored.rows)
    setOrder(restored.order)
    setMessage(restored.message)
    setLoadedStagingKey(stagingKey)
  }, [stagingKey])
  useEffect(() => {
    if (loadedStagingKey === stagingKey) saveTemporaryState(stagingKey, { rows, order, message })
  }, [loadedStagingKey, message, order, rows, stagingKey])
  useEffect(() => {
    if (!mix.data) return
    setStoredTitle(mix.data.title || '')
    setStoredChannel(mix.data.channel_name || '')
    setStoredUploadDate(mix.data.upload_date || '')
  }, [mix.data?.title, mix.data?.channel_name, mix.data?.upload_date])
  useEffect(() => setThumbnailFailed(false), [mix.data?.thumbnail_url])
  const updateMix = useMutation({
    mutationFn: () => api<WatchedMix>(`/watched-mixes/${encodeURIComponent(videoId)}`, { method: 'PATCH', body: JSON.stringify({ title: storedTitle, channel_name: storedChannel, upload_date: storedUploadDate }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['watched-mix', videoId] }); void client.invalidateQueries({ queryKey: ['watched-mixes'] }); void client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  const deleteMix = useMutation({
    mutationFn: () => api<void>(`/watched-mixes/${encodeURIComponent(videoId)}`, { method: 'DELETE' }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['watched-mixes'] }); void client.invalidateQueries({ queryKey: ['navigation'] }); navigate('/watched-mixes') },
  })
  const parse = useMutation({
    mutationFn: () => api<{ rows: StagingRow[]; searchable: number }>(`/watched-mixes/${encodeURIComponent(videoId)}/tracklist/parse`, { method: 'POST', body: JSON.stringify({ text, order }) }),
    onSuccess: (result) => { setRows(result.rows); setMessage(`Parsed ${result.rows.length} lines; ${result.searchable} ready to search.`) },
  })
  const startSearch = useMutation({
    mutationFn: () => api<Job>(`/watched-mixes/${encodeURIComponent(videoId)}/tracklist/search`, { method: 'POST', body: JSON.stringify({ rows }) }),
    onSuccess: (job) => setSearchJobId(job.id),
  })
  const searchJob = useQuery({
    queryKey: ['job', searchJobId],
    queryFn: () => api<Job>(`/jobs/${searchJobId}`),
    enabled: Boolean(searchJobId),
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.state ?? '') ? 750 : false,
  })
  useEffect(() => {
    const result = searchJob.data?.state === 'succeeded' ? searchJob.data.result as { rows?: StagingRow[]; searched?: number } : null
    if (!result?.rows) return
    setRows(result.rows)
    setMessage(`Searched ${result.searched ?? result.rows.length} tracks on TIDAL.`)
    setSearchJobId(null)
  }, [searchJob.data])
  useEffect(() => {
    if (searchJob.data?.state !== 'failed') return
    setMessage(searchJob.data.error || 'TIDAL search failed. You can try again.')
    setSearchJobId(null)
  }, [searchJob.data])

  const like = useMutation({
    mutationFn: ({ row, candidate }: { row: StagingRow; candidate: Candidate }) => api(`/watched-mixes/${encodeURIComponent(videoId)}/tracklist/like`, { method: 'POST', body: JSON.stringify({ candidate }) }).then(() => row.row_id),
    onSuccess: (rowId) => {
      setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, status: 'imported' } : row))
      setMessage('Liked on TIDAL, cached locally, and associated with this mix.')
      void client.invalidateQueries({ queryKey: ['tracks'] })
    },
  })
  const watch = useMutation({
    mutationFn: (row: StagingRow) => api<{ added: boolean }>(`/watched-mixes/${encodeURIComponent(videoId)}/tracklist/watch`, { method: 'POST', body: JSON.stringify({ artist: row.artist, title: row.title, timestamp: row.timestamp, raw_line: row.raw_line }) }).then((result) => ({ rowId: row.row_id, added: result.added })),
    onSuccess: ({ rowId, added }) => {
      setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, status: 'watching' } : row))
      setMessage(added ? 'Added to Pending tracks.' : 'That track is already pending.')
      void client.invalidateQueries({ queryKey: ['pending-tracks'] })
    },
  })

  function selectCandidate(rowId: number, selectedId: string) {
    setRows((current) => current.map((row) => row.row_id === rowId ? { ...row, selected_id: selectedId } : row))
  }

  const displayTitle = mix.data?.title || mix.data?.live_title || 'Untitled watched mix'
  const displayChannel = mix.data?.live_channel_name || mix.data?.channel_name
  const displayUploadDate = mix.data?.live_upload_date || mix.data?.upload_date
  return <div className="watched-mix-detail">
    <section className="watched-mix-header">
      {mix.data?.thumbnail_url && !thumbnailFailed ? <img src={mix.data.thumbnail_url} alt="" onError={() => setThumbnailFailed(true)} /> : <div className="cover-placeholder" aria-label="YouTube thumbnail unavailable">♪</div>}
      <div><p className="eyebrow">Watched mix</p><h1>{displayTitle}</h1><p>{[displayChannel, mix.data?.live_view_count !== null && mix.data?.live_view_count !== undefined ? `${mix.data.live_view_count.toLocaleString()} views` : '', displayUploadDate ? `Uploaded ${displayUploadDate}` : ''].filter(Boolean).join(' · ')}</p>{mix.data?.youtube_url ? <a className="button-link quiet-link" href={mix.data.youtube_url} target="_blank" rel="noreferrer">Open on YouTube</a> : null}{mix.data?.live_metadata_error ? <p className="warning">{mix.data.live_metadata_error}</p> : null}</div>
    </section>
    <details className="tracklist-import"><summary>Edit watched mix</summary><div className="event-media-fields"><label>Stored title<input value={storedTitle} onChange={(event) => setStoredTitle(event.target.value)} /></label><label>Stored channel<input value={storedChannel} onChange={(event) => setStoredChannel(event.target.value)} /></label><label>Upload date<input value={storedUploadDate} onChange={(event) => setStoredUploadDate(event.target.value)} placeholder="YYYY-MM-DD" /></label><div className="button-row"><button type="button" className="primary" onClick={() => updateMix.mutate()} disabled={updateMix.isPending}>Save details</button><button type="button" className="danger" onClick={() => { if (window.confirm('Delete this watched mix and its local track associations?')) deleteMix.mutate() }} disabled={deleteMix.isPending}>Delete watched mix</button></div>{updateMix.isError || deleteMix.isError ? <div className="error-banner">{updateMix.error?.message || deleteMix.error?.message}</div> : null}</div></details>
    <details className="tracklist-import" open>
      <summary>Import tracklist</summary>
      <p>Paste a temporary tracklist, inspect TIDAL candidates, then Like or Watch only the rows you want.</p>
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder={'00:00 Artist - Track\n05:24 Artist - Next track'} rows={8} />
      <div className="button-row"><select value={order} onChange={(event) => setOrder(event.target.value as typeof order)}><option value="artist_title">Artist — Title</option><option value="title_artist">Title — Artist</option></select><button type="button" onClick={() => parse.mutate()} disabled={!text.trim() || parse.isPending}>Parse</button><button type="button" className="primary" onClick={() => startSearch.mutate()} disabled={!rows.some((row) => !['invalid', 'unresolved'].includes(row.status)) || startSearch.isPending || (searchJob.data?.state === 'running' || searchJob.data?.state === 'queued')}>Search TIDAL</button></div>
      {message ? <p className="good">{message}</p> : null}
      {parse.isError || startSearch.isError || like.isError || watch.isError ? <div className="error-banner">{parse.error?.message || startSearch.error?.message || like.error?.message || watch.error?.message}</div> : null}
      <JobStatus jobId={searchJobId} />
      {rows.some((row) => Boolean(row.timestamp)) ? <MixStopwatch rows={rows.map((row) => ({ id: String(row.row_id), mix_position: row.timestamp }))} onActiveTrackChange={setActiveStagingId} storageKey={`musicsync.stopwatch:watched-staging:${videoId}`} /> : null}
      {rows.length ? <div className="staging-table-wrap"><table className="track-table staging-table"><thead><tr><th>Time</th><th>Artist</th><th>Title</th><th>TIDAL candidate</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rows.map((row) => {
        const candidate = row.matches.find((item) => String(item.id) === String(row.selected_id))
        return <tr key={row.row_id} className={activeStagingId === String(row.row_id) ? 'mix-current-track' : ''}><td>{row.timestamp || '—'}</td><td>{row.artist || '—'}</td><td>{row.title}</td><td>{row.matches.length ? <select value={row.selected_id} onChange={(event) => selectCandidate(row.row_id, event.target.value)}>{row.matches.map((item) => <option key={String(item.id)} value={String(item.id)}>{item.label}</option>)}</select> : '—'}</td><td><span className={`status-badge ${row.status}`}>{row.status}</span></td><td><div className="button-row"><button type="button" disabled={!candidate || row.status === 'imported' || like.isPending} onClick={() => candidate && like.mutate({ row, candidate })}>Like</button><button type="button" disabled={['invalid', 'unresolved', 'watching'].includes(row.status) || watch.isPending} onClick={() => watch.mutate(row)}>Watch</button></div></td></tr>
      })}</tbody></table></div> : null}
    </details>
    <TrackBrowser collectionType="watched_mix" collectionId={videoId} hideCollectionHeading />
  </div>
}
