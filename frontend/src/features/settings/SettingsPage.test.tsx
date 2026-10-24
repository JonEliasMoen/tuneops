import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from './SettingsPage'


const initialSettings = {
  dark_mode: true,
  tags_collapsed_by_default: true,
  default_sort_direction: 'asc' as const,
  lastfm_username: 'Aruzhu',
  history_top_tracks: 20,
  spotify_search_delay_seconds: 0.75,
  quick_views: [],
  mix_quick_views: [],
  lastfm_api_key_configured: true,
}


describe('SettingsPage autosave', () => {
  const writes: typeof initialSettings[] = []

  beforeEach(() => {
    writes.length = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      let payload: unknown = {}
      if (url.endsWith('/settings') && init?.method !== 'PATCH') payload = initialSettings
      if (url.endsWith('/settings') && init?.method === 'PATCH') {
        payload = JSON.parse(String(init.body))
        writes.push(payload as typeof initialSettings)
      }
      if (url.endsWith('/youtube/status')) payload = { configured: false, connected: false }
      if (url.endsWith('/settings/orphaned-tracks')) payload = { items: [], total: 0, offset: 0, limit: 250, has_more: false }
      return { ok: true, json: async () => payload }
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('autosaves settings and has no normal save button', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)

    const username = await screen.findByDisplayValue('Aruzhu')
    expect(screen.queryByRole('button', { name: 'Save settings' })).toBeNull()
    fireEvent.change(username, { target: { value: 'UpdatedUser' } })

    await waitFor(() => expect(writes).toHaveLength(1), { timeout: 2000 })
    expect(writes[0].lastfm_username).toBe('UpdatedUser')
    await screen.findByText('Saved automatically.')
  })

  it('offers the standalone VirtualDJ companion as a direct download', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)

    const link = await screen.findByRole('link', { name: 'Download VirtualDJ companion' })
    expect(link.getAttribute('href')).toBe('/downloads/virtualdj-companion/tuneops_virtualdj.py')
    expect(link.getAttribute('download')).toBe('tuneops_virtualdj.py')
  })

  it('links to My Mixes discovery settings', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>)

    const link = await screen.findByRole('link', { name: 'Open My Mixes settings' })
    expect(link.getAttribute('href')).toBe('/settings/my-mixes')
  })
})
