import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import type { Track, TrackPage } from '../../api/types'
import { Inspector } from './Inspector'

const track: Track = {
  id: 'track-1', title: 'Test track', artist: 'Test artist', artists: [], remix: '', album: '', album_art_url: '',
  length: '4:00', bpm: '120', key: '08A', year: '2026', date_added: '', playlists: [], events: [], sources: [], mixes: [], djmi: [],
  dimensions: {}, play_count: 0, last_played: '', tidal_uri: 'tidal://track/track-1', _source_order: 0,
}

const page: TrackPage = {
  collection: { type: 'playlist', id: 'source-playlist', name: 'Source', collection_type: 'playlist' },
  items: [track], total: 1, offset: 0, limit: 200, has_more: false,
  stats: { top_artists: [], artist_options: [], bpm_min: null, bpm_max: null, vibe: '', vibe_count: 0 },
}

function renderInspector() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Inspector
        track={track}
        selectedTracks={[track]}
        queryKey={['tracks', 'playlist', 'source-playlist']}
        collapsedDefault
        collectionType="playlist"
        collectionId="source-playlist"
      />
    </QueryClientProvider>,
  )
}

describe('track inspector playlist actions', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/dimensions')) return Promise.resolve({ ok: true, json: async () => ({ values: {}, labels: {}, max_values: {} }) })
      if (url.endsWith('/playlist-options')) return Promise.resolve({ ok: true, json: async () => ([
        { id: 'playlist-1', name: 'Normal playlist', collection_type: 'playlist' },
        { id: 'event-1', name: 'Festival set', collection_type: 'event' },
        { id: 'source-1', name: 'Shazam source', collection_type: 'source' },
      ]) })
      if (url.endsWith('/watched-mixes')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.endsWith('/tracks/like') && init?.method === 'POST') return Promise.resolve({ ok: true, json: async () => ({ message: 'Liked 1 track in TIDAL.' }) })
      if (url.endsWith('/tracks/playlist-action') && init?.method === 'POST') return Promise.resolve({ ok: true, json: async () => ({ message: 'Added 1 track.' }) })
      return Promise.reject(new Error(`Unexpected API request: ${url}`))
    }))
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('offers playlists, events, and sources as Add destinations', async () => {
    const user = userEvent.setup()
    renderInspector()
    await user.click(screen.getByRole('button', { name: 'Add to playlist' }))

    expect(await screen.findByText('Playlists')).toBeTruthy()
    expect(screen.getByText('Events')).toBeTruthy()
    expect(screen.getByText('Sources')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Normal playlist' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Festival set' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Shazam source' })).toBeTruthy()
  })

  it('shows the last Add destination first on the next use', async () => {
    sessionStorage.setItem('musicsync.react.recent-add-playlist', 'event-1')
    const user = userEvent.setup()
    renderInspector()

    await user.click(screen.getByRole('button', { name: 'Add to playlist' }))

    const recent = await screen.findByText('Recent')
    expect(recent.closest('.action-group')?.textContent).toContain('Festival set')
    const entries = Array.from(document.querySelectorAll<HTMLButtonElement>('#track-actions button[data-action-entry]:not(.action-back)'))
    expect(entries[0].textContent).toBe('Festival set')
    expect(screen.getAllByRole('button', { name: 'Festival set' })).toHaveLength(1)
  })

  it('likes the selected tracks in TIDAL', async () => {
    const user = userEvent.setup()
    renderInspector()
    await user.click(screen.getByRole('button', { name: 'Like in TIDAL' }))

    await waitFor(() => expect(screen.getByText('Liked 1 track in TIDAL.')).toBeTruthy())
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(([url]) => String(url).endsWith('/tracks/like'))
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ track_ids: ['track-1'] })
  })

  it('sends only the selected local IDs and destination when a destination is chosen', async () => {
    const user = userEvent.setup()
    renderInspector()
    await user.click(screen.getByRole('button', { name: 'Add to playlist' }))
    await user.click(await screen.findByRole('button', { name: 'Festival set' }))

    await waitFor(() => expect(screen.getByText('Added 1 track.')).toBeTruthy())
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(([url]) => String(url).endsWith('/tracks/playlist-action'))
    expect(call).toBeTruthy()
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      action: 'add', track_ids: ['track-1'], playlist_id: 'event-1', source_playlist_id: null,
    })
  })

  it('hands keyboard focus to a destination after opening Remove from playlist', async () => {
    const user = userEvent.setup()
    const memberTrack: Track = {
      ...track,
      playlists: [{ id: 'playlist-1', name: 'Normal playlist' }],
      events: [{ id: 'event-1', name: 'Festival set' }],
      sources: [{ id: 'source-1', name: 'Shazam source' }],
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Inspector track={memberTrack} selectedTracks={[memberTrack]} queryKey={['tracks']} collapsedDefault collectionType="playlist" collectionId="source-playlist" />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const actions = document.getElementById('track-actions')!
    actions.focus()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Like in TIDAL' }))

    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    const destination = await screen.findByRole('button', { name: 'Normal playlist' })
    await waitFor(() => expect(document.activeElement).toBe(destination))
  })

  it('includes the currently open playlist as a Remove destination even when memberships hide it', async () => {
    const user = userEvent.setup()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Inspector track={track} selectedTracks={[track]} queryKey={['tracks']} collapsedDefault collectionType="playlist" collectionId="playlist-1" />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'Remove from playlist' }))

    expect(await screen.findByRole('button', { name: 'Normal playlist' })).toBeTruthy()
  })

  it('moves Left from Actions back to the track list', async () => {
    const user = userEvent.setup()
    const trackList = document.createElement('section')
    trackList.dataset.trackBrowserRoot = 'true'
    trackList.tabIndex = 0
    document.body.append(trackList)
    renderInspector()

    document.getElementById('track-actions')!.focus()
    await user.keyboard('{ArrowLeft}')

    expect(document.activeElement).toBe(trackList)
    trackList.remove()
  })
})
