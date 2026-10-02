import type { MixSummary } from '../../api/types'

export type MixSortField = 'folder_name' | 'youtube_title' | 'tidal_playlist_name' | 'track_count' | 'youtube_upload_date' | 'youtube_views' | 'youtube_watch_minutes' | 'youtube_average_view_duration' | 'youtube_average_view_percentage' | 'youtube_likes' | 'youtube_comments' | 'youtube_subscribers_gained'

export type MixSort = {
  field: MixSortField
  direction: 'asc' | 'desc'
} | null

export function sortMixes(mixes: MixSummary[], sort: MixSort): MixSummary[] {
  if (!sort) return [...mixes]
  const direction = sort.direction === 'asc' ? 1 : -1
  return [...mixes].sort((left, right) => {
    if (['track_count', 'youtube_views', 'youtube_watch_minutes', 'youtube_average_view_duration', 'youtube_average_view_percentage', 'youtube_likes', 'youtube_comments', 'youtube_subscribers_gained'].includes(sort.field)) {
      return (Number(left[sort.field] ?? -1) - Number(right[sort.field] ?? -1)) * direction
    }
    return String(left[sort.field] || '').localeCompare(
      String(right[sort.field] || ''), undefined, { numeric: true, sensitivity: 'base' },
    ) * direction
  })
}
