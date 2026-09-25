import { describe, expect, it, vi } from 'vitest'
import { keepRowVisible } from './TrackBrowser'

function rect(top: number, bottom: number): DOMRect {
  return { top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }
}

describe('track selection scroll containment', () => {
  it('scrolls only the table viewport when the selected row is below it', () => {
    const viewport = document.createElement('div')
    const row = document.createElement('tr')
    viewport.scrollTop = 100
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue(rect(100, 500))
    vi.spyOn(row, 'getBoundingClientRect').mockReturnValue(rect(550, 580))

    keepRowVisible(viewport, row)

    expect(viewport.scrollTop).toBe(180)
  })

  it('does not scroll when the selected row is already visible', () => {
    const viewport = document.createElement('div')
    const row = document.createElement('tr')
    viewport.scrollTop = 100
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue(rect(100, 500))
    vi.spyOn(row, 'getBoundingClientRect').mockReturnValue(rect(200, 230))

    keepRowVisible(viewport, row)

    expect(viewport.scrollTop).toBe(100)
  })
})
