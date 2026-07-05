import type { ReactNode } from 'react'
import { MobileNav } from './MobileNav'
import { useUiStore } from '../../state/uiStore'

// Phone / portrait-tablet shell (<1024px): one full-screen view at a time over
// a bottom tab bar. The inspector becomes a full-screen slide-over that opens
// whenever something is selected and closes via its Back header.
export function MobileShell({
  main,
  inspector,
}: {
  main: ReactNode
  inspector: ReactNode
}) {
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)
  const mobileView = useUiStore((s) => s.mobileView)
  const isChat = mobileView === 'chat'

  return (
    <div className="flex h-full flex-col">
      <main
        className={`flex min-h-0 flex-1 flex-col ${isChat ? '' : 'overflow-y-auto bg-bg1'}`}
        style={isChat ? { background: 'var(--chat-bg)' } : undefined}
      >
        {main}
      </main>
      <MobileNav />

      {/* Inspector slide-over — drill-in over everything incl. the nav */}
      {selection !== null && (
        <div className="fixed inset-0 z-[60] flex flex-col bg-bg1">
          <div className="flex shrink-0 items-center border-b border-line bg-bg1">
            <button
              type="button"
              className="flex items-center gap-2 px-4 min-h-[48px] text-textsec hover:text-text transition-colors"
              onClick={() => select(null)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 18l-6-6 6-6" />
              </svg>
              <span className="font-ui text-[11px] tracking-wider">BACK</span>
            </button>
          </div>
          <div
            className="flex min-h-0 flex-1 flex-col overflow-y-auto"
            style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
          >
            {inspector}
          </div>
        </div>
      )}
    </div>
  )
}
