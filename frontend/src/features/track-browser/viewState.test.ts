import { beforeEach, describe, expect, it } from 'vitest'
import { loadBrowserState, saveBrowserState, type BrowserState } from './viewState'

const defaults: BrowserState = {
  sort: null,
  visibleFields: ['title', 'artist'],
  selectedId: null,
  scrollTop: 0,
  loaded: 200,
  filters: {
    query: '', artist: '', key: '', rating: '', tag: '', collectionType: '', bpmMin: '', bpmMax: '',
  },
}

describe('track browser view state', () => {
  beforeEach(() => sessionStorage.clear())

  it('keeps shared fields, sorting, and filters when opening another collection', () => {
    saveBrowserState('playlist:first', {
      ...defaults,
      sort: { field: 'date_added', direction: 'desc' },
      visibleFields: ['title', 'artist', 'rating'],
      filters: { ...defaults.filters, query: 'marsh', tag: 'vibe:Dreamy' },
    })

    const restored = loadBrowserState('playlist:second', defaults)
    expect(restored.sort).toEqual({ field: 'date_added', direction: 'desc' })
    expect(restored.visibleFields).toEqual(['title', 'artist', 'rating'])
    expect(restored.filters).toMatchObject({ query: 'marsh', tag: 'vibe:Dreamy' })
    expect(restored.selectedId).toBeNull()
  })

  it('restores a collection-specific selection, scroll position, and capped loaded rows', () => {
    saveBrowserState('playlist:darkprog', {
      ...defaults,
      selectedId: 'tidal-123',
      scrollTop: 840,
      loaded: 5_000,
    })

    const restored = loadBrowserState('playlist:darkprog', defaults)
    expect(restored.selectedId).toBe('tidal-123')
    expect(restored.scrollTop).toBe(840)
    expect(restored.loaded).toBe(1_000)
  })

  it('does not leak a selection or scroll position into another collection', () => {
    saveBrowserState('playlist:first', {
      ...defaults,
      selectedId: 'tidal-123',
      scrollTop: 840,
      loaded: 600,
    })

    const restored = loadBrowserState('playlist:second', defaults)
    expect(restored.selectedId).toBeNull()
    expect(restored.scrollTop).toBe(0)
    expect(restored.loaded).toBe(200)
  })
})
