import { useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { api, queryString } from '../../api/client'
import type { BeatportChartReference, BeatportChartTrack, PublicSettings } from '../../api/types'
import { useTableKeyboardNavigation } from '../../components/dataTableState'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import { Inspector } from '../track-browser/Inspector'

type FollowResponse = { items: BeatportChartReference[] }
type DetailResponse = {
  chart: BeatportChartReference
  mode: 'top' | 'recent'
  items: BeatportChartTrack[]
  offset: number
  limit: number
  total: number
  has_more: boolean
}
type TidalLookupResponse = {
  isrc: string
  track: { id: string; title: string; artist: string; tidal_uri: string }
}
const RECENT_PAGE_SIZE = 25
const TOP_PAGE_SIZE = 10
const GLOBAL_TOP: BeatportChartReference = { type: 'tracks', id: 'top', name: 'Top Beatport' }

function TidalSearchCell({ isrc }: { isrc: string }) {
  const normalized = isrc.trim().toUpperCase().replaceAll('-', '')
  const lookup = useQuery({
    queryKey: ['beatport-tidal-isrc', normalized],
    queryFn: () => api<TidalLookupResponse>(`/charts/tidal-match${queryString({ isrc: normalized })}`),
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  })
  if (!normalized) return <span className="empty-cell">—</span>
  if (lookup.data) return <a className="tidal-native chart-tidal-link" href={lookup.data.track.tidal_uri} title={`${lookup.data.track.artist} – ${lookup.data.track.title}`}>Play in TIDAL</a>
  return <button type="button" className="chart-search-tidal" disabled={lookup.isFetching} title={lookup.isError ? lookup.error.message : 'Search TIDAL by ISRC'} onClick={(event) => { event.stopPropagation(); void lookup.refetch() }}>{lookup.isFetching ? 'Searching…' : lookup.isError ? 'Retry TIDAL' : 'Search TIDAL'}</button>
}

export function ChartsOverviewPage() {
  const client = useQueryClient()
  const [type, setType] = useState<'genres' | 'labels' | 'artists'>('genres')
  const [query, setQuery] = useState('')
  const search = useDebouncedValue(query.trim())
  const followed = useQuery({ queryKey: ['beatport-charts'], queryFn: () => api<FollowResponse>('/charts') })
  const results = useQuery({
    queryKey: ['beatport-chart-search', type, search],
    queryFn: () => api<FollowResponse>(`/charts/search${queryString({ type, q: search })}`),
    enabled: search.length >= 2,
  })
  const follow = useMutation({
    mutationFn: (item: BeatportChartReference) => api<FollowResponse>('/charts', { method: 'POST', body: JSON.stringify(item) }),
    onSuccess: (value) => { client.setQueryData(['beatport-charts'], value); void client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  const unfollow = useMutation({
    mutationFn: (item: BeatportChartReference) => api<FollowResponse>(`/charts/${item.type}/${encodeURIComponent(item.id)}`, { method: 'DELETE' }),
    onSuccess: (value) => { client.setQueryData(['beatport-charts'], value); void client.invalidateQueries({ queryKey: ['navigation'] }) },
  })
  const followedKeys = new Set((followed.data?.items ?? []).map((item) => `${item.type}:${item.id}`))

  return <section className="charts-page">
    <header className="tool-heading"><div><p className="eyebrow">Beatport</p><h1>Charts</h1><p>Choose the genres, labels, artists, and global chart you want to keep in the sidebar.</p></div></header>
    <div className="chart-search-panel">
      <label>Type<select value={type} onChange={(event) => setType(event.target.value as 'genres' | 'labels' | 'artists')}><option value="genres">Genres</option><option value="labels">Labels</option><option value="artists">Artists</option></select></label>
      <label>Search Beatport<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={type === 'genres' ? 'Progressive House…' : type === 'labels' ? 'Colorize…' : 'Nora En Pure…'} /></label>
    </div>
    {results.isFetching ? <p>Searching Beatport…</p> : null}
    {results.isError ? <div className="error-banner">{results.error.message}</div> : null}
    {search.length >= 2 && results.data ? <div className="chart-result-list">{results.data.items.map((item) => {
      const active = followedKeys.has(`${item.type}:${item.id}`)
      return <article key={`${item.type}:${item.id}`}><div><strong>{item.name}</strong><small>{item.type === 'genres' ? 'Genre' : item.type === 'labels' ? 'Label' : 'Artist'}</small></div><button type="button" className={active ? 'danger' : 'primary'} disabled={follow.isPending || unfollow.isPending} onClick={() => active ? unfollow.mutate(item) : follow.mutate(item)}>{active ? 'Unfollow' : 'Follow'}</button></article>
    })}{!results.data.items.length ? <p>No Beatport matches.</p> : null}</div> : null}
    <section className="followed-charts"><h2>Top Beatport</h2><div className="chart-result-list"><article><div><strong>Top Beatport</strong><small>Global Top 100</small></div><button type="button" className={followedKeys.has('tracks:top') ? 'danger' : 'primary'} disabled={follow.isPending || unfollow.isPending} onClick={() => followedKeys.has('tracks:top') ? unfollow.mutate(GLOBAL_TOP) : follow.mutate(GLOBAL_TOP)}>{followedKeys.has('tracks:top') ? 'Unfollow' : 'Follow'}</button></article></div></section>
    <section className="followed-charts"><h2>Followed charts</h2>{followed.data?.items.length ? <div className="chart-result-list">{followed.data.items.map((item) => <article key={`${item.type}:${item.id}`}><div><strong>{item.name}</strong><small>{item.type === 'genres' ? 'Genre' : item.type === 'labels' ? 'Label' : item.type === 'artists' ? 'Artist' : 'Global chart'}</small></div><button type="button" className="danger" onClick={() => unfollow.mutate(item)}>Unfollow</button></article>)}</div> : <p>No charts followed yet. Search above to add one.</p>}</section>
  </section>
}

export function ChartDetailPage({ forcedType }: { forcedType?: 'labels' } = {}) {
  const route = useParams()
  const type = forcedType ?? route.type ?? ''
  const id = route.id ?? ''
  const location = useLocation()
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const mode = type !== 'tracks' && params.get('mode') === 'recent' ? 'recent' : 'top'
  const pageSize = mode === 'top' ? TOP_PAGE_SIZE : RECENT_PAGE_SIZE
  const tableRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const detail = useInfiniteQuery({
    queryKey: ['beatport-chart', type, id, mode],
    queryFn: ({ pageParam, signal }) => api<DetailResponse>(`/charts/${type}/${encodeURIComponent(id)}${queryString({ mode, offset: pageParam, limit: pageSize })}`, { signal }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  })
  const rows = useMemo(() => detail.data?.pages.flatMap((page) => page.items) ?? [], [detail.data])
  const navigation = useTableKeyboardNavigation(
    rows,
    (item) => `${item.id}:${item.position}`,
    (item) => { if (item.tidal_track) document.getElementById('track-actions')?.focus() },
  )
  const selected = rows.find((item) => `${item.id}:${item.position}` === navigation.selectedKey) ?? null
  const selectedTrack = selected?.tidal_track ?? null
  const chart = detail.data?.pages[0]?.chart
  const total = detail.data?.pages[0]?.total ?? 0
  const temporaryName = (location.state as { chartName?: string } | null)?.chartName ?? ''
  const chartName = (chart?.name && chart.name !== id ? chart.name : '') || (type === 'labels' ? rows[0]?.label : '') || temporaryName || id || 'Chart'
  const followed = useQuery({ queryKey: ['beatport-charts'], queryFn: () => api<FollowResponse>('/charts') })
  const followedHere = followed.data?.items.some((item) => item.type === type && item.id === id) ?? false
  const canFollow = type !== 'labels' || chartName !== id
  const follow = useMutation({
    mutationFn: () => api<FollowResponse>('/charts', { method: 'POST', body: JSON.stringify({ type, id, name: chartName }) }),
    onSuccess: (value) => { client.setQueryData(['beatport-charts'], value); void client.invalidateQueries({ queryKey: ['navigation'] }) },
  })

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !detail.hasNextPage) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !detail.isFetchingNextPage) void detail.fetchNextPage()
    }, { root: tableRef.current, rootMargin: '300px' })
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [detail.hasNextPage, detail.isFetchingNextPage, detail.fetchNextPage])

  useEffect(() => {
    if (!rows.length || sessionStorage.getItem('musicsync.react.focus-track-list') !== window.location.pathname) return
    sessionStorage.removeItem('musicsync.react.focus-track-list')
    navigation.setSelectedKey(`${rows[0].id}:${rows[0].position}`)
    requestAnimationFrame(() => tableRef.current?.focus({ preventScroll: true }))
  }, [rows.length])

  return <section className="charts-page">
    <header className="tool-heading"><div><p className="eyebrow">{type === 'tracks' ? 'Beatport global chart' : `Beatport ${type === 'labels' ? 'label' : type === 'artists' ? 'artist' : 'genre'}`}</p><h1>{chartName}</h1><p>{rows.length.toLocaleString()}{total ? ` of ${Math.min(total, mode === 'top' ? 100 : total).toLocaleString()}` : ''} {mode} tracks loaded.</p></div><div className="button-row">{!followedHere && type !== '' ? <button type="button" className="primary" disabled={follow.isPending || !canFollow} onClick={() => follow.mutate()}>{follow.isPending ? 'Following…' : 'Follow'}</button> : <span className="status-badge matched">Following</span>}<button type="button" className={mode === 'top' ? 'primary' : ''} onClick={() => setParams({ mode: 'top' })}>Top</button>{type !== 'tracks' ? <button type="button" className={mode === 'recent' ? 'primary' : ''} onClick={() => setParams({ mode: 'recent' })}>Recent</button> : null}{detail.hasNextPage ? <button type="button" className="quiet" disabled={detail.isFetchingNextPage} onClick={() => void detail.fetchNextPage()}>{detail.isFetchingNextPage ? 'Loading…' : `Load ${pageSize} more`}</button> : null}</div></header>
    {detail.isPending ? <p>Loading Beatport chart…</p> : null}
    {detail.isError ? <div className="error-banner">{detail.error.message}</div> : null}
    {detail.data ? <div className="library-layout">
      <div className="track-list-pane"><div ref={tableRef} className="track-table-wrap chart-table-wrap" tabIndex={0} onKeyDown={navigation.onKeyDown} aria-label="Beatport chart table"><table className="track-table"><thead><tr><th>#</th><th>Track</th><th>Artist</th><th>BPM</th><th>Key</th><th>Label</th><th>Genre</th><th>TIDAL</th><th>Released</th></tr></thead><tbody>{rows.map((item) => {
        const key = `${item.id}:${item.position}`
        return <tr key={key} className={navigation.selectedKey === key ? 'selected' : ''} aria-selected={navigation.selectedKey === key} onClick={() => navigation.setSelectedKey(key)}><td>{item.position}</td><td>{item.title}{item.mix ? <small className="chart-mix-name"> {item.mix}</small> : null}</td><td>{item.artists || '—'}</td><td className="numeric">{item.bpm ?? '—'}</td><td><span className="camelot-key" data-key={item.key}>{item.key || '—'}</span></td><td>{item.label_id && item.label ? <Link className="chart-label-link" to={`/charts/label/${encodeURIComponent(item.label_id)}`} state={{ chartName: item.label }} onClick={(event) => { event.stopPropagation(); sessionStorage.setItem('musicsync.react.focus-track-list', `/charts/label/${encodeURIComponent(item.label_id!)}`) }}>{item.label}</Link> : item.label || '—'}</td><td>{item.genre || '—'}</td><td>{item.tidal_track ? <span className="status-badge matched">Matched</span> : <TidalSearchCell isrc={item.isrc ?? ''} />}</td><td>{item.release_date || '—'}</td></tr>
      })}</tbody></table><div ref={sentinelRef} className="load-sentinel">{detail.hasNextPage ? <button type="button" className="quiet" disabled={detail.isFetchingNextPage} onClick={() => void detail.fetchNextPage()}>{detail.isFetchingNextPage ? 'Loading more…' : 'Load more'}</button> : null}</div></div></div>
      <Inspector track={selectedTrack} selectedTracks={selectedTrack ? [selectedTrack] : []} queryKey={['beatport-inspector-track', type, id]} collapsedDefault={settings.data?.tags_collapsed_by_default ?? true} collectionType="search" collectionId="beatport" />
    </div> : null}
  </section>
}
