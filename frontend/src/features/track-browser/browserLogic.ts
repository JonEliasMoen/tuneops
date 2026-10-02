import type { SortState } from './viewState'

export type SelectionState = {
  selectedIds: string[]
  anchorId: string | null
  lastRangeIndex: number | null
}

export function selectTrackRange(
  trackIds: string[],
  index: number,
  lastRangeIndex: number | null,
  extend: boolean,
): SelectionState {
  const trackId = trackIds[index]
  if (!trackId) return { selectedIds: [], anchorId: null, lastRangeIndex }
  if (extend && lastRangeIndex !== null) {
    const [start, end] = [lastRangeIndex, index].sort((left, right) => left - right)
    return {
      selectedIds: trackIds.slice(start, end + 1),
      anchorId: trackId,
      lastRangeIndex,
    }
  }
  return { selectedIds: [trackId], anchorId: trackId, lastRangeIndex: index }
}

export function nextSort(current: SortState, field: string): SortState {
  if (!current || current.field !== field) return { field, direction: 'asc' }
  if (current.direction === 'asc') return { field, direction: 'desc' }
  return null
}

export function normalizeQuickViewFields(fields: string[], allowedFields: string[]): string[] {
  const allowed = new Set(allowedFields)
  const normalized = [...new Set(fields)].filter((field) => allowed.has(field))
  return normalized.length ? normalized : ['title', 'artist']
}
