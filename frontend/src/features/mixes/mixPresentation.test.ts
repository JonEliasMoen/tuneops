import { describe, expect, it } from 'vitest'
import { formatYouTubeFacts, watchedMixPresentation } from './mixPresentation'

describe('formatYouTubeFacts', () => {
  it('keeps zero views and omits missing facts', () => {
    expect(formatYouTubeFacts({ channel: 'Artist', views: 0 })).toBe('Artist · 0 views')
    expect(formatYouTubeFacts({})).toBe('')
  })
})

describe('watchedMixPresentation', () => {
  it('keeps the stored title while preferring fresh non-editable facts', () => {
    expect(watchedMixPresentation({
      title: 'My stored title',
      channel_name: 'Stored channel',
      upload_date: '2020-01-01',
      live_title: 'Current YouTube title',
      live_channel_name: 'Current channel',
      live_view_count: 1234,
      live_upload_date: '2026-09-27',
    })).toEqual({
      title: 'My stored title',
      facts: `Current channel · ${(1234).toLocaleString()} views · Uploaded 2026-09-27`,
    })
  })

  it('falls back to live title and then a useful placeholder', () => {
    expect(watchedMixPresentation({ live_title: 'Live title' }).title).toBe('Live title')
    expect(watchedMixPresentation().title).toBe('Untitled watched mix')
  })
})
