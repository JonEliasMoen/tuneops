export type SortState = { field: string; direction: 'asc' | 'desc' } | null

export type BrowserFilters = {
  query: string
  artist: string
  key: string
  rating: string
  tag: string
  collectionType: string
  bpmMin: string
  bpmMax: string
}

export type BrowserState = {
  sort: SortState
  visibleFields: string[]
  selectedId: string | null
  scrollTop: number
  loaded: number
  filters: BrowserFilters
}

type StoredState = {
  global?: { sort?: SortState; visibleFields?: string[]; filters?: Partial<BrowserFilters> }
  collections?: Record<string, Partial<BrowserState>>
}

const KEY = 'musicsync.react.track-view.v1'

function read(): StoredState {
  try { return JSON.parse(sessionStorage.getItem(KEY) || '{}') }
  catch { return {} }
}

function write(state: StoredState) {
  sessionStorage.setItem(KEY, JSON.stringify(state))
}

export function loadBrowserState(collectionKey: string, defaults: BrowserState): BrowserState {
  const stored = read()
  return {
    ...defaults,
    ...(stored.global ?? {}),
    ...(stored.collections?.[collectionKey] ?? {}),
    filters: { ...defaults.filters, ...(stored.global?.filters ?? {}) },
  }
}

export function saveBrowserState(collectionKey: string, state: BrowserState) {
  const stored = read()
  stored.global = { sort: state.sort, visibleFields: state.visibleFields, filters: state.filters }
  stored.collections = {
    ...(stored.collections ?? {}),
    [collectionKey]: {
      selectedId: state.selectedId,
      scrollTop: state.scrollTop,
      loaded: Math.min(1000, Math.max(200, state.loaded)),
    },
  }
  write(stored)
}
