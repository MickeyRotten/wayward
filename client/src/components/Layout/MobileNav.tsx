import { useState } from 'react'
import type { ReactNode } from 'react'
import { TABS } from '../IconRail/IconRail'
import { useUiStore } from '../../state/uiStore'
import type { MobileView, TabId } from '../../state/uiStore'
import { useWorldbuildStore } from '../../state/worldbuildStore'
import { useChatStore } from '../../state/chatStore'

// Primary slots on the bar; everything else lives in the More sheet.
const BAR_TABS: TabId[] = ['home', 'items', 'lore']
const MORE_TABS: TabId[] = ['tasks', 'journal', 'suggestions', 'saves', 'config']

const CHAT_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
)

const MORE_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="12" r="1" />
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
  </svg>
)

function tabDef(id: TabId) {
  return TABS.find((t) => t.id === id)!
}

function NavButton({
  icon,
  label,
  active,
  badge = 0,
  onClick,
}: {
  icon: ReactNode
  label: string
  active: boolean
  badge?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`relative flex flex-1 flex-col items-center justify-center min-h-[56px] transition-colors ${
        active ? 'text-gold' : 'text-textdim'
      }`}
      onClick={onClick}
    >
      {/* Active indicator — gold top border (bottom-bar mirror of the rail's left border) */}
      {active && <div className="absolute top-0 left-3 right-3 h-[2px] bg-gold" />}
      {icon}
      {badge > 0 && (
        <span className="absolute top-1.5 right-[calc(50%-22px)] min-w-[15px] h-[15px] px-1 flex items-center justify-center rounded-full bg-gold text-bg0 font-ui text-[8px] leading-none">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
      <span className="font-ui text-[9px] tracking-wider mt-1">{label.toUpperCase()}</span>
    </button>
  )
}

export function MobileNav() {
  const mobileView = useUiStore((s) => s.mobileView)
  const setMobileView = useUiStore((s) => s.setMobileView)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const select = useUiStore((s) => s.select)
  const pendingCount = useWorldbuildStore((s) => s.pendingCount)
  const planningMode = useChatStore((s) => s.planningMode)
  const setPlanningMode = useChatStore((s) => s.setPlanningMode)
  const [moreOpen, setMoreOpen] = useState(false)

  const go = (view: MobileView) => {
    setMobileView(view)
    // Keep activeTab in sync so a rotate/resize to desktop lands on the same panel.
    if (view !== 'chat') setActiveTab(view)
    // Leaving for another view closes any drilled-in inspector overlay.
    select(null)
    setMoreOpen(false)
  }

  const moreActive = MORE_TABS.includes(mobileView as TabId)

  return (
    <nav
      className="relative shrink-0 bg-bg1 border-t border-line"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {/* More sheet — sits above the bar, list of secondary destinations */}
      {moreOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMoreOpen(false)} />
          <div className="absolute bottom-full left-0 right-0 z-50 bg-bg1 border-t border-line2 shadow-[0_-8px_24px_rgba(0,0,0,0.5)]">
            {MORE_TABS.map((id) => {
              const t = tabDef(id)
              const badge = id === 'suggestions' ? pendingCount : 0
              const active = mobileView === id
              return (
                <button
                  key={id}
                  type="button"
                  className={`flex w-full items-center gap-3 px-5 min-h-[48px] transition-colors ${
                    active ? 'text-gold' : 'text-textsec'
                  }`}
                  onClick={() => go(id)}
                >
                  {t.icon}
                  <span className="font-ui text-[11px] tracking-wider">{t.label.toUpperCase()}</span>
                  {badge > 0 && (
                    <span className="ml-auto min-w-[17px] h-[17px] px-1 flex items-center justify-center rounded-full bg-gold text-bg0 font-ui text-[9px] leading-none">
                      {badge > 9 ? '9+' : badge}
                    </span>
                  )}
                </button>
              )
            })}
            {/* Edit/Play mode toggle — reachable from every view, not just Chat
                (the chat banner's Play button stays the desktop primary). */}
            <button
              type="button"
              className={`flex w-full items-center gap-3 px-5 min-h-[48px] border-t border-line transition-colors ${
                planningMode ? 'text-gold' : 'text-textsec'
              }`}
              onClick={() => { setPlanningMode(!planningMode); setMoreOpen(false) }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
              </svg>
              <span className="font-ui text-[11px] tracking-wider">EDIT MODE</span>
              <span className={`ml-auto font-ui text-[9px] tracking-wider px-2 py-0.5 border ${
                planningMode ? 'text-gold border-gold/40' : 'text-textdim border-line'
              }`}>
                {planningMode ? 'ON' : 'OFF'}
              </span>
            </button>
          </div>
        </>
      )}

      <div className="flex">
        <NavButton icon={CHAT_ICON} label="Chat" active={mobileView === 'chat'} onClick={() => go('chat')} />
        {BAR_TABS.map((id) => {
          const t = tabDef(id)
          return (
            <NavButton
              key={id}
              icon={t.icon}
              label={t.label}
              active={mobileView === id}
              onClick={() => go(id)}
            />
          )
        })}
        <NavButton
          icon={MORE_ICON}
          label="More"
          active={moreActive || moreOpen}
          badge={pendingCount}
          onClick={() => setMoreOpen((v) => !v)}
        />
      </div>
    </nav>
  )
}
