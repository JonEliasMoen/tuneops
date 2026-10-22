import { describe, expect, it } from 'vitest'
import { nextTableSort } from './dataTableState'

describe('shared data-table state', () => {
  it('cycles ascending, descending, then off', () => {
    expect(nextTableSort(null, 'title')).toEqual({ field: 'title', direction: 'asc' })
    expect(nextTableSort({ field: 'title', direction: 'asc' }, 'title')).toEqual({ field: 'title', direction: 'desc' })
    expect(nextTableSort({ field: 'title', direction: 'desc' }, 'title')).toBeNull()
  })

  it('starts with the configured descending direction', () => {
    const descending = nextTableSort(null, 'title', 'desc')
    expect(descending).toEqual({ field: 'title', direction: 'desc' })
    expect(nextTableSort(descending, 'title', 'desc')).toEqual({ field: 'title', direction: 'asc' })
    expect(nextTableSort({ field: 'title', direction: 'asc' }, 'title', 'desc')).toBeNull()
  })
})
