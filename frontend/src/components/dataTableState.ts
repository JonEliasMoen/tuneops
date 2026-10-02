import { useEffect, useState, type KeyboardEvent } from 'react'

export type TableSort<Field extends string> = { field: Field; direction: 'asc' | 'desc' } | null

export function nextTableSort<Field extends string>(current: TableSort<Field>, field: Field): TableSort<Field> {
  if (!current || current.field !== field) return { field, direction: 'asc' }
  if (current.direction === 'asc') return { field, direction: 'desc' }
  return null
}

export function usePersistentTableSort<Field extends string>(storageKey: string, fallback: TableSort<Field>) {
  const [sort, setSort] = useState<TableSort<Field>>(() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null') as TableSort<Field>
      return stored && typeof stored.field === 'string' && ['asc', 'desc'].includes(stored.direction) ? stored : fallback
    } catch {
      return fallback
    }
  })
  useEffect(() => { sessionStorage.setItem(storageKey, JSON.stringify(sort)) }, [sort, storageKey])
  return [sort, setSort] as const
}

export function useTableKeyboardNavigation<Row>(rows: Row[], rowKey: (row: Row) => string, onActivate: (row: Row) => void) {
  const [selectedKey, setSelectedKey] = useState('')
  useEffect(() => {
    if (selectedKey && !rows.some((row) => rowKey(row) === selectedKey)) setSelectedKey('')
  }, [rows, rowKey, selectedKey])

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!rows.length || ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A'].includes((event.target as HTMLElement).tagName)) return
    const current = rows.findIndex((row) => rowKey(row) === selectedKey)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const start = current < 0 ? (event.key === 'ArrowDown' ? 0 : rows.length - 1) : current
      const index = Math.max(0, Math.min(rows.length - 1, start + (current < 0 ? 0 : event.key === 'ArrowDown' ? 1 : -1)))
      setSelectedKey(rowKey(rows[index]))
    } else if ((event.key === 'Enter' || event.key === 'ArrowRight') && current >= 0) {
      event.preventDefault()
      onActivate(rows[current])
    }
  }

  return { selectedKey, setSelectedKey, onKeyDown }
}
