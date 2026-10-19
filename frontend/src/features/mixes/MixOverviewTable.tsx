import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { MixSummary, PublicSettings } from '../../api/types'
import { nextTableSort, usePersistentTableSort, useTableKeyboardNavigation } from '../../components/dataTableState'
import { numericColorScale, numericScaleColor } from '../../components/numericColorScale'
import { DEFAULT_MIX_FIELDS, MIX_FIELD_OPTIONS, mixPerformance, sortMixes, viewsPerDay, type MixField, type MixSortField } from './mixOverview'

const LABELS = Object.fromEntries(MIX_FIELD_OPTIONS) as Record<MixField, string>
const SORTABLE = new Set<MixField>(MIX_FIELD_OPTIONS.map(([field]) => field).filter((field) => !['cover', 'youtube_url', 'youtube_analytics_url'].includes(field)))
const FIELD_STORAGE_KEY = 'musicsync.mix-overview-fields'

function displayTimestamp(value: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

function duration(seconds: number | null) {
  if (seconds === null) return '—'
  const rounded = Math.round(seconds)
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const remainder = rounded % 60
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}` : `${minutes}:${String(remainder).padStart(2, '0')}`
}

function rate(value: number | null) {
  if (value === null) return '—'
  return value < 10 ? value.toFixed(2) : value.toFixed(1)
}

function storedFields(): MixField[] | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(FIELD_STORAGE_KEY) || 'null')
    const allowed = new Set<MixField>(DEFAULT_MIX_FIELDS)
    const fields = Array.isArray(parsed) ? parsed.filter((field): field is MixField => allowed.has(field)) : []
    return fields.length ? fields : null
  } catch {
    return null
  }
}

export function MixOverviewTable({ mixes }: { mixes: MixSummary[] }) {
  const navigate = useNavigate()
  const tableRoot = useRef<HTMLDivElement>(null)
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const [sort, setSort] = usePersistentTableSort<MixSortField>('musicsync.table-sort:mix-overview', { field: 'folder_name', direction: 'asc' })
  const [visibleFields, setVisibleFields] = useState<MixField[]>(() => storedFields() ?? DEFAULT_MIX_FIELDS)
  const [fieldsOpen, setFieldsOpen] = useState(false)
  const initializedDefault = useRef(Boolean(storedFields()))
  const rows = useMemo(() => sortMixes(mixes, sort), [mixes, sort])
  const viewsScale = useMemo(() => numericColorScale(mixes.map((mix) => mix.youtube_views)), [mixes])
  const viewsPerDayScale = useMemo(() => numericColorScale(mixes.map((mix) => viewsPerDay(mix))), [mixes])
  const ctrScale = useMemo(() => numericColorScale(mixes.map((mix) => mix.youtube_thumbnail_ctr)), [mixes])
  const averagePercentageScale = useMemo(() => numericColorScale(mixes.map((mix) => mix.youtube_average_view_percentage)), [mixes])
  const performanceScale = useMemo(() => numericColorScale(mixes.map((mix) => mixPerformance(mix, mixes)?.score)), [mixes])

  useEffect(() => {
    if (initializedDefault.current || !settings.data) return
    const configured = settings.data.mix_quick_views.find((view) => view.default)?.fields ?? DEFAULT_MIX_FIELDS
    const allowed = new Set<MixField>(DEFAULT_MIX_FIELDS)
    const normalized = configured.filter((field): field is MixField => allowed.has(field as MixField))
    setVisibleFields(normalized.length ? normalized : DEFAULT_MIX_FIELDS)
    initializedDefault.current = true
  }, [settings.data])
  useEffect(() => {
    if (initializedDefault.current) sessionStorage.setItem(FIELD_STORAGE_KEY, JSON.stringify(visibleFields))
  }, [visibleFields])

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

  function changeSort(field: MixField) {
    if (SORTABLE.has(field)) setSort((current) => nextTableSort(current, field as MixSortField))
  }

  function applyQuickView(fields: string[]) {
    const allowed = new Set<MixField>(DEFAULT_MIX_FIELDS)
    const normalized = fields.filter((field): field is MixField => allowed.has(field as MixField))
    setVisibleFields(normalized.length ? normalized : DEFAULT_MIX_FIELDS)
    setFieldsOpen(false)
  }

  function cell(field: MixField, mix: MixSummary): ReactNode {
    const performance = mixPerformance(mix, mixes)
    switch (field) {
      case 'cover': return mix.cover_url ? <img src={mix.cover_url} alt="" loading="lazy" /> : <span className="mix-cover-empty">♪</span>
      case 'folder_name': return <Link className="mix-name-link" to={`/mixes/${encodeURIComponent(mix.folder_name)}`}>{mix.folder_name}</Link>
      case 'youtube_title': return mix.youtube_title || <span className="empty-cell">—</span>
      case 'tidal_playlist_name': return mix.tidal_playlist_name || <span className="empty-cell">—</span>
      case 'track_count': return mix.track_count.toLocaleString()
      case 'youtube_upload_date': return displayTimestamp(mix.youtube_upload_date)
      case 'youtube_duration_seconds': return duration(mix.youtube_duration_seconds)
      case 'youtube_views': return mix.youtube_views === null ? '—' : mix.youtube_views.toLocaleString()
      case 'youtube_views_per_day': return rate(viewsPerDay(mix))
      case 'youtube_thumbnail_impressions': return mix.youtube_thumbnail_impressions === null ? '—' : mix.youtube_thumbnail_impressions.toLocaleString()
      case 'youtube_thumbnail_ctr': return mix.youtube_thumbnail_ctr === null ? '—' : `${mix.youtube_thumbnail_ctr.toFixed(2)}%`
      case 'youtube_watch_minutes': return mix.youtube_watch_minutes === null ? '—' : `${Math.round(mix.youtube_watch_minutes / 60).toLocaleString()} h`
      case 'youtube_average_view_duration': return duration(mix.youtube_average_view_duration)
      case 'youtube_average_view_percentage': return mix.youtube_average_view_percentage === null ? '—' : `${mix.youtube_average_view_percentage.toFixed(1)}%`
      case 'youtube_likes': return mix.youtube_likes === null ? '—' : mix.youtube_likes.toLocaleString()
      case 'youtube_comments': return mix.youtube_comments === null ? '—' : mix.youtube_comments.toLocaleString()
      case 'youtube_subscribers_gained': return mix.youtube_subscribers_gained === null ? '—' : `+${mix.youtube_subscribers_gained.toLocaleString()}`
      case 'youtube_performance': return performance ? Math.round(performance.score) : '—'
      case 'youtube_verdict': return performance ? <span className={`performance-verdict ${performance.verdict.toLowerCase().replace(' ', '-')}`}>{performance.verdict}</span> : <span className="empty-cell">—</span>
      case 'youtube_url': return mix.youtube_url ? <a href={mix.youtube_url} target="_blank" rel="noreferrer">Open</a> : <span className="empty-cell">—</span>
      case 'youtube_analytics_url': return mix.youtube_analytics_url ? <a href={mix.youtube_analytics_url} target="_blank" rel="noreferrer">Open</a> : <span className="empty-cell">—</span>
    }
  }

  function cellClass(field: MixField) {
    return `${field === 'cover' ? 'mix-cover-column' : ''} ${['track_count', 'youtube_duration_seconds', 'youtube_views', 'youtube_views_per_day', 'youtube_thumbnail_impressions', 'youtube_thumbnail_ctr', 'youtube_watch_minutes', 'youtube_average_view_duration', 'youtube_average_view_percentage', 'youtube_likes', 'youtube_comments', 'youtube_subscribers_gained', 'youtube_performance'].includes(field) ? 'numeric' : ''}`.trim()
  }

  function cellStyle(field: MixField, mix: MixSummary) {
    const value = field === 'youtube_views' ? mix.youtube_views
      : field === 'youtube_views_per_day' ? viewsPerDay(mix)
        : field === 'youtube_thumbnail_ctr' ? mix.youtube_thumbnail_ctr
          : field === 'youtube_average_view_percentage' ? mix.youtube_average_view_percentage
            : field === 'youtube_performance' ? mixPerformance(mix, mixes)?.score ?? null : null
    const scale = field === 'youtube_views' ? viewsScale
      : field === 'youtube_views_per_day' ? viewsPerDayScale
        : field === 'youtube_thumbnail_ctr' ? ctrScale
          : field === 'youtube_average_view_percentage' ? averagePercentageScale
            : performanceScale
    return value === null ? undefined : { backgroundColor: numericScaleColor(value, scale) }
  }

  return <>
    <div className="track-toolbar mix-overview-toolbar">
      {(settings.data?.mix_quick_views ?? []).map((view) => <button type="button" key={view.id} className={`quiet ${view.default ? 'default-view' : ''}`} onClick={() => applyQuickView(view.fields)}>{view.name}</button>)}
      <div className="fields-picker">
        <button type="button" className="quiet" onClick={() => setFieldsOpen((value) => !value)} aria-expanded={fieldsOpen}>Fields</button>
        {fieldsOpen ? <div className="fields-menu">{MIX_FIELD_OPTIONS.map(([field, label]) => <label key={field}><input type="checkbox" checked={visibleFields.includes(field)} onChange={(event) => setVisibleFields((current) => event.target.checked ? [...current, field] : current.filter((item) => item !== field))} />{label}</label>)}</div> : null}
      </div>
    </div>
    <div ref={tableRoot} className="mix-overview-table-wrap" tabIndex={0} onKeyDown={navigation.onKeyDown} aria-label="My mixes table">
      <table className="track-table mix-overview-table">
        <thead><tr>{visibleFields.map((field) => <th key={field} className={field === 'cover' ? 'mix-cover-column' : ''}>{SORTABLE.has(field) ? <button type="button" className="sort-button" onClick={() => changeSort(field)}>{LABELS[field]}<span>{sort?.field === field ? sort.direction === 'asc' ? '▲' : '▼' : ''}</span></button> : LABELS[field]}</th>)}</tr></thead>
        <tbody>{rows.map((mix) => <tr key={mix.folder_name} data-table-row-key={mix.folder_name} className={navigation.selectedKey === mix.folder_name ? 'selected' : ''} onClick={() => navigation.setSelectedKey(mix.folder_name)} aria-selected={navigation.selectedKey === mix.folder_name}>
          {visibleFields.map((field) => <td key={field} className={`${cellClass(field)} ${['youtube_views', 'youtube_views_per_day', 'youtube_thumbnail_ctr', 'youtube_average_view_percentage', 'youtube_performance'].includes(field) ? 'metric-scale-cell' : ''}`.trim()} style={cellStyle(field, mix)}>{cell(field, mix)}</td>)}
        </tr>)}</tbody>
      </table>
      {!rows.length ? <div className="empty-table"><strong>No local mix folders were found.</strong></div> : null}
    </div>
  </>
}
