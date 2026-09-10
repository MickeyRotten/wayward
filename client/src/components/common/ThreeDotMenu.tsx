import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const MENU_WIDTH = 128 // w-32

/** A small "•••" trigger + dropdown of actions — shared by the character
 * sheet's Prompt Blocks (BlockTreeEditor) and Equipment slots (EquipmentGrid)
 * so both present the same tap-to-open / three-dots-for-actions pattern.
 * The dropdown is portaled to <body> and positioned with `fixed` off the
 * trigger's own rect — a plain `absolute` child would get clipped by any
 * `overflow-hidden`/`overflow-auto` ancestor (a row card, a scrolled Folder
 * panel, ...). No outside-click listener: the menu only closes when an item
 * fires, the trigger is re-toggled, or the page scrolls/resizes underneath
 * it (closed rather than repositioned, since it'd otherwise drift off its
 * trigger). */
export function ThreeDotMenu({ open, onToggle, items }: {
  open: boolean
  onToggle: () => void
  items: { label: string; onClick: () => void; danger?: boolean }[]
}) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) { setPos(null); return }
    const rect = buttonRef.current?.getBoundingClientRect()
    if (!rect) return
    const left = Math.min(rect.left, window.innerWidth - MENU_WIDTH - 4)
    setPos({ top: rect.bottom + 2, left: Math.max(4, left) })
  }, [open])

  useEffect(() => {
    if (!open) return
    window.addEventListener('scroll', onToggle, true)
    window.addEventListener('resize', onToggle)
    return () => {
      window.removeEventListener('scroll', onToggle, true)
      window.removeEventListener('resize', onToggle)
    }
  }, [open, onToggle])

  return (
    <div className="relative shrink-0 mt-1">
      <button
        ref={buttonRef}
        type="button"
        className="w-6 h-7 flex items-center justify-center text-textdim hover:text-text transition-colors"
        onClick={(e) => { e.stopPropagation(); onToggle() }}
        title="Actions"
      >
        <span className="text-sm leading-none tracking-widest">&bull;&bull;&bull;</span>
      </button>
      {open && pos && createPortal(
        <div
          className="fixed z-50 border border-line bg-bg1 shadow-lg w-32"
          style={{ top: pos.top, left: pos.left }}
          onClick={(e) => e.stopPropagation()}
        >
          {items.map(({ label, onClick, danger }) => (
            <ThreeDotMenuItem key={label} label={label} onClick={onClick} danger={danger} />
          ))}
        </div>,
        document.body
      )}
    </div>
  )
}

function ThreeDotMenuItem({ label, onClick, danger }: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      className={`block w-full text-left px-3 py-1.5 text-xs font-body transition-colors hover:bg-bg2 ${danger ? 'text-danger' : 'text-text'}`}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
    >
      {label}
    </button>
  )
}
