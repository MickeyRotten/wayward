import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

interface AppShellProps {
  iconRail: ReactNode
  left: ReactNode
  middle: ReactNode
  right: ReactNode
}

// Device-local panel widths (desktop only — MobileShell has its own layout
// and never renders this component).
const LEFT_MIN = 220
const LEFT_MAX = 480
const LEFT_DEFAULT = 288
const LEFT_KEY = 'wayward.leftPanelWidth'

const RIGHT_MIN = 260
const RIGHT_MAX = 520
const RIGHT_DEFAULT = 344
const RIGHT_KEY = 'wayward.rightPanelWidth'

// Chat must stay legible even with both side panels dragged toward their max
// on a narrower window.
const CHAT_MIN = 360

function readStoredWidth(key: string, fallback: number, min: number, max: number): number {
  const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null
  const n = raw === null ? NaN : Number(raw)
  return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.round(n))) : fallback
}

function storeWidth(key: string, value: number) {
  try {
    localStorage.setItem(key, String(Math.round(value)))
  } catch {
    // ignore storage failures (private mode, etc.)
  }
}

function ResizeHandle({ onPointerDown }: { onPointerDown: (e: ReactPointerEvent) => void }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      className="group flex cursor-col-resize items-stretch justify-center bg-bg1"
    >
      <div className="w-px bg-line group-hover:bg-gold group-active:bg-gold" />
    </div>
  )
}

export function AppShell({ iconRail, left, middle, right }: AppShellProps) {
  const [leftWidth, setLeftWidth] = useState(() => readStoredWidth(LEFT_KEY, LEFT_DEFAULT, LEFT_MIN, LEFT_MAX))
  const [rightWidth, setRightWidth] = useState(() => readStoredWidth(RIGHT_KEY, RIGHT_DEFAULT, RIGHT_MIN, RIGHT_MAX))
  const leftWidthRef = useRef(leftWidth)
  const rightWidthRef = useRef(rightWidth)
  leftWidthRef.current = leftWidth
  rightWidthRef.current = rightWidth

  const dragState = useRef<{ side: 'left' | 'right'; startX: number; startWidth: number } | null>(null)

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragState.current
      if (!drag) return
      const dx = e.clientX - drag.startX
      if (drag.side === 'left') {
        const maxAllowed = Math.min(LEFT_MAX, window.innerWidth - rightWidthRef.current - CHAT_MIN)
        setLeftWidth(Math.min(maxAllowed, Math.max(LEFT_MIN, drag.startWidth + dx)))
      } else {
        const maxAllowed = Math.min(RIGHT_MAX, window.innerWidth - leftWidthRef.current - CHAT_MIN)
        setRightWidth(Math.min(maxAllowed, Math.max(RIGHT_MIN, drag.startWidth - dx)))
      }
    }
    const onUp = () => {
      const drag = dragState.current
      if (!drag) return
      dragState.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      storeWidth(drag.side === 'left' ? LEFT_KEY : RIGHT_KEY, drag.side === 'left' ? leftWidthRef.current : rightWidthRef.current)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  const startDrag = useCallback(
    (side: 'left' | 'right') => (e: ReactPointerEvent) => {
      e.preventDefault()
      dragState.current = { side, startX: e.clientX, startWidth: side === 'left' ? leftWidthRef.current : rightWidthRef.current }
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [],
  )

  return (
    <div
      className="grid h-full"
      style={{ gridTemplateColumns: `66px ${leftWidth}px 5px minmax(${CHAT_MIN}px,1fr) 5px ${rightWidth}px` }}
    >
      <nav className="flex flex-col overflow-hidden bg-bg1 border-r border-line">
        {iconRail}
      </nav>
      <aside className="flex flex-col overflow-y-auto bg-bg1">
        {left}
      </aside>
      <ResizeHandle onPointerDown={startDrag('left')} />
      <main className="flex flex-col overflow-hidden" style={{ background: 'var(--chat-bg)' }}>
        {middle}
      </main>
      <ResizeHandle onPointerDown={startDrag('right')} />
      <aside className="flex flex-col overflow-y-auto bg-bg1">
        {right}
      </aside>
    </div>
  )
}
