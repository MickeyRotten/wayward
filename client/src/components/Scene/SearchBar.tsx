// The in-chat message search bar (Tools → Search Messages…).

export function SearchBar({
  query, onQuery, count, index, onPrev, onNext, onClose,
}: {
  query: string
  onQuery: (v: string) => void
  count: number
  index: number
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  return (
    <div className="shrink-0 border-b border-line2 bg-bg2 px-3 py-2 flex items-center gap-2">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-textdim shrink-0">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
      </svg>
      <input
        autoFocus
        className="flex-1 bg-transparent text-sm font-body text-text outline-none placeholder:text-textdim"
        placeholder="Search messages…"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); e.shiftKey ? onPrev() : onNext() }
          else if (e.key === 'Escape') onClose()
        }}
      />
      <span className="font-ui text-[9px] text-textdim tracking-wider shrink-0 tabular-nums">
        {query.trim() ? `${count > 0 ? index + 1 : 0}/${count}` : ''}
      </span>
      <button type="button" className="text-textdim hover:text-text disabled:opacity-30" disabled={count === 0} onClick={onPrev} aria-label="Previous match">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m18 15-6-6-6 6" /></svg>
      </button>
      <button type="button" className="text-textdim hover:text-text disabled:opacity-30" disabled={count === 0} onClick={onNext} aria-label="Next match">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      <button type="button" className="font-ui text-[10px] text-textdim hover:text-text tracking-wider shrink-0" onClick={onClose} aria-label="Close search">
        ✕
      </button>
    </div>
  )
}
