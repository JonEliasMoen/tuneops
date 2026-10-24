import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MyMixSettingsPage } from './MyMixSettingsPage'

describe('MyMixSettingsPage', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists persisted mixes and starts explicit TIDAL discovery', async () => {
    const requests: Array<{ url: string; method: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      requests.push({ url, method })
      let payload: unknown = {}
      if (url.endsWith('/settings/my-mixes')) payload = { items: [{ internal_name: 'darkprog', expected_tidal_name: 'djset darkprog', tidal_playlist_id: '', tidal_playlist_name: '', track_count: 0, status: 'not_discovered' }] }
      if (url.endsWith('/mixes/discover-tidal')) payload = { id: 'discovery', kind: 'mix-tidal-discovery', state: 'queued', message: '', current: 0, total: null, result: null, error: '', created_at: 'now' }
      if (url.endsWith('/jobs/discovery')) payload = { id: 'discovery', kind: 'mix-tidal-discovery', state: 'succeeded', message: 'Discovery complete: 1 new of 1 djset playlists imported', current: 2, total: null, result: {}, error: '', created_at: 'now' }
      return { ok: true, json: async () => payload }
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><MyMixSettingsPage /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('djset darkprog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Discover automatically' }))

    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/mixes/discover-tidal') && request.method === 'POST')).toBe(true))
    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/jobs/discovery'))).toBe(true))
  })
})
