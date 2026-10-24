import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
  afterEach(() => vi.useRealTimers())

  it('publishes only the final value after the quiet period', () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 350),
      { initialProps: { value: '' } },
    )

    rerender({ value: 'm' })
    act(() => vi.advanceTimersByTime(200))
    rerender({ value: 'marsh' })
    act(() => vi.advanceTimersByTime(349))
    expect(result.current).toBe('')

    act(() => vi.advanceTimersByTime(1))
    expect(result.current).toBe('marsh')
  })
})
