/** A small "•••" trigger + dropdown of actions — shared by the character
 * sheet's Prompt Blocks (BlockTreeEditor) and Equipment slots (EquipmentGrid)
 * so both present the same tap-to-open / three-dots-for-actions pattern.
 * No outside-click listener: the menu only closes when an item fires or the
 * trigger is re-toggled. */
export function ThreeDotMenu({ open, onToggle, items }: {
  open: boolean
  onToggle: () => void
  items: { label: string; onClick: () => void; danger?: boolean }[]
}) {
  return (
    <div className="relative shrink-0 mt-1">
      <button
        type="button"
        className="w-6 h-7 flex items-center justify-center text-textdim hover:text-text transition-colors"
        onClick={(e) => { e.stopPropagation(); onToggle() }}
        title="Actions"
      >
        <span className="text-sm leading-none tracking-widest">&bull;&bull;&bull;</span>
      </button>
      {open && (
        <div
          className="absolute z-20 left-0 top-full mt-0.5 border border-line bg-bg1 shadow-lg w-32"
          onClick={(e) => e.stopPropagation()}
        >
          {items.map(({ label, onClick, danger }) => (
            <ThreeDotMenuItem key={label} label={label} onClick={onClick} danger={danger} />
          ))}
        </div>
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
