import { describe, expect, it } from 'vitest'
import { nextSort, normalizeQuickViewFields, selectTrackRange } from './browserLogic'

describe('track selection', () => {
  const tracks = ['one', 'two', 'three', 'four']

  it('selects one row and establishes the shift-selection anchor', () => {
    expect(selectTrackRange(tracks, 1, null, false)).toEqual({
      selectedIds: ['two'], anchorId: 'two', lastRangeIndex: 1,
    })
  })

  it('extends selection in either direction without moving the range anchor', () => {
    expect(selectTrackRange(tracks, 3, 1, true)).toEqual({
      selectedIds: ['two', 'three', 'four'], anchorId: 'four', lastRangeIndex: 1,
    })
    expect(selectTrackRange(tracks, 0, 2, true)).toEqual({
      selectedIds: ['one', 'two', 'three'], anchorId: 'one', lastRangeIndex: 2,
    })
  })
})

describe('sort and Quick View transitions', () => {
  it('cycles ascending, descending, then off', () => {
    const ascending = nextSort(null, 'date_added')
    const descending = nextSort(ascending, 'date_added')
    expect(ascending).toEqual({ field: 'date_added', direction: 'asc' })
    expect(descending).toEqual({ field: 'date_added', direction: 'desc' })
    expect(nextSort(descending, 'date_added')).toBeNull()
  })

  it('deduplicates Quick View fields and ignores removed column keys', () => {
    expect(normalizeQuickViewFields(
      ['title', 'rating', 'rating', 'obsolete'],
      ['title', 'artist', 'rating'],
    )).toEqual(['title', 'rating'])
    expect(normalizeQuickViewFields(['obsolete'], ['title', 'artist'])).toEqual(['title', 'artist'])
  })
})
