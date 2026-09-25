import { useEffect, useMemo, useRef, useState } from 'react'

export function parseSeconds(value: string | undefined): number | null {
  const parts = String(value || '').trim().replace(/^\[/, '').replace(/\]$/, '').split(':')
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) return null
  return parts.reduce((total, part) => total * 60 + Number(part), 0)
}

export function formatElapsed(milliseconds: number) {
  const tenths = Math.floor(Math.max(0, milliseconds) / 100)
  const totalSeconds = Math.floor(tenths / 10)
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  const minutes = totalMinutes % 60
  const hours = Math.floor(totalMinutes / 60)
  const base = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${tenths % 10}`
  return hours ? `${hours}:${base}` : base
}

export function activeTrackIdAt(
  timestamps: Array<{ id: string; seconds: number }>,
  elapsedSeconds: number,
): string | null {
  return timestamps.reduce<{ id: string; seconds: number } | null>(
    (active, row) => row.seconds <= elapsedSeconds && (!active || row.seconds >= active.seconds) ? row : active,
    null,
  )?.id ?? null
}

export function MixStopwatch({ rows, onActiveTrackChange }: {
  rows: Array<{ id: string; mix_position?: string }>
  onActiveTrackChange: (trackId: string | null) => void
}) {
  const timestamps = useMemo(
    () => rows.map((row) => ({ id: row.id, seconds: parseSeconds(row.mix_position) })).filter((row): row is { id: string; seconds: number } => row.seconds !== null),
    [rows],
  )
  const [elapsed, setElapsed] = useState(0)
  const [running, setRunning] = useState(false)
  const [started, setStarted] = useState(false)
  const startedAt = useRef(0)
  const pausedElapsed = useRef(0)

  useEffect(() => {
    if (!running) return
    const interval = window.setInterval(() => setElapsed(pausedElapsed.current + performance.now() - startedAt.current), 100)
    return () => window.clearInterval(interval)
  }, [running])

  useEffect(() => {
    if (!started) {
      onActiveTrackChange(null)
      return
    }
    const seconds = elapsed / 1000
    onActiveTrackChange(activeTrackIdAt(timestamps, seconds))
  }, [elapsed, started, timestamps, onActiveTrackChange])

  if (!timestamps.length) return null

  function toggle() {
    if (running) {
      pausedElapsed.current += performance.now() - startedAt.current
      setElapsed(pausedElapsed.current)
      setRunning(false)
      return
    }
    startedAt.current = performance.now()
    setStarted(true)
    setRunning(true)
  }

  function stop() {
    pausedElapsed.current = 0
    startedAt.current = 0
    setElapsed(0)
    setStarted(false)
    setRunning(false)
    onActiveTrackChange(null)
  }

  return <div className="mix-stopwatch">
    <span className="mix-stopwatch-time">{formatElapsed(elapsed)}</span>
    <button type="button" className="primary" onClick={toggle}>{running ? 'Pause' : started ? 'Resume' : 'Start'}</button>
    <button type="button" onClick={stop} disabled={!started}>Stop</button>
    <span className="hint">Rows with Time are highlighted while they play.</span>
  </div>
}
