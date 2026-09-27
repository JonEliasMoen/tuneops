import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadTemporaryState, saveTemporaryState } from './watchedMixState'

describe('temporary watched-mix state', () => {
  afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })

  it('restores recently saved staging state', () => {
    saveTemporaryState('staging', { rows: [1, 2] })
    expect(loadTemporaryState('staging', { rows: [] })).toEqual({ rows: [1, 2] })
  })

  it('drops staging state after one day', () => {
    sessionStorage.setItem('staging', JSON.stringify({ savedAt: Date.now() - 25 * 60 * 60 * 1000, value: { rows: [1] } }))
    expect(loadTemporaryState('staging', { rows: [] })).toEqual({ rows: [] })
    expect(sessionStorage.getItem('staging')).toBeNull()
  })
})
