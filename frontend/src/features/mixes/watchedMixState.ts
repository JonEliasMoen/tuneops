const MAX_AGE_MS = 24 * 60 * 60 * 1000

type Stored<T> = { savedAt: number; value: T }

export function loadTemporaryState<T>(key: string, fallback: T): T {
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || 'null') as Stored<T> | null
    if (!stored || Date.now() - stored.savedAt > MAX_AGE_MS) {
      sessionStorage.removeItem(key)
      return fallback
    }
    return stored.value
  } catch {
    sessionStorage.removeItem(key)
    return fallback
  }
}

export function saveTemporaryState<T>(key: string, value: T) {
  sessionStorage.setItem(key, JSON.stringify({ savedAt: Date.now(), value } satisfies Stored<T>))
}
