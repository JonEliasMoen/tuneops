export type NumericColorScale = {
  min: number
  average: number
  max: number
}

export function numericColorScale(values: Array<number | null | undefined>): NumericColorScale | null {
  const numbers = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  if (!numbers.length) return null
  return {
    min: Math.min(...numbers),
    average: numbers.reduce((total, value) => total + value, 0) / numbers.length,
    max: Math.max(...numbers),
  }
}

export function numericScalePosition(value: number, scale: NumericColorScale): number {
  if (value === scale.average) return 0
  if (value < scale.average) {
    const span = scale.average - scale.min
    return span > 0 ? Math.max(-1, (value - scale.average) / span) : 0
  }
  const span = scale.max - scale.average
  return span > 0 ? Math.min(1, (value - scale.average) / span) : 0
}

export function numericScaleColor(value: number | null | undefined, scale: NumericColorScale | null): string | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || !scale) return undefined
  const position = numericScalePosition(value, scale)
  const hue = position < 0 ? 48 + (position * 43) : 48 + (position * 92)
  const strength = 0.12 + Math.abs(position) * 0.18
  return `hsl(${hue.toFixed(1)} 72% 48% / ${strength.toFixed(3)})`
}
