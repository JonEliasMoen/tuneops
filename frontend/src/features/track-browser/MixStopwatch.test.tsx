import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MixStopwatch, activeTrackIdAt, formatElapsed, parseSeconds } from './MixStopwatch'

describe('mix stopwatch timing', () => {
  afterEach(() => vi.restoreAllMocks())

  it('parses mix timestamps and formats elapsed time consistently', () => {
    expect(parseSeconds('[01:02:03.5]')).toBe(3723.5)
    expect(parseSeconds('07:20')).toBe(440)
    expect(parseSeconds('not a timestamp')).toBeNull()
    expect(formatElapsed(0)).toBe('00:00.0')
    expect(formatElapsed(3_723_500)).toBe('1:02:03.5')
  })

  it('selects the latest track whose timestamp has started', () => {
    const timestamps = [{ id: 'intro', seconds: 0 }, { id: 'second', seconds: 440 }, { id: 'third', seconds: 734 }]
    expect(activeTrackIdAt(timestamps, -1)).toBeNull()
    expect(activeTrackIdAt(timestamps, 0)).toBe('intro')
    expect(activeTrackIdAt(timestamps, 500)).toBe('second')
    expect(activeTrackIdAt(timestamps, 734)).toBe('third')
  })

  it('resets the active track when stopped', () => {
    const onActiveTrackChange = vi.fn()
    render(<MixStopwatch rows={[{ id: 'intro', mix_position: '00:00' }]} onActiveTrackChange={onActiveTrackChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))

    expect(onActiveTrackChange).toHaveBeenLastCalledWith(null)
    expect((screen.getByRole('button', { name: 'Stop' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
