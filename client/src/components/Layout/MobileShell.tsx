import { useCallback, type ReactNode } from 'react'
import { MobileNav } from './MobileNav'
import { useBackHandler } from '../../lib/useBackHandler'
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
  const back = useUiStore((s) => s.back)
  const goBack = useUiStore((s) => s.goBack)
  const mobileView = useUiStore((s) => s.mobileView)
  const isChat = mobileView === 'chat'

  // The Inspector is a full-screen drill-in, so the Android hardware Back button
  // has to close it. Without this, Back quit the app from the screen a phone
  // player spends most of their time on.
  const closeInspector = useCallback(() => select(null), [select])
  useBackHandler(selection !== null, closeInspector)

  // The header's BACK button steps out one level at a time: from a drilled-in
  // sub-view (e.g. a character-sheet block) it returns to the owning sheet
  // first, same as the breadcrumb inside the Inspector; only closes the whole
  // overlay once there's nowhere left to step back to.
  const headerBack = () => (back ? goBack() : select(null))

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
              onClick={headerBack}
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
