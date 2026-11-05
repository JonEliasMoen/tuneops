import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ChartDetailPage, ChartsOverviewPage } from './ChartsPages'

function response(value: object) {
  return Promise.resolve({ ok: true, json: async () => value })
}

function renderPage(element: ReactNode, path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/charts" element={element} />
          <Route path="/charts/:type/:id" element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Beatport chart navigation', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/charts/search')) return response({
        items: [{ type: 'genres', id: '12', name: 'Progressive House' }],
      })
      if (url.includes('/charts/genres/12')) return response({
        chart: { type: 'genres', id: '12', name: 'Progressive House' },
        mode: 'top', offset: 0, limit: 10, total: 1, has_more: false,
        items: [{
          position: 1, id: 'track-1', title: 'Track', artists: 'Artist',
          artist_refs: [{ id: '84', name: 'Artist' }],
          label: 'Colorize', label_id: '42',
          genre: 'Progressive House', genre_id: '12',
        }],
      })
      if (url.endsWith('/charts')) return response({ items: [] })
      if (url.endsWith('/settings')) return response({ tags_collapsed_by_default: true })
      if (url.endsWith('/dimensions')) return response({ values: {}, labels: {}, max_values: {} })
      return response({})
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('links overview search results to an unfollowed chart page', async () => {
    const user = userEvent.setup()
    renderPage(<ChartsOverviewPage />, '/charts')

    await user.type(screen.getByLabelText('Search Beatport'), 'Progressive')

    const link = await screen.findByRole('link', { name: /Progressive House/ })
    expect(link.getAttribute('href')).toBe('/charts/genres/12')
  })

  it('links track artists, labels, and genres to their chart pages', async () => {
    renderPage(<ChartDetailPage />, '/charts/genres/12')

    expect(await screen.findByText('Not followed')).toBeTruthy()
    expect((await screen.findByRole('link', { name: 'Artist' })).getAttribute('href')).toBe('/charts/artists/84')
    expect(screen.getByRole('link', { name: 'Colorize' }).getAttribute('href')).toBe('/charts/labels/42')
    expect(screen.getByRole('link', { name: 'Progressive House' }).getAttribute('href')).toBe('/charts/genres/12')
  })
})
