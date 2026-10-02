import { describe, expect, it } from 'vitest'
import type { MixSummary } from '../../api/types'
import { sortMixes } from './mixOverview'

function mix(folder_name: string, track_count: number, updated_at = ''): MixSummary {
  return {
    folder_name, track_count, updated_at, youtube_url: '', youtube_analytics_url: '', youtube_title: '', youtube_upload_date: updated_at, tidal_url: '',
    tidal_playlist_id: '', tidal_playlist_name: '', cover_url: '',
    has_cover: false,
    youtube_views: null, youtube_watch_minutes: null,
    youtube_average_view_duration: null, youtube_average_view_percentage: null,
    youtube_likes: null, youtube_comments: null,
    youtube_subscribers_gained: null, youtube_analytics_fetched_at: '',
  }
}

describe('My Mixes overview sorting', () => {
  const rows = [mix('Mix 10', 4, '2026-01-01'), mix('Mix 2', 12, '2026-02-01')]

  it('sorts names naturally and does not mutate API data', () => {
    expect(sortMixes(rows, { field: 'folder_name', direction: 'asc' }).map((row) => row.folder_name)).toEqual(['Mix 2', 'Mix 10'])
    expect(rows.map((row) => row.folder_name)).toEqual(['Mix 10', 'Mix 2'])
  })

  it('sorts numeric counts and ISO timestamps descending', () => {
    expect(sortMixes(rows, { field: 'track_count', direction: 'desc' })[0].track_count).toBe(12)
    expect(sortMixes(rows, { field: 'youtube_upload_date', direction: 'desc' })[0].youtube_upload_date).toBe('2026-02-01')
  })

  it('sorts YouTube engagement counts numerically', () => {
    const low = { ...mix('Low', 1), youtube_likes: 9, youtube_comments: 2 }
    const high = { ...mix('High', 1), youtube_likes: 120, youtube_comments: 30 }
    expect(sortMixes([low, high], { field: 'youtube_likes', direction: 'desc' })[0].folder_name).toBe('High')
    expect(sortMixes([low, high], { field: 'youtube_comments', direction: 'desc' })[0].folder_name).toBe('High')
  })
})
