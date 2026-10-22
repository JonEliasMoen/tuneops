import { describe, expect, it } from 'vitest'
import type { MixSummary } from '../../api/types'
import { mixPerformance, sortMixes, viewsPerDay } from './mixOverview'

function mix(folder_name: string, track_count: number, updated_at = ''): MixSummary {
  return {
    folder_name, track_count, updated_at, youtube_url: '', youtube_analytics_url: '', youtube_title: '', youtube_upload_date: updated_at, youtube_duration_seconds: null, tidal_url: '',
    tidal_playlist_id: '', tidal_playlist_name: '', cover_url: '',
    has_cover: false,
    youtube_views: null, youtube_thumbnail_impressions: null, youtube_thumbnail_ctr: null,
    youtube_watch_minutes: null,
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

  it('sorts cover click-through rate numerically', () => {
    const low = { ...mix('Low', 1), youtube_thumbnail_ctr: 2.4 }
    const high = { ...mix('High', 1), youtube_thumbnail_ctr: 7.1 }
    expect(sortMixes([low, high], { field: 'youtube_thumbnail_ctr', direction: 'desc' })[0].folder_name).toBe('High')
  })

  it('keeps missing values last in either direction', () => {
    const missing = mix('Missing', 1)
    const low = { ...mix('Low', 1), youtube_views: 2 }
    const high = { ...mix('High', 1), youtube_views: 20 }
    expect(sortMixes([missing, high, low], { field: 'youtube_views', direction: 'asc' }).map((row) => row.folder_name)).toEqual(['Low', 'High', 'Missing'])
    expect(sortMixes([missing, low, high], { field: 'youtube_views', direction: 'desc' }).map((row) => row.folder_name)).toEqual(['High', 'Low', 'Missing'])
  })

  it('normalizes views by days since upload and sorts the derived rate', () => {
    const newer = { ...mix('Newer', 1, '2026-10-06'), youtube_views: 100 }
    const older = { ...mix('Older', 1, '2026-09-28'), youtube_views: 50 }
    expect(viewsPerDay(newer, new Date('2026-10-07T12:00:00Z'))).toBe(50)
    expect(viewsPerDay(older, new Date('2026-10-07T12:00:00Z'))).toBe(5)
    expect(sortMixes([older, newer], { field: 'youtube_views_per_day', direction: 'desc' })[0].folder_name).toBe('Newer')
  })

  it('classifies relative reach and retention into actionable verdicts', () => {
    const today = new Date('2026-10-07T12:00:00Z')
    const winner = { ...mix('Winner', 1, '2026-10-06'), youtube_views: 40, youtube_average_view_percentage: 70 }
    const undersold = { ...mix('Undersold', 1, '2026-10-06'), youtube_views: 2, youtube_average_view_percentage: 65 }
    const weak = { ...mix('Weak', 1, '2026-10-06'), youtube_views: 30, youtube_average_view_percentage: 20 }
    const needsWork = { ...mix('Needs work', 1, '2026-10-06'), youtube_views: 1, youtube_average_view_percentage: 15 }
    const mixes = [winner, undersold, weak, needsWork]
    expect(mixPerformance(winner, mixes, today)?.verdict).toBe('Winner')
    expect(mixPerformance(undersold, mixes, today)?.verdict).toBe('Undersold')
    expect(mixPerformance(weak, mixes, today)?.verdict).toBe('Weak hold')
    expect(mixPerformance(needsWork, mixes, today)?.verdict).toBe('Needs work')
  })
})
