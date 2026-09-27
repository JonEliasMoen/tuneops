import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, queryString } from '../../api/client'
import type { Job, PublicSettings, Track, TrackPage } from '../../api/types'
import { JobStatus } from '../../components/JobStatus'
import { COLUMNS, DEFAULT_FIELDS } from './columns'
import { Inspector } from './Inspector'
import { MixStopwatch } from './MixStopwatch'
import { EventMedia } from './EventMedia'
import { loadBrowserState, saveBrowserState, type BrowserFilters, type SortState } from './viewState'

const PAGE_SIZE = 200
const checkedCollections = new Set<string>()
const CAMELOT_KEYS = Array.from({ length: 12 }, (_, index) => [`${String(index + 1).padStart(2, '0')}A`, `${String(index + 1).padStart(2, '0')}B`]).flat()
type DimensionCatalog = { values: Record<string, string[]>; labels: Record<string, string> }

function isEditing(target: EventTarget | null) {
  return Boolean((target as HTMLElement | null)?.closest('input, textarea, select, button, a, summary, [contenteditable="true"]'))
}

export function keepRowVisible(viewport: HTMLElement, row: HTMLElement) {
  const viewportRect = viewport.getBoundingClientRect()
  const rowRect = row.getBoundingClientRect()
  if (rowRect.top < viewportRect.top) {
    viewport.scrollTop -= viewportRect.top - rowRect.top
  } else if (rowRect.bottom > viewportRect.bottom) {
    viewport.scrollTop += rowRect.bottom - viewportRect.bottom
  }
}

export function TrackBrowser({ collectionType, collectionId, hideCollectionHeading = false }: {
  collectionType: TrackPage['collection']['type']
  collectionId: string
  hideCollectionHeading?: boolean
}) {
  const collectionKey = `${collectionType}:${collectionId}`
  const queryClient = useQueryClient()
  const browserRootRef = useRef<HTMLElement>(null)
  const tableRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const pendingScroll = useRef<number | null>(null)
  const focusTracksOnLoad = useRef(false)
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const dimensions = useQuery({ queryKey: ['dimensions'], queryFn: () => api<DimensionCatalog>('/dimensions') })
  const [initializedKey, setInitializedKey] = useState('')
  const [sort, setSort] = useState<SortState>(null)
  const [visibleFields, setVisibleFields] = useState<string[]>(DEFAULT_FIELDS)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [anchorId, setAnchorId] = useState<string | null>(null)
  const [lastRangeIndex, setLastRangeIndex] = useState<number | null>(null)
  const [loaded, setLoaded] = useState(PAGE_SIZE)
  const [fieldsOpen, setFieldsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [artist, setArtist] = useState('')
  const [keyFilter, setKeyFilter] = useState('')
  const [rating, setRating] = useState('')
  const [tag, setTag] = useState('')
  const [collectionFilter, setCollectionFilter] = useState('')
  const [bpmMin, setBpmMin] = useState('')
  const [bpmMax, setBpmMax] = useState('')
  const [refreshJobId, setRefreshJobId] = useState<string | null>(null)
  const [refreshError, setRefreshError] = useState('')
  const [activeTrackId, setActiveTrackId] = useState<string | null>(null)
  const providerBacked = collectionType === 'liked' || collectionType === 'playlist' || collectionType === 'event' || collectionType === 'source'

  useEffect(() => {
    if (settings.isPending) return
    const defaultFields = settings.data?.quick_views.find((view) => view.default)?.fields ?? DEFAULT_FIELDS
    const restored = loadBrowserState(collectionKey, {
      sort: null,
      visibleFields: defaultFields,
      selectedId: null,
      scrollTop: 0,
      loaded: PAGE_SIZE,
      filters: { query: '', artist: '', key: '', rating: '', tag: '', collectionType: '', bpmMin: '', bpmMax: '' },
    })
    setSort(restored.sort)
    setVisibleFields(restored.visibleFields?.length ? restored.visibleFields : defaultFields)
    setAnchorId(restored.selectedId)
    setSelectedIds(restored.selectedId ? new Set([restored.selectedId]) : new Set())
    setLoaded(restored.loaded)
    setQuery(restored.filters.query)
    setArtist(restored.filters.artist)
    setKeyFilter(restored.filters.key)
    setRating(restored.filters.rating)
    setTag(restored.filters.tag)
    setCollectionFilter(restored.filters.collectionType)
    setBpmMin(restored.filters.bpmMin)
    setBpmMax(restored.filters.bpmMax)
    pendingScroll.current = restored.scrollTop
    focusTracksOnLoad.current = sessionStorage.getItem('musicsync.react.focus-track-list') === window.location.pathname
    if (focusTracksOnLoad.current) sessionStorage.removeItem('musicsync.react.focus-track-list')
    setInitializedKey(collectionKey)
  }, [collectionKey, settings.isPending])

  const params = {
    sort_field: sort?.field,
    sort_direction: sort?.direction,
    q: deferredQuery,
    artist: artist ? [artist] : [],
    key: keyFilter ? [keyFilter] : [],
    rating: rating ? [rating] : [],
    tag: tag ? [tag] : [],
    collection_type: collectionType === 'search' && collectionFilter ? [collectionFilter] : [],
    bpm_min: bpmMin,
    bpm_max: bpmMax,
  }
  const trackQueryKey = ['tracks', collectionType, collectionId, params] as const
  const tracks = useInfiniteQuery({
    queryKey: trackQueryKey,
    queryFn: ({ pageParam }) => api<TrackPage>(`/collections/${collectionType}/${encodeURIComponent(collectionId)}/tracks${queryString({ ...params, offset: pageParam, limit: PAGE_SIZE })}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
    enabled: initializedKey === collectionKey,
  })

  async function refreshFromTidal(force: boolean) {
    setRefreshError('')
    try {
      const job = await api<Job>(`/collections/${collectionType}/${encodeURIComponent(collectionId)}/refresh?force=${force}`, { method: 'POST' })
      setRefreshJobId(job.id)
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : 'Could not start the TIDAL refresh.')
      checkedCollections.delete(collectionKey)
    }
  }

  useEffect(() => {
    if (!providerBacked || initializedKey !== collectionKey || checkedCollections.has(collectionKey)) return
    checkedCollections.add(collectionKey)
    void refreshFromTidal(false)
  }, [collectionKey, initializedKey, providerBacked])
  const pages = tracks.data?.pages ?? []
  const rows = pages.flatMap((page) => page.items)
  const pageInfo = pages[0]
  const selected = rows.find((row) => row.id === anchorId) ?? rows[0] ?? null
  const selectedTracks = rows.filter((row) => selectedIds.has(row.id))

  useEffect(() => {
    if (!rows.length || (anchorId && rows.some((row) => row.id === anchorId))) return
    setAnchorId(rows[0].id)
    setSelectedIds(new Set([rows[0].id]))
  }, [rows, anchorId])

  useEffect(() => {
    if (!focusTracksOnLoad.current || !rows.length) return
    const first = rows[0]
    setAnchorId(first.id)
    setSelectedIds(new Set([first.id]))
    focusTracksOnLoad.current = false
    requestAnimationFrame(() => browserRootRef.current?.focus({ preventScroll: collectionType === 'watched_mix' }))
  }, [rows])

  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && tracks.hasNextPage && !tracks.isFetchingNextPage) {
        setLoaded((value) => value + PAGE_SIZE)
        void tracks.fetchNextPage()
      }
    }, { root: tableRef.current, rootMargin: '300px' })
    const node = sentinelRef.current
    if (node) observer.observe(node)
    return () => observer.disconnect()
  }, [tracks.hasNextPage, tracks.isFetchingNextPage, tracks.fetchNextPage])

  useEffect(() => {
    if (initializedKey !== collectionKey || rows.length >= loaded || !tracks.hasNextPage || tracks.isFetchingNextPage) return
    void tracks.fetchNextPage()
  }, [collectionKey, initializedKey, loaded, rows.length, tracks.hasNextPage, tracks.isFetchingNextPage, tracks.fetchNextPage])

  useEffect(() => {
    if (initializedKey !== collectionKey || tracks.isFetching || pendingScroll.current === null || !tableRef.current) return
    if (rows.length < loaded && tracks.hasNextPage) return
    const target = pendingScroll.current
    const frame = requestAnimationFrame(() => {
      if (tableRef.current) tableRef.current.scrollTop = target
      pendingScroll.current = null
    })
    return () => cancelAnimationFrame(frame)
  }, [collectionKey, initializedKey, rows.length, tracks.isFetching])

  useEffect(() => {
    const node = tableRef.current
    if (!node || initializedKey !== collectionKey) return
    const filters: BrowserFilters = { query, artist, key: keyFilter, rating, tag, collectionType: collectionFilter, bpmMin, bpmMax }
    const save = () => saveBrowserState(collectionKey, { sort, visibleFields, selectedId: anchorId, scrollTop: node.scrollTop, loaded, filters })
    node.addEventListener('scroll', save, { passive: true })
    if (pendingScroll.current === null) save()
    return () => {
      node.removeEventListener('scroll', save)
      // React StrictMode immediately replays effects in development. Do not
      // overwrite a not-yet-restored saved position with the DOM's initial 0.
      if (pendingScroll.current === null) save()
    }
  }, [collectionKey, initializedKey, sort, visibleFields, anchorId, loaded, query, artist, keyFilter, rating, tag, collectionFilter, bpmMin, bpmMax])

  useEffect(() => {
    if (pendingScroll.current !== null) return
    const viewport = tableRef.current
    const row = viewport?.querySelector<HTMLElement>(`tr[data-track-id="${CSS.escape(anchorId ?? '')}"]`)
    if (viewport && row) keepRowVisible(viewport, row)
  }, [anchorId])

  const columns = useMemo(() => {
    const allowed = new Set(visibleFields)
    allowed.delete('mix_position')
    if (collectionType === 'setlist') allowed.add('mix_position')
    return COLUMNS.filter((column) => allowed.has(column.key))
  }, [visibleFields, collectionType])

  function selectRow(index: number, extend: boolean) {
    const row = rows[index]
    if (!row) return
    if (extend && lastRangeIndex !== null) {
      const [start, end] = [lastRangeIndex, index].sort((a, b) => a - b)
      setSelectedIds(new Set(rows.slice(start, end + 1).map((item) => item.id)))
    } else {
      setSelectedIds(new Set([row.id]))
      setLastRangeIndex(index)
    }
    setAnchorId(row.id)
  }

  function handleTableKeys(event: React.KeyboardEvent<HTMLDivElement>) {
    if (isEditing(event.target) || !rows.length) return
    const index = Math.max(0, rows.findIndex((row) => row.id === anchorId))
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const target = Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))
      selectRow(target, event.shiftKey)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      document.getElementById('track-actions')?.focus()
    }
  }

  function cycleSort(field: string) {
    setLoaded(PAGE_SIZE)
    setSort((current) => {
      if (!current || current.field !== field) return { field, direction: 'asc' }
      if (current.direction === 'asc') return { field, direction: 'desc' }
      return null
    })
  }

  function applyQuickView(fields: string[]) {
    setVisibleFields(fields)
    setFieldsOpen(false)
  }

  function clearFilters() {
    setQuery(''); setArtist(''); setKeyFilter(''); setRating(''); setTag(''); setCollectionFilter(''); setBpmMin(''); setBpmMax(''); setLoaded(PAGE_SIZE)
  }

  const stats = pageInfo?.stats
  const hasFilters = Boolean(query || artist || keyFilter || rating || tag || collectionFilter || bpmMin || bpmMax)
  const emptyCopy = collectionType === 'search'
    ? hasFilters
      ? 'No indexed tracks match these search filters.'
      : 'Search your cached library by title, artist, remix, or album.'
    : collectionType === 'setlist'
      ? 'This mix has no imported TIDAL setlist yet. Save a TIDAL playlist URL and choose Sync playlist above.'
      : collectionType === 'watched_mix'
        ? 'No tracks are associated with this watched mix yet. Associate tracks from a library track action.'
        : providerBacked
          ? 'This indexed collection has no cached tracks yet. Refresh from TIDAL to check it again.'
          : 'No cached tracks are available for this view yet.'
  return <section ref={browserRootRef} className="track-browser" data-track-browser-root tabIndex={0} onKeyDown={handleTableKeys}>
    <header className={`tool-heading${hideCollectionHeading ? ' track-toolbar-only' : ''}`}>
      <div>{!hideCollectionHeading ? <h1>{pageInfo?.collection.name ?? 'Loading collection…'}</h1> : null}<p>{collectionType === 'search' ? 'Search every locally indexed track.' : `${pageInfo?.total?.toLocaleString() ?? '…'} tracks in the local library.`}</p></div>
      <div className="track-toolbar">
        {(settings.data?.quick_views ?? []).map((view) => <button type="button" key={view.id} className={`quiet ${view.default ? 'default-view' : ''}`} onClick={() => applyQuickView(view.fields)}>{view.name}</button>)}
        <div className="fields-picker">
          <button type="button" className="quiet" onClick={() => setFieldsOpen((value) => !value)} aria-expanded={fieldsOpen}>Fields</button>
          {fieldsOpen ? <div className="fields-menu">{COLUMNS.filter((column) => column.key !== 'mix_position').map((column) => <label key={column.key}><input type="checkbox" checked={visibleFields.includes(column.key)} onChange={(event) => setVisibleFields((current) => event.target.checked ? [...current, column.key] : current.filter((field) => field !== column.key))} />{column.label}</label>)}</div> : null}
        </div>
        <button
          type="button"
          className="primary"
          onClick={() => providerBacked ? void refreshFromTidal(true) : void tracks.refetch()}
          disabled={tracks.isFetching}
        >{providerBacked ? 'Refresh from TIDAL' : tracks.isFetching ? 'Loading…' : 'Reload SQLite'}</button>
      </div>
    </header>
    {refreshError ? <div className="error-banner">{refreshError}</div> : null}
    <JobStatus
      jobId={refreshJobId}
      onComplete={() => {
        void queryClient.invalidateQueries({ queryKey: ['tracks', collectionType, collectionId] })
        void queryClient.invalidateQueries({ queryKey: ['navigation'] })
        setRefreshJobId(null)
      }}
      onFailed={(message) => { setRefreshError(message); setRefreshJobId(null); checkedCollections.delete(collectionKey) }}
    />
    {collectionType === 'event' ? <EventMedia eventId={collectionId} /> : null}
    {stats ? <div className="collection-stats"><span className="stats-label">Collection stats</span>{stats.top_artists.map((item) => <Link key={item.id} className="stat artist-stat" to={`/artists/${encodeURIComponent(item.id)}`}><strong>{item.name}</strong> {item.count} tracks</Link>)}{stats.bpm_min !== null ? <span className="stat bpm-stat"><strong>BPM</strong> {stats.bpm_min}–{stats.bpm_max}</span> : null}{stats.vibe ? <span className="stat vibe-stat"><strong>Top vibe</strong> {stats.vibe} · {stats.vibe_count}</span> : null}</div> : null}
    <div className="quick-filters">
      <label>Track<input value={query} onChange={(event) => { setQuery(event.target.value); setLoaded(PAGE_SIZE) }} placeholder={collectionType === 'search' ? 'Title, artist, album…' : 'Title or remix…'} /></label>
      {collectionType === 'search' ? <label>Found in<select value={collectionFilter} onChange={(event) => { setCollectionFilter(event.target.value); setLoaded(PAGE_SIZE) }}><option value="">Any indexed collection</option><option value="playlist">Playlists</option><option value="event">Events</option><option value="source">Sources</option><option value="mix">My mixes</option></select></label> : null}
      <label>Artist<select value={artist} onChange={(event) => { setArtist(event.target.value); setLoaded(PAGE_SIZE) }}><option value="">Any artist</option>{stats?.artist_options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label>Key<select value={keyFilter} onChange={(event) => { setKeyFilter(event.target.value); setLoaded(PAGE_SIZE) }}><option value="">Any key</option>{CAMELOT_KEYS.map((key) => <option key={key}>{key}</option>)}</select></label>
      <label>Tag<select value={tag} onChange={(event) => { setTag(event.target.value); setLoaded(PAGE_SIZE) }}><option value="">Any tag</option>{Object.entries(dimensions.data?.values ?? {}).filter(([dimension]) => dimension !== 'rating').map(([dimension, values]) => <optgroup key={dimension} label={dimensions.data?.labels[dimension] ?? dimension}>{values.map((value) => <option key={`${dimension}:${value}`} value={`${dimension}:${value}`}>{value}</option>)}</optgroup>)}</select></label>
      <label>BPM min<input inputMode="numeric" value={bpmMin} onChange={(event) => { setBpmMin(event.target.value); setLoaded(PAGE_SIZE) }} /></label>
      <label>BPM max<input inputMode="numeric" value={bpmMax} onChange={(event) => { setBpmMax(event.target.value); setLoaded(PAGE_SIZE) }} /></label>
      <label>Rating<select value={rating} onChange={(event) => { setRating(event.target.value); setLoaded(PAGE_SIZE) }}><option value="">Any rating</option>{[1,2,3,4,5].map((value) => <option key={value} value={value}>{'★'.repeat(value)}</option>)}</select></label>
      <button type="button" className="quiet clear-filters" onClick={clearFilters}>Clear</button>
    </div>
    {tracks.isError ? <div className="error-banner">{tracks.error.message}</div> : null}
    <div className="library-layout">
      <div className="track-list-pane">
        {collectionType === 'setlist' ? <MixStopwatch rows={rows} onActiveTrackChange={setActiveTrackId} storageKey={`musicsync.stopwatch:${collectionType}:${collectionId}`} /> : null}
        <div className="track-status">{tracks.isFetching && !rows.length ? 'Loading from SQLite…' : `${rows.length.toLocaleString()} of ${(pageInfo?.total ?? 0).toLocaleString()} tracks loaded.`}</div>
        <div className="track-table-wrap" ref={tableRef}>
          <table className="track-table">
            <thead><tr>{columns.map((column) => <th key={column.key} className={column.className} onClick={() => cycleSort(column.key)}><button type="button" className="sort-button">{column.label}<span>{sort?.field === column.key ? sort.direction === 'asc' ? '▲' : '▼' : ''}</span></button></th>)}</tr></thead>
            <tbody>{rows.map((track, index) => <tr
              key={`${track.id}:${track._source_order}`}
              data-track-id={track.id}
              className={`${anchorId === track.id ? 'selected' : ''} ${selectedIds.has(track.id) ? 'multi-selected' : ''} ${activeTrackId === track.id ? 'mix-current-track' : ''}`}
              onClick={(event) => {
                selectRow(index, event.shiftKey)
                browserRootRef.current?.focus()
              }}
            >{columns.map((column) => <td key={column.key} className={column.className}>{column.value(track)}</td>)}</tr>)}</tbody>
          </table>
          {!tracks.isFetching && !rows.length ? <div className="empty-table"><strong>{emptyCopy}</strong>{hasFilters ? <button type="button" className="quiet" onClick={clearFilters}>Clear filters</button> : null}</div> : null}
          <div ref={sentinelRef} className="load-sentinel">{tracks.hasNextPage ? tracks.isFetchingNextPage ? 'Loading more…' : 'Scroll for more' : ''}</div>
        </div>
      </div>
      <Inspector track={selected} selectedTracks={selectedTracks.length ? selectedTracks : selected ? [selected] : []} queryKey={trackQueryKey} collapsedDefault={settings.data?.tags_collapsed_by_default ?? true} collectionType={collectionType} collectionId={collectionId} />
    </div>
  </section>
}
