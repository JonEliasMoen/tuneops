import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { Navigation } from '../api/types'

function isEditing(target: EventTarget | null) {
  const element = target as HTMLElement | null
  return Boolean(element?.closest('input, textarea, select, [contenteditable="true"], [role="listbox"]'))
}

function isTrackRoute(path: string | undefined) {
  return Boolean(path && (path === '/liked-tracks' || path === '/search' || path === '/artists' || path === '/mixes' || /^\/(playlists|events|sources|mixes|watched-mixes|artists|history)\//.test(path)))
}

export function Sidebar() {
  const { pathname } = useLocation()
  const sidebarRef = useRef<HTMLElement>(null)
  const navigation = useQuery({ queryKey: ['navigation'], queryFn: () => api<Navigation>('/navigation') })
  const initialOpen = useMemo(
    () => {
      const open = new Set<string>()
      for (const group of navigation.data?.groups ?? []) {
        for (const item of group.items) {
          if (item.path === pathname || item.children?.some((child) => child.path === pathname)) open.add(group.id)
          if (item.children?.some((child) => child.path === pathname)) open.add(`${group.id}:${item.id}`)
        }
      }
      return open
    },
    [navigation.data, pathname],
  )
  const [openOverrides, setOpenOverrides] = useState<Record<string, boolean>>({})
  const isOpen = (groupId: string) => openOverrides[groupId] ?? initialOpen.has(groupId)

  function activateLink(link: HTMLAnchorElement) {
    const path = link.dataset.path
    if (isTrackRoute(path)) sessionStorage.setItem('musicsync.react.focus-track-list', path!)
    link.click()
  }

  useEffect(() => {
    const enterSidebar = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowLeft' || isEditing(event.target) || sidebarRef.current?.contains(document.activeElement)) return
      const entries = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('[data-nav-entry]') ?? [])
      const target = entries.find((entry) => entry.dataset.path === pathname) ?? entries[0]
      if (target) {
        event.preventDefault()
        target.focus()
      }
    }
    window.addEventListener('keydown', enterSidebar)
    return () => window.removeEventListener('keydown', enterSidebar)
  }, [pathname, navigation.data])

  function handleKeys(event: React.KeyboardEvent<HTMLElement>) {
    if (isEditing(event.target)) return
    const entries = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('[data-nav-entry]') ?? [])
    const index = entries.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      entries[Math.max(0, Math.min(entries.length - 1, index + delta))]?.focus()
      return
    }
    const current = document.activeElement as HTMLElement | null
    const groupId = current?.dataset.group
    const nestedId = current?.dataset.nested
    if (nestedId && current?.dataset.nestedParent === 'true' && (event.key === 'Enter' || event.key === 'ArrowRight')) {
      event.preventDefault()
      setOpenOverrides((previous) => ({ ...previous, [nestedId]: event.key === 'Enter' && isOpen(nestedId) ? false : true }))
      return
    }
    if (nestedId && current?.dataset.nestedChild === 'true' && event.key === 'ArrowLeft') {
      event.preventDefault()
      setOpenOverrides((previous) => ({ ...previous, [nestedId]: false }))
      requestAnimationFrame(() => sidebarRef.current?.querySelector<HTMLElement>(`[data-nested="${CSS.escape(nestedId)}"][data-nested-parent="true"]`)?.focus())
      return
    }
    if (groupId && current?.dataset.groupParent === 'true' && (event.key === 'Enter' || event.key === 'ArrowRight')) {
      event.preventDefault()
      setOpenOverrides((previous) => ({
        ...previous,
        [groupId]: event.key === 'Enter' && isOpen(groupId) ? false : true,
      }))
      return
    }
    if (groupId && current?.dataset.groupChild === 'true' && event.key === 'ArrowLeft') {
      event.preventDefault()
      setOpenOverrides((previous) => ({ ...previous, [groupId]: false }))
      requestAnimationFrame(() => sidebarRef.current?.querySelector<HTMLElement>(`[data-group="${CSS.escape(groupId)}"][data-group-parent="true"]`)?.focus())
      return
    }
    if ((event.key === 'ArrowRight' || event.key === 'Enter') && current instanceof HTMLAnchorElement) {
      event.preventDefault()
      activateLink(current)
    }
  }

  return (
    <aside className="sidebar" ref={sidebarRef} onKeyDown={handleKeys} aria-label="Music tools navigation">
      <div className="brand"><span className="brand-mark">♪</span><span>TuneOps</span></div>
      {navigation.isError ? <p className="sidebar-error">Backend unavailable</p> : null}
      <nav className="side-nav">
        {(navigation.data?.tools ?? []).map((item) => (
          <Link key={item.id} to={item.path} data-nav-entry data-path={item.path} className={`nav-item ${pathname === item.path ? 'active' : ''}`} onClick={() => {
            if (isTrackRoute(item.path)) sessionStorage.setItem('musicsync.react.focus-track-list', item.path)
          }}>
            <span className="nav-icon">{item.icon}</span><span>{item.label}</span>
          </Link>
        ))}
        {(navigation.data?.groups ?? []).map((group) => {
          const expanded = isOpen(group.id)
          return (
            <section className="nav-group" key={group.id}>
              <button
                type="button"
                className="nav-item nav-parent"
                aria-expanded={expanded}
                data-nav-entry
                data-group={group.id}
                data-group-parent="true"
                onClick={() => setOpenOverrides((previous) => ({ ...previous, [group.id]: !expanded }))}
              >
                <span className={`nav-chevron ${expanded ? 'open' : ''}`}>▸</span><span>{group.label}</span>
                <small>{group.items.length}</small>
              </button>
              {expanded ? <div className="nav-children">
                {group.items.map((item) => item.children?.length ? <div className="nav-nested" key={`${item.kind}:${item.id}`}>
                  <button
                    type="button"
                    className="nav-item nav-child nav-nested-parent"
                    aria-expanded={isOpen(`${group.id}:${item.id}`)}
                    data-nav-entry
                    data-group={group.id}
                    data-group-child="true"
                    data-nested={`${group.id}:${item.id}`}
                    data-nested-parent="true"
                    onClick={() => setOpenOverrides((previous) => ({ ...previous, [`${group.id}:${item.id}`]: !isOpen(`${group.id}:${item.id}`) }))}
                  ><span className={`nav-chevron ${isOpen(`${group.id}:${item.id}`) ? 'open' : ''}`}>▸</span><span>{item.label}</span><small>{item.children.length}</small></button>
                  {isOpen(`${group.id}:${item.id}`) ? <div className="nav-grandchildren">{item.children.map((child) => <Link
                    key={`${child.kind}:${child.id}`}
                    to={child.path}
                    data-nav-entry
                    data-path={child.path}
                    data-group={group.id}
                    data-group-child="true"
                    data-nested={`${group.id}:${item.id}`}
                    data-nested-child="true"
                    className={`nav-item nav-child nav-grandchild ${pathname === child.path ? 'active' : ''}`}
                    onClick={() => sessionStorage.setItem('musicsync.react.focus-track-list', child.path)}
                  ><span className="nav-icon">{child.icon}</span><span title={child.label}>{child.label}</span></Link>)}</div> : null}
                </div> : (
                  <Link
                    key={`${item.kind}:${item.id}`}
                    to={item.path}
                    data-nav-entry
                    data-path={item.path}
                    data-group={group.id}
                    data-group-child="true"
                    className={`nav-item nav-child ${pathname === item.path ? 'active' : ''}`}
                    onClick={() => sessionStorage.setItem('musicsync.react.focus-track-list', item.path)}
                  >
                    <span className="nav-icon">{item.icon}</span><span title={item.label}>{item.label}</span>
                  </Link>
                ))}
              </div> : null}
            </section>
          )
        })}
      </nav>
    </aside>
  )
}
