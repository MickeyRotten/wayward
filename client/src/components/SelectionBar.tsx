/* Design System selection indicator: a 2px gold bar inset on the left edge of
   a selected card. The parent card must be `relative`. */
export function SelectionBar({ show }: { show: boolean }) {
  if (!show) return null
  return <span className="absolute left-0 top-2.5 bottom-2.5 w-[2px] bg-gold" aria-hidden="true" />
}

/* Design System "mandatory/locked" indicator — a small gold lock glyph next
   to a row's title, for entries that can't be removed/disabled (a Lorebook
   entry, a mandatory character-sheet block). */
export function LockGlyph() {
  return <span className="font-ui text-[10px] text-gold2 shrink-0" title="Locked">&#128274;</span>
}
