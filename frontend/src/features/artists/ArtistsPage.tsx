import { useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, queryString } from '../../api/client'
import type { ArtistOverviewPage, ArtistOverviewRow, PublicSettings } from '../../api/types'
import { nextTableSort, usePersistentTableSort, useTableKeyboardNavigation } from '../../components/dataTableState'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'

const PAGE_SIZE = 200
const QUERY_STORAGE_KEY = 'musicsync.artist-overview-query'
const SCROLL_STORAGE_KEY = 'musicsync.artist-overview-scroll'
type ArtistSortField = 'name' | 'indexed_tracks' | 'lastfm_plays'

export function ArtistsPage() {
  const navigate = useNavigate()
  const tableRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const restoredScroll = useRef(false)
  const [query, setQuery] = useState(() => sessionStorage.getItem(QUERY_STORAGE_KEY) || '')
  const deferredQuery = useDebouncedValue(query)
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const [sort, setSort] = usePersistentTableSort<ArtistSortField>('musicsync.table-sort:artists', null)
  const pages = useInfiniteQuery({
    queryKey: ['artists', deferredQuery, sort],
    queryFn: ({ pageParam, signal }) => api<ArtistOverviewPage>(`/artists${queryString({
      offset: pageParam,
      limit: PAGE_SIZE,
      q: deferredQuery,
      sort_field: sort?.field || 'name',
      sort_direction: sort?.direction || 'asc',
    })}`, { signal }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  })
  const rows = useMemo(() => pages.data?.pages.flatMap((page) => page.items) ?? [], [pages.data])
  const total = pages.data?.pages[0]?.total ?? 0
  const navigation = useTableKeyboardNavigation(
    rows,
    (artist) => artist.id,
    (artist) => navigate(`/artists/${encodeURIComponent(artist.id)}`),
  )

  useEffect(() => { sessionStorage.setItem(QUERY_STORAGE_KEY, query) }, [query])
  useEffect(() => {
    if (!sentinelRef.current || !pages.hasNextPage) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !pages.isFetchingNextPage) void pages.fetchNextPage()
    }, { root: tableRef.current, rootMargin: '300px' })
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [pages.hasNextPage, pages.isFetchingNextPage, pages.fetchNextPage])
  useEffect(() => {
    if (!rows.length || restoredScroll.current || !tableRef.current) return
    tableRef.current.scrollTop = Number(sessionStorage.getItem(SCROLL_STORAGE_KEY) || 0)
    restoredScroll.current = true
  }, [rows.length])
  useEffect(() => {
    if (!navigation.selectedKey) return
    tableRef.current?.querySelector<HTMLElement>(`tr[data-table-row-key="${CSS.escape(navigation.selectedKey)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [navigation.selectedKey])
  useEffect(() => {
    if (sessionStorage.getItem('musicsync.react.focus-track-list') !== window.location.pathname) return
    sessionStorage.removeItem('musicsync.react.focus-track-list')
    tableRef.current?.focus({ preventScroll: true })
  }, [rows.length])

  function heading(field: ArtistSortField, label: string) {
    return <button type="button" className="sort-button" onClick={() => {
      tableRef.current?.scrollTo({ top: 0 })
      sessionStorage.setItem(SCROLL_STORAGE_KEY, '0')
      setSort((current) => nextTableSort(current, field, settings.data?.default_sort_direction ?? 'asc'))
    }}>
      {label}<span>{sort?.field === field ? sort.direction === 'asc' ? '▲' : '▼' : ''}</span>
    </button>
  }

  return <section>
    <header className="tool-heading"><div><p className="eyebrow">Library</p><h1>Artists</h1><p>Artists represented in your indexed tracks, with matched Last.fm listening history.</p></div></header>
    <div className="artist-overview-search">
      <label>Search artists<input value={query} onChange={(event) => { setQuery(event.target.value); tableRef.current?.scrollTo({ top: 0 }); sessionStorage.setItem(SCROLL_STORAGE_KEY, '0') }} placeholder="Artist name…" /></label>
      {query ? <button type="button" onClick={() => { setQuery(''); tableRef.current?.scrollTo({ top: 0 }); sessionStorage.setItem(SCROLL_STORAGE_KEY, '0') }}>Clear</button> : null}
    </div>
    <p className="track-status">{pages.isPending ? 'Loading artists…' : `${rows.length.toLocaleString()} of ${total.toLocaleString()} artists loaded.`}</p>
    {pages.isError ? <div className="error-banner">{pages.error.message}</div> : null}
    <div
      ref={tableRef}
      className="track-table-wrap artist-overview-table"
      tabIndex={0}
      aria-label="Artists table"
      onKeyDown={navigation.onKeyDown}
      onScroll={(event) => sessionStorage.setItem(SCROLL_STORAGE_KEY, String(event.currentTarget.scrollTop))}
    >
      <table className="track-table">
        <thead><tr><th>{heading('name', 'Artist')}</th><th className="numeric">{heading('indexed_tracks', 'Indexed tracks')}</th><th className="numeric">{heading('lastfm_plays', 'Last.fm streams')}</th></tr></thead>
        <tbody>{rows.map((artist: ArtistOverviewRow) => <tr
          key={artist.id}
          data-table-row-key={artist.id}
          className={navigation.selectedKey === artist.id ? 'selected' : ''}
          aria-selected={navigation.selectedKey === artist.id}
          onClick={() => navigation.setSelectedKey(artist.id)}
          onDoubleClick={() => navigate(`/artists/${encodeURIComponent(artist.id)}`)}
        >
          <td><Link className="artist-link" to={`/artists/${encodeURIComponent(artist.id)}`}>{artist.name}</Link></td>
          <td className="numeric">{artist.indexed_tracks.toLocaleString()}</td>
          <td className="numeric">{artist.lastfm_plays.toLocaleString()}</td>
        </tr>)}</tbody>
      </table>
      {pages.hasNextPage ? <div ref={sentinelRef} className="load-sentinel">{pages.isFetchingNextPage ? 'Loading more…' : 'Scroll for more'}</div> : null}
      {!pages.isPending && !rows.length ? <div className="empty-table"><strong>No indexed artists match this search.</strong></div> : null}
    </div>
  </section>
}
