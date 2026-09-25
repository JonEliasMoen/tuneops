import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'

const navigation = {
  tools: [
    { id: 'liked', label: 'Liked tracks', path: '/liked-tracks', kind: 'tool', icon: '♥' },
    { id: 'search', label: 'Global search', path: '/search', kind: 'tool', icon: '⌕' },
  ],
  groups: [
    {
      id: 'playlists', label: 'Playlists', items: [
        { id: 'deep', label: 'Deep groove', path: '/playlists/deep', kind: 'playlist', icon: '♫' },
        { id: 'peak', label: 'Peak techno', path: '/playlists/peak', kind: 'playlist', icon: '♫' },
      ],
    },
    {
      id: 'events', label: 'Events', items: [
        { id: 'festival', label: 'Festival', path: '/events/festival', kind: 'event', icon: '♫' },
      ],
    },
  ],
}

function RouteName() {
  return <output data-testid="route">{useLocation().pathname}</output>
}

function renderSidebar(initialPath = '/liked-tracks') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
        <RouteName />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sidebar keyboard navigation', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => navigation }))
    if (!globalThis.CSS) vi.stubGlobal('CSS', { escape: (value: string) => value })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('moves through collapsed groups, opens one, enters a child, and returns to its parent', async () => {
    const user = userEvent.setup()
    renderSidebar()
    const playlists = await screen.findByRole('button', { name: /Playlists/ })
    const events = screen.getByRole('button', { name: /Events/ })

    playlists.focus()
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(events)
    await user.keyboard('{ArrowUp}{ArrowRight}')
    expect(playlists.getAttribute('aria-expanded')).toBe('true')

    await user.keyboard('{ArrowDown}')
    const deepGroove = screen.getByRole('link', { name: /Deep groove/ })
    expect(document.activeElement).toBe(deepGroove)
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => expect(playlists.getAttribute('aria-expanded')).toBe('false'))
    expect(document.activeElement).toBe(playlists)
  })

  it('uses right arrow on a selected sidebar item to navigate into it', async () => {
    const user = userEvent.setup()
    renderSidebar()
    const playlists = await screen.findByRole('button', { name: /Playlists/ })
    playlists.focus()
    await user.keyboard('{ArrowRight}{ArrowDown}{ArrowRight}')

    await waitFor(() => expect(screen.getByTestId('route').textContent).toBe('/playlists/deep'))
    expect(sessionStorage.getItem('musicsync.react.focus-track-list')).toBe('/playlists/deep')
  })

  it('uses either Enter or Right Arrow on direct track tools and records the focus handoff', async () => {
    const user = userEvent.setup()
    renderSidebar('/search')
    const likedTracks = await screen.findByRole('link', { name: /Liked tracks/ })
    likedTracks.focus()
    await user.keyboard('{Enter}')

    await waitFor(() => expect(screen.getByTestId('route').textContent).toBe('/liked-tracks'))
    expect(sessionStorage.getItem('musicsync.react.focus-track-list')).toBe('/liked-tracks')
  })
})
