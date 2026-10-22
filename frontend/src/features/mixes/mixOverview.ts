import type { MixSummary } from '../../api/types'

export type MixSortField = 'folder_name' | 'youtube_title' | 'tidal_playlist_name' | 'track_count' | 'youtube_upload_date' | 'youtube_duration_seconds' | 'youtube_views' | 'youtube_views_per_day' | 'youtube_thumbnail_impressions' | 'youtube_thumbnail_ctr' | 'youtube_watch_minutes' | 'youtube_average_view_duration' | 'youtube_average_view_percentage' | 'youtube_likes' | 'youtube_comments' | 'youtube_subscribers_gained' | 'youtube_performance' | 'youtube_verdict'

export const MIX_FIELD_OPTIONS = [
  ['cover', 'Cover'], ['folder_name', 'Mix'], ['youtube_title', 'YouTube title'],
  ['tidal_playlist_name', 'TIDAL setlist'], ['track_count', 'Tracks'],
  ['youtube_upload_date', 'Uploaded'], ['youtube_duration_seconds', 'Length'],
  ['youtube_views', 'Views'], ['youtube_views_per_day', 'Views/day'],
  ['youtube_thumbnail_impressions', 'Reported cover impressions'], ['youtube_thumbnail_ctr', 'Recent cover CTR'],
  ['youtube_watch_minutes', 'Watch time'], ['youtube_average_view_duration', 'Avg view'],
  ['youtube_average_view_percentage', 'Avg %'], ['youtube_likes', 'Likes'],
  ['youtube_comments', 'Comments'], ['youtube_subscribers_gained', 'Subs'],
  ['youtube_performance', 'Performance'], ['youtube_verdict', 'Verdict'],
  ['youtube_url', 'YouTube'], ['youtube_analytics_url', 'Analytics'],
] as const

export type MixField = typeof MIX_FIELD_OPTIONS[number][0]
export const DEFAULT_MIX_FIELDS: MixField[] = MIX_FIELD_OPTIONS.map(([field]) => field)

export type MixSort = {
  field: MixSortField
  direction: 'asc' | 'desc'
} | null

const NUMERIC_MIX_FIELDS = new Set<MixSortField>([
  'track_count', 'youtube_duration_seconds', 'youtube_views', 'youtube_thumbnail_impressions',
  'youtube_thumbnail_ctr', 'youtube_watch_minutes', 'youtube_average_view_duration',
  'youtube_average_view_percentage', 'youtube_likes', 'youtube_comments',
  'youtube_subscribers_gained',
])

export function viewsPerDay(mix: MixSummary, today = new Date()): number | null {
  if (mix.youtube_views === null || !/^\d{4}-\d{2}-\d{2}$/.test(mix.youtube_upload_date)) return null
  const uploaded = Date.parse(`${mix.youtube_upload_date}T00:00:00Z`)
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  if (!Number.isFinite(uploaded) || uploaded > todayUtc) return null
  const ageDays = Math.max(1, Math.floor((todayUtc - uploaded) / 86_400_000) + 1)
  return mix.youtube_views / ageDays
}

function percentileRank(value: number, values: number[]): number {
  if (values.length <= 1) return 50
  const lower = values.filter((candidate) => candidate < value).length
  const equal = values.filter((candidate) => candidate === value).length
  return ((lower + (equal - 1) / 2) / (values.length - 1)) * 100
}

export type MixPerformance = {
  score: number
  reachPercentile: number
  retentionPercentile: number
  verdict: 'Winner' | 'Undersold' | 'Weak hold' | 'Needs work'
}

export function mixPerformance(mix: MixSummary, mixes: MixSummary[], today = new Date()): MixPerformance | null {
  const reach = viewsPerDay(mix, today)
  const retention = mix.youtube_average_view_percentage
  if (reach === null || retention === null) return null
  const reachValues = mixes.map((item) => viewsPerDay(item, today)).filter((value): value is number => value !== null)
  const retentionValues = mixes.map((item) => item.youtube_average_view_percentage).filter((value): value is number => value !== null)
  const reachPercentile = percentileRank(reach, reachValues)
  const retentionPercentile = percentileRank(retention, retentionValues)
  const highReach = reachPercentile >= 50
  const highRetention = retentionPercentile >= 50
  const verdict = highReach
    ? highRetention ? 'Winner' : 'Weak hold'
    : highRetention ? 'Undersold' : 'Needs work'
  return {
    score: retentionPercentile * 0.55 + reachPercentile * 0.45,
    reachPercentile,
    retentionPercentile,
    verdict,
  }
}

export function sortMixes(mixes: MixSummary[], sort: MixSort): MixSummary[] {
  if (!sort) return [...mixes]
  const field = sort.field
  const direction = sort.direction === 'asc' ? 1 : -1
  function value(mix: MixSummary): string | number | null {
    if (field === 'youtube_views_per_day') return viewsPerDay(mix)
    if (field === 'youtube_performance') return mixPerformance(mix, mixes)?.score ?? null
    if (field === 'youtube_verdict') return mixPerformance(mix, mixes)?.verdict ?? null
    if (NUMERIC_MIX_FIELDS.has(field)) {
      const candidate = mix[field]
      return candidate === null || candidate === undefined ? null : Number(candidate)
    }
    const candidate = mix[field]
    return candidate === null || candidate === undefined || candidate === '' ? null : String(candidate)
  }
  return [...mixes].sort((left, right) => {
    const leftValue = value(left)
    const rightValue = value(right)
    if (leftValue === null && rightValue === null) return 0
    if (leftValue === null) return 1
    if (rightValue === null) return -1
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return (leftValue - rightValue) * direction
    }
    return String(leftValue).localeCompare(String(rightValue), undefined, {
      numeric: true, sensitivity: 'base',
    }) * direction
  })
}
