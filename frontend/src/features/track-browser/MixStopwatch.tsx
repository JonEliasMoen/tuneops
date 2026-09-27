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

type StopwatchState = { elapsed: number; running: boolean; started: boolean; savedAt: number }

function restoredStopwatch(key?: string): StopwatchState {
  if (!key) return { elapsed: 0, running: false, started: false, savedAt: Date.now() }
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null') as StopwatchState | null
    if (!value || Date.now() - value.savedAt > 24 * 60 * 60 * 1000) return { elapsed: 0, running: false, started: false, savedAt: Date.now() }
    return { ...value, elapsed: value.elapsed + (value.running ? Date.now() - value.savedAt : 0) }
  } catch {
    return { elapsed: 0, running: false, started: false, savedAt: Date.now() }
  }
}

export function MixStopwatch({ rows, onActiveTrackChange, storageKey }: {
  rows: Array<{ id: string; mix_position?: string }>
  onActiveTrackChange: (trackId: string | null) => void
  storageKey?: string
}) {
  const timestamps = useMemo(
    () => rows.map((row) => ({ id: row.id, seconds: parseSeconds(row.mix_position) })).filter((row): row is { id: string; seconds: number } => row.seconds !== null),
    [rows],
  )
  const initial = useMemo(() => restoredStopwatch(storageKey), [storageKey])
  const [elapsed, setElapsed] = useState(initial.elapsed)
  const [running, setRunning] = useState(initial.running)
  const [started, setStarted] = useState(initial.started)
  const [startValue, setStartValue] = useState(formatElapsed(initial.elapsed).replace(/\.\d$/, ''))
  const startedAt = useRef(performance.now())
  const pausedElapsed = useRef(initial.elapsed)

  useEffect(() => {
    const restored = restoredStopwatch(storageKey)
    pausedElapsed.current = restored.elapsed
    startedAt.current = performance.now()
    setElapsed(restored.elapsed)
    setRunning(restored.running)
    setStarted(restored.started)
    setStartValue(formatElapsed(restored.elapsed).replace(/\.\d$/, ''))
  }, [storageKey])

  useEffect(() => {
    if (!running) return
    const interval = window.setInterval(() => {
      const current = pausedElapsed.current + performance.now() - startedAt.current
      setElapsed(current)
      if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify({ elapsed: current, running: true, started: true, savedAt: Date.now() } satisfies StopwatchState))
    }, 100)
    return () => window.clearInterval(interval)
  }, [running, storageKey])

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
      if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify({ elapsed: pausedElapsed.current, running: false, started: true, savedAt: Date.now() } satisfies StopwatchState))
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
    setStartValue('00:00')
    if (storageKey) sessionStorage.removeItem(storageKey)
    onActiveTrackChange(null)
  }

  function setStartTime() {
    const seconds = parseSeconds(startValue)
    if (seconds === null) return
    const milliseconds = seconds * 1000
    pausedElapsed.current = milliseconds
    startedAt.current = performance.now()
    setElapsed(milliseconds)
    setStarted(true)
    if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify({ elapsed: milliseconds, running, started: true, savedAt: Date.now() } satisfies StopwatchState))
  }

  return <div className="mix-stopwatch">
    <span className="mix-stopwatch-time">{formatElapsed(elapsed)}</span>
    <button type="button" className="primary" onClick={toggle}>{running ? 'Pause' : started ? 'Resume' : 'Start'}</button>
    <button type="button" onClick={stop} disabled={!started}>Stop</button>
    <label className="stopwatch-start">Start time<input aria-label="Stopwatch start time" value={startValue} onChange={(event) => setStartValue(event.target.value)} placeholder="00:00" /></label>
    <button type="button" onClick={setStartTime} disabled={parseSeconds(startValue) === null}>Set</button>
    <span className="hint">Rows with Time are highlighted while they play.</span>
  </div>
}
