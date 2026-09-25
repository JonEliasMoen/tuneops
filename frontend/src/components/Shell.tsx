import type { PropsWithChildren } from 'react'
import { Sidebar } from './Sidebar'

export function Shell({ children }: PropsWithChildren) {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="page-content" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  )
}
