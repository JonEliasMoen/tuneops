import { useSyncExternalStore } from 'react'

let tagsOpen: boolean | undefined
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot() {
  return tagsOpen
}

export function useTagsPanel(defaultCollapsed: boolean) {
  const stored = useSyncExternalStore(subscribe, snapshot, snapshot)
  const open = stored ?? !defaultCollapsed
  const setOpen = (value: boolean) => {
    tagsOpen = value
    listeners.forEach((listener) => listener())
  }
  return [open, setOpen] as const
}
