import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PlaylistSyncPage } from './PlaylistSyncPage'


describe('PlaylistSyncPage autosave', () => {
  const writes: Array<{ playlists: Array<Record<string, unknown>> }> = []

  beforeEach(() => {
    writes.length = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      let payload: unknown = []
      if (url.endsWith('/health')) payload = { providers: {} }
      if (url.endsWith('/sync/mappings') && init?.method !== 'PUT') payload = {
        playlists: [{
          _mapping_id: 'mapping-1', enabled: true, name: 'Original',
          direction: 'tidal_cache', collection_type: 'playlist',
          spotify: '', tidal: 'tidal-id', tidal_name: '',
        }],
      }
      if (url.endsWith('/sync/mappings') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        payload = body
      }
      return { ok: true, json: async () => payload }
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('saves edited mappings automatically without a normal save button', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><PlaylistSyncPage /></QueryClientProvider>)

    const name = await screen.findByDisplayValue('Original')
    expect(screen.queryByRole('button', { name: 'Save mappings' })).toBeNull()
    fireEvent.change(name, { target: { value: 'Autosaved' } })

    await waitFor(() => expect(writes).toHaveLength(1), { timeout: 2000 })
    expect(writes[0].playlists[0].name).toBe('Autosaved')
    await screen.findByText('Saved automatically.')
  })

  it('creates new mappings above the existing mappings', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><PlaylistSyncPage /></QueryClientProvider>)

    await screen.findByDisplayValue('Original')
    fireEvent.click(screen.getByRole('button', { name: 'Add mapping' }))

    const names = screen.getAllByLabelText('Mapping name') as HTMLInputElement[]
    expect(names).toHaveLength(2)
    expect(names[0].value).toBe('')
    expect(names[1].value).toBe('Original')
  })
})
