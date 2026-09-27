import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { Collection, Job, Track, TrackPage } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'
import { useTagsPanel } from './uiPreferences'

type Catalog = {
  values: Record<string, string[]>
  labels: Record<string, string>
  max_values: Record<string, number>
}

type PlaylistOption = { id: string; name: string; collection_type: 'playlist' | 'event' | 'source' }
type WatchedMix = { video_id: string; title: string; channel_name?: string }
type ActionMode = 'add' | 'remove' | 'move' | 'associate' | null

const memberRoutes: Array<[keyof Pick<Track, 'playlists' | 'events' | 'sources' | 'mixes' | 'djmi'>, string]> = [
  ['playlists', 'playlists'], ['events', 'events'], ['sources', 'sources'], ['mixes', 'mixes'], ['djmi', 'watched-mixes'],
]

export function Inspector({
  track,
  selectedTracks,
  queryKey,
  collapsedDefault,
  collectionType,
  collectionId,
}: {
  track: Track | null
  selectedTracks: Track[]
  queryKey: readonly unknown[]
  collapsedDefault: boolean
  collectionType: Collection['type']
  collectionId: string
}) {
  const client = useQueryClient()
  const actionsRef = useRef<HTMLElement>(null)
  const [tagsOpen, setTagsOpen] = useTagsPanel(collapsedDefault)
  const [mode, setMode] = useState<ActionMode>(null)
  const [feedback, setFeedback] = useState('')
  const [tagFeedback, setTagFeedback] = useState('')
  const [autoTagJob, setAutoTagJob] = useState<string | null>(null)
  const catalog = useQuery({ queryKey: ['dimensions'], queryFn: () => api<Catalog>('/dimensions') })
  const playlists = useQuery({ queryKey: ['playlist-options'], queryFn: () => api<PlaylistOption[]>('/playlist-options') })
  const watchedMixes = useQuery({ queryKey: ['watched-mixes'], queryFn: () => api<WatchedMix[]>('/watched-mixes') })

  useEffect(() => {
    setMode(null)
    setFeedback('')
  }, [track?.id])

  const toggle = useMutation({
    mutationFn: ({ dimension, value, enable }: { dimension: string; value: string; enable: boolean }) => api<{ updated: Record<string, Record<string, string[]>> }>('/tracks/dimensions/toggle', {
      method: 'POST',
      body: JSON.stringify({ track_ids: selectedTracks.map((item) => item.id), dimension, value, enable }),
    }),
    onMutate: async ({ dimension, value, enable }) => {
      setTagFeedback('')
      await client.cancelQueries({ queryKey })
      const previous = client.getQueriesData<InfiniteData<TrackPage>>({ queryKey })
      const wanted = new Set(selectedTracks.map((item) => item.id))
      const maximum = catalog.data?.max_values[dimension] ?? 999
      client.setQueriesData<InfiniteData<TrackPage>>({ queryKey }, (data) => data ? {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => {
            if (!wanted.has(item.id)) return item
            const current = item.dimensions?.[dimension] ?? []
            let values = current
            if (enable && !current.includes(value)) {
              values = maximum === 1 ? [value] : [...current.slice(Math.max(0, current.length - maximum + 1)), value]
            } else if (!enable) {
              values = current.filter((itemValue) => itemValue !== value)
            }
            return { ...item, dimensions: { ...item.dimensions, [dimension]: values } }
          }),
        })),
      } : data)
      return { previous }
    },
    onSuccess: ({ updated }) => client.setQueriesData<InfiniteData<TrackPage>>({ queryKey }, (data) => data ? {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((item) => updated[item.id] ? { ...item, dimensions: updated[item.id] } : item),
      })),
    } : data),
    onError: (error, _variables, context) => {
      context?.previous.forEach(([key, data]) => client.setQueryData(key, data))
      setTagFeedback(error.message || 'Could not save the tag. Your view was restored.')
    },
  })

  const action = useMutation({
    mutationFn: async ({ playlistId, watchedId }: { playlistId?: string; watchedId?: string }) => {
      const trackIds = selectedTracks.map((item) => item.id)
      if (mode === 'associate') {
        return api<{ added: number; selected: number }>('/tracks/associate-watched-mix', {
          method: 'POST', body: JSON.stringify({ track_ids: trackIds, video_id: watchedId }),
        }).then((result) => ({ message: `Associated ${result.added} new track${result.added === 1 ? '' : 's'} with the watched mix.` }))
      }
      return api<{ message: string }>('/tracks/playlist-action', {
        method: 'POST',
        body: JSON.stringify({
          action: mode,
          track_ids: trackIds,
          playlist_id: playlistId,
          source_playlist_id: mode === 'move' ? collectionId : null,
        }),
      })
    },
    onSuccess: async (result) => {
      setFeedback(result.message)
      setMode(null)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['tracks'] }),
        client.invalidateQueries({ queryKey: ['navigation'] }),
      ])
      document.querySelector<HTMLElement>('[data-track-browser-root]')?.focus()
    },
    onError: (error) => setFeedback(error.message),
  })
  const autoTag = useMutation({
    mutationFn: () => api<Job>('/tracks/auto-tag', {
      method: 'POST', body: JSON.stringify({ track_ids: selectedTracks.map((item) => item.id) }),
    }),
    onSuccess: (job) => {
      setFeedback('')
      setAutoTagJob(job.id)
    },
    onError: (error) => setFeedback(error.message),
  })
  const likeTracks = useMutation({
    mutationFn: () => api<{ message: string }>('/tracks/like', {
      method: 'POST', body: JSON.stringify({ track_ids: selectedTracks.map((item) => item.id) }),
    }),
    onSuccess: async (result) => {
      setFeedback(result.message)
      await client.invalidateQueries({ queryKey: ['tracks'] })
      document.querySelector<HTMLElement>('[data-track-browser-root]')?.focus({ preventScroll: true })
    },
    onError: (error) => setFeedback(error.message),
  })

  const destinationOptions = useMemo(() => {
    const all = playlists.data ?? []
    if (mode === 'add') return all
    if (mode === 'move') return all.filter((item) => item.id !== collectionId)
    if (mode === 'remove') {
      const ids = new Set(selectedTracks.flatMap((item) => [...item.playlists, ...item.events, ...item.sources].map((entry) => entry.id)))
      if (['playlist', 'event', 'source'].includes(collectionType)) ids.add(collectionId)
      return all.filter((item) => ids.has(item.id))
    }
    return []
  }, [collectionId, collectionType, mode, playlists.data, selectedTracks])

  useEffect(() => {
    if (mode === null) return
    const frame = requestAnimationFrame(() => {
      const panel = actionsRef.current
      const destination = panel?.querySelector<HTMLButtonElement>('button[data-action-entry]:not(.action-back):not(:disabled)')
      const fallback = panel?.querySelector<HTMLButtonElement>('button[data-action-entry]:not(:disabled)')
      ;(destination ?? fallback)?.focus()
    })
    return () => cancelAnimationFrame(frame)
  }, [mode, destinationOptions.length])

  function actionKeys(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      event.stopPropagation()
      setMode(null)
      document.querySelector<HTMLElement>('[data-track-browser-root]')?.focus({ preventScroll: true })
      return
    }
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button[data-action-entry]:not(:disabled)'))
    if (!buttons.length) return
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      buttons[(index < 0 ? 0 : (index + delta + buttons.length) % buttons.length)].focus()
    } else if (event.key === 'Enter' && index < 0) {
      event.preventDefault()
      buttons[0].focus()
    }
  }

  if (!track) return <aside className="inspector"><div className="empty-inspector">Select a track</div></aside>
  const allMemberships = memberRoutes.flatMap(([key, route]) => (track[key] ?? []).map((item) => ({ ...item, route })))
  const count = selectedTracks.length || 1
  return <aside className="inspector" id="track-inspector">
    <section className="selected-track-panel">
      {track.album_art_url ? <img src={track.album_art_url} alt="" className="album-art" /> : null}
      <div className="eyebrow">{count > 1 ? `${count} tracks selected` : 'Selected track'}</div>
      <h2>{track.title}</h2>
      <p className="selected-artist">{track.artist}</p>
      {allMemberships.length ? <div className="inspector-memberships">{allMemberships.map((item) => <Link key={`${item.route}:${item.id}`} to={`/${item.route}/${encodeURIComponent(item.id)}`} className="membership-pill">{item.name}</Link>)}</div> : null}
      {track.play_count ? <p className="listening-stat">Played {track.play_count.toLocaleString()} times{track.last_played ? ` · last ${track.last_played}` : ''}</p> : null}
      <a className="tidal-native" href={track.tidal_uri}>Play in TIDAL</a>
      {tagFeedback ? <p className="action-feedback error">{tagFeedback}</p> : null}
      <details className="tags-panel" open={tagsOpen} onToggle={(event) => setTagsOpen(event.currentTarget.open)}>
        <summary>Tags & ratings</summary>
        {Object.entries(catalog.data?.values ?? {}).map(([dimension, values]) => <div className="dimension" key={dimension}>
          <strong>{catalog.data?.labels[dimension] ?? dimension}</strong>
          <div className="dimension-options">{values.map((value) => {
            const selected = (track.dimensions?.[dimension] ?? []).includes(value)
            return <button
              type="button"
              key={value}
              className={selected ? 'selected' : ''}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate({ dimension, value, enable: !selected })}
            >{dimension === 'rating' ? `${'★'.repeat(Number(value))}` : value}</button>
          })}</div>
        </div>)}
      </details>
    </section>
    <section
      ref={actionsRef}
      className="actions-panel"
      id="track-actions"
      tabIndex={0}
      onKeyDown={actionKeys}
      onFocus={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.querySelector<HTMLButtonElement>('button[data-action-entry]')?.focus()
      }}
    >
      <h2>Actions</h2>
      {feedback ? <p className={action.isError ? 'action-feedback error' : 'action-feedback'}>{feedback}</p> : null}
      {mode === null ? <div className="action-list">
        <button data-action-entry type="button" disabled={likeTracks.isPending} onClick={() => { setFeedback(''); likeTracks.mutate() }}>Like in TIDAL</button>
        <button data-action-entry type="button" onClick={() => { setFeedback(''); setMode('add') }}>Add to playlist</button>
        <button data-action-entry type="button" onClick={() => { setFeedback(''); setMode('remove') }}>Remove from playlist</button>
        {collectionType === 'playlist' ? <button data-action-entry type="button" onClick={() => { setFeedback(''); setMode('move') }}>Move to playlist</button> : null}
        <button data-action-entry type="button" onClick={() => { setFeedback(''); setMode('associate') }}>Associate with watched mix</button>
        <button data-action-entry type="button" disabled={autoTag.isPending || Boolean(autoTagJob)} onClick={() => autoTag.mutate()}>Auto tag with Qwen3</button>
        <JobStatus jobId={autoTagJob} onComplete={() => { client.invalidateQueries({ queryKey: ['tracks'] }); setAutoTagJob(null); setFeedback('Auto tagging complete.') }} onFailed={(message) => { setAutoTagJob(null); setFeedback(message) }} />
      </div> : <div className="action-list">
        <button data-action-entry type="button" className="action-back" onClick={() => setMode(null)}>← Back</button>
        <p className="action-prompt">{mode === 'associate' ? `Choose a watched mix for ${count} track${count === 1 ? '' : 's'}` : `${mode === 'add' ? 'Add to' : mode === 'remove' ? 'Remove from' : 'Move to'}…`}</p>
        {mode === 'associate'
          ? (watchedMixes.data ?? []).map((item) => <button data-action-entry type="button" key={item.video_id} disabled={action.isPending} onClick={() => action.mutate({ watchedId: item.video_id })}>{item.title || item.video_id}</button>)
          : (['playlist', 'event', 'source'] as const).map((kind) => {
              const group = destinationOptions.filter((item) => item.collection_type === kind)
              return group.length ? <div className="action-group" key={kind}><strong>{kind === 'playlist' ? 'Playlists' : kind === 'event' ? 'Events' : 'Sources'}</strong>{group.map((item) => <button data-action-entry type="button" key={item.id} disabled={action.isPending} onClick={() => action.mutate({ playlistId: item.id })}>{item.name}</button>)}</div> : null
            })}
        {!action.isPending && (mode === 'associate' ? !(watchedMixes.data ?? []).length : !destinationOptions.length) ? <p className="detail-empty">No available destinations.</p> : null}
        {action.isPending ? <p className="action-prompt">Updating TIDAL and SQLite…</p> : null}
      </div>}
    </section>
  </aside>
}
