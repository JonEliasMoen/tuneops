import { useEffect, useMemo, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { MixSummary } from '../../api/types'
import { nextTableSort, usePersistentTableSort, useTableKeyboardNavigation } from '../../components/dataTableState'
import { numericColorScale, numericScaleColor } from '../../components/numericColorScale'
import { sortMixes, type MixSortField } from './mixOverview'

const SORTABLE_COLUMNS: Array<{ field: MixSortField; label: string }> = [
  { field: 'folder_name', label: 'Mix' },
  { field: 'youtube_title', label: 'YouTube title' },
  { field: 'tidal_playlist_name', label: 'TIDAL setlist' },
  { field: 'track_count', label: 'Tracks' },
  { field: 'youtube_upload_date', label: 'Uploaded' },
  { field: 'youtube_views', label: 'Views' },
  { field: 'youtube_watch_minutes', label: 'Watch time' },
  { field: 'youtube_average_view_duration', label: 'Avg view' },
  { field: 'youtube_average_view_percentage', label: 'Avg %' },
  { field: 'youtube_likes', label: 'Likes' },
  { field: 'youtube_comments', label: 'Comments' },
  { field: 'youtube_subscribers_gained', label: 'Subs' },
]

function displayTimestamp(value: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

function duration(seconds: number | null) {
  if (seconds === null) return '—'
  const rounded = Math.round(seconds)
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

export function MixOverviewTable({ mixes }: { mixes: MixSummary[] }) {
  const navigate = useNavigate()
  const tableRoot = useRef<HTMLDivElement>(null)
  const [sort, setSort] = usePersistentTableSort<MixSortField>('musicsync.table-sort:mix-overview', { field: 'folder_name', direction: 'asc' })
  const rows = useMemo(() => sortMixes(mixes, sort), [mixes, sort])
  const viewsScale = useMemo(() => numericColorScale(mixes.map((mix) => mix.youtube_views)), [mixes])
  const averagePercentageScale = useMemo(() => numericColorScale(mixes.map((mix) => mix.youtube_average_view_percentage)), [mixes])

  const navigation = useTableKeyboardNavigation(rows, (mix) => mix.folder_name, (mix) => navigate(`/mixes/${encodeURIComponent(mix.folder_name)}`))
  useEffect(() => {
    if (!navigation.selectedKey) return
    document.querySelector<HTMLElement>(`tr[data-table-row-key="${CSS.escape(navigation.selectedKey)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [navigation.selectedKey])
  useEffect(() => {
    if (sessionStorage.getItem('musicsync.react.focus-track-list') !== window.location.pathname) return
    sessionStorage.removeItem('musicsync.react.focus-track-list')
    tableRoot.current?.focus({ preventScroll: true })
  }, [])

  function changeSort(field: MixSortField) {
    setSort((current) => nextTableSort(current, field))
  }

  return <div ref={tableRoot} className="mix-overview-table-wrap" tabIndex={0} onKeyDown={navigation.onKeyDown} aria-label="My mixes table">
    <table className="track-table mix-overview-table">
      <thead><tr>
        <th className="mix-cover-column">Cover</th>
        {SORTABLE_COLUMNS.map((column) => <th key={column.field}><button type="button" className="sort-button" onClick={() => changeSort(column.field)}>{column.label}<span>{sort?.field === column.field ? sort.direction === 'asc' ? '▲' : '▼' : ''}</span></button></th>)}
        <th>YouTube</th><th>Analytics</th>
      </tr></thead>
      <tbody>{rows.map((mix) => <tr key={mix.folder_name} data-table-row-key={mix.folder_name} className={navigation.selectedKey === mix.folder_name ? 'selected' : ''} onClick={() => navigation.setSelectedKey(mix.folder_name)} aria-selected={navigation.selectedKey === mix.folder_name}>
        <td className="mix-cover-column">{mix.cover_url ? <img src={mix.cover_url} alt="" loading="lazy" /> : <span className="mix-cover-empty">♪</span>}</td>
        <td><Link className="mix-name-link" to={`/mixes/${encodeURIComponent(mix.folder_name)}`}>{mix.folder_name}</Link></td>
        <td>{mix.youtube_title || <span className="empty-cell">—</span>}</td>
        <td>{mix.tidal_playlist_name || <span className="empty-cell">—</span>}</td>
        <td className="numeric">{mix.track_count.toLocaleString()}</td>
        <td>{displayTimestamp(mix.youtube_upload_date)}</td>
        <td className="numeric metric-scale-cell" style={{ backgroundColor: numericScaleColor(mix.youtube_views, viewsScale) }}>{mix.youtube_views === null ? '—' : mix.youtube_views.toLocaleString()}</td>
        <td className="numeric">{mix.youtube_watch_minutes === null ? '—' : `${Math.round(mix.youtube_watch_minutes / 60).toLocaleString()} h`}</td>
        <td className="numeric">{duration(mix.youtube_average_view_duration)}</td>
        <td className="numeric metric-scale-cell" style={{ backgroundColor: numericScaleColor(mix.youtube_average_view_percentage, averagePercentageScale) }}>{mix.youtube_average_view_percentage === null ? '—' : `${mix.youtube_average_view_percentage.toFixed(1)}%`}</td>
        <td className="numeric">{mix.youtube_likes === null ? '—' : mix.youtube_likes.toLocaleString()}</td>
        <td className="numeric">{mix.youtube_comments === null ? '—' : mix.youtube_comments.toLocaleString()}</td>
        <td className="numeric">{mix.youtube_subscribers_gained === null ? '—' : `+${mix.youtube_subscribers_gained.toLocaleString()}`}</td>
        <td>{mix.youtube_url ? <a href={mix.youtube_url} target="_blank" rel="noreferrer">Open</a> : <span className="empty-cell">—</span>}</td>
        <td>{mix.youtube_analytics_url ? <a href={mix.youtube_analytics_url} target="_blank" rel="noreferrer">Open</a> : <span className="empty-cell">—</span>}</td>
      </tr>)}</tbody>
    </table>
    {!rows.length ? <div className="empty-table"><strong>No local mix folders were found.</strong></div> : null}
  </div>
}
