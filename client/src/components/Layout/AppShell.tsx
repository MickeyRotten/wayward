import type { ReactNode } from 'react'

interface AppShellProps {
  left: ReactNode
  middle: ReactNode
  right: ReactNode
}

export function AppShell({ left, middle, right }: AppShellProps) {
  return (
    <div className="grid h-full grid-cols-[260px_1fr_360px]">
      <aside className="overflow-y-auto border-r-[1.5px] border-border bg-off">
        {left}
      </aside>
      <main className="flex flex-col overflow-hidden bg-white">
        {middle}
      </main>
      <aside className="overflow-y-auto border-l-[1.5px] border-border bg-off">
        {right}
      </aside>
    </div>
  )
}
