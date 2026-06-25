import type { ReactNode } from 'react'

interface AppShellProps {
  iconRail: ReactNode
  left: ReactNode
  middle: ReactNode
  right: ReactNode
}

export function AppShell({ iconRail, left, middle, right }: AppShellProps) {
  return (
    <div className="grid h-full grid-cols-[66px_288px_minmax(0,1fr)_344px]">
      <nav className="flex flex-col overflow-hidden bg-bg1 border-r border-line">
        {iconRail}
      </nav>
      <aside className="flex flex-col overflow-y-auto bg-bg1 border-r border-line">
        {left}
      </aside>
      <main className="flex flex-col overflow-hidden" style={{ background: 'var(--chat-bg)' }}>
        {middle}
      </main>
      <aside className="flex flex-col overflow-y-auto bg-bg1 border-l border-line">
        {right}
      </aside>
    </div>
  )
}
