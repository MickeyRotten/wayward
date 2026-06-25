/* Design System selection indicator: a 2px gold bar inset on the left edge of
   a selected card. The parent card must be `relative`. */
export function SelectionBar({ show }: { show: boolean }) {
  if (!show) return null
  return <span className="absolute left-0 top-2.5 bottom-2.5 w-[2px] bg-gold" aria-hidden="true" />
}
