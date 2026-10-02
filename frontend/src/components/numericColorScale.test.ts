import { describe, expect, it } from 'vitest'
import { numericColorScale, numericScaleColor, numericScalePosition } from './numericColorScale'

describe('numeric color scale', () => {
  it('uses min, arithmetic average, and max as anchors', () => {
    const scale = numericColorScale([10, 20, 60, null])
    expect(scale).toEqual({ min: 10, average: 30, max: 60 })
    expect(numericScalePosition(10, scale!)).toBe(-1)
    expect(numericScalePosition(30, scale!)).toBe(0)
    expect(numericScalePosition(60, scale!)).toBe(1)
  })

  it('handles empty and flat inputs safely', () => {
    expect(numericColorScale([null, undefined])).toBeNull()
    const flat = numericColorScale([5, 5])!
    expect(numericScalePosition(5, flat)).toBe(0)
    expect(numericScaleColor(null, flat)).toBeUndefined()
  })
})
