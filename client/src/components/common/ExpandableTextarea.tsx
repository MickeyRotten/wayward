import { useEffect, useRef, useState } from 'react'

/**
 * A full-screen modal text editor overlaid on the UI with a semi-opaque black
 * backdrop. Closes on backdrop click, the DONE button, or Escape.
 */
export function TextEditorModal({
  label,
  value,
  onChange,
  onClose,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
    >
      <div
        className="flex flex-col w-full max-w-3xl h-[80vh] border border-line2 bg-bg1 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <span className="font-ui text-[11px] tracking-wider text-textsec uppercase">{label}</span>
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border border-line px-3 py-1 hover:border-line2 hover:text-text"
            onClick={onClose}
          >
            DONE
          </button>
        </div>
        <textarea
          autoFocus
          className="flex-1 w-full bg-bg0 px-4 py-3 text-sm font-body text-text outline-none resize-none"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  )
}

/** Small "open large editor" icon button (a maximize/expand glyph). */
export function ExpandIconButton({
  onClick,
  className = '',
}: {
  onClick: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      title="Open large editor"
      onClick={onClick}
      className={`text-textdim hover:text-text bg-bg0/80 border border-line hover:border-line2 p-0.5 ${className}`}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 3h6v6" />
        <path d="M9 21H3v-6" />
        <path d="M21 3l-7 7" />
        <path d="M3 21l7-7" />
      </svg>
    </button>
  )
}

/**
 * A textarea with a corner "expand" button that opens the same content in a
 * large modal editor. Supports both controlled (pass value + onChange) and
 * uncontrolled/save-on-blur (also pass onBlur) usage, matching the two textarea
 * patterns used across the app.
 */
export function ExpandableTextarea({
  value,
  onChange,
  onBlur,
  placeholder,
  rows = 3,
  className = '',
  label = 'Edit',
}: {
  value: string
  onChange: (v: string) => void
  onBlur?: (v: string) => void
  placeholder?: string
  rows?: number
  className?: string
  label?: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const uncontrolled = onBlur !== undefined

  const openModal = () => {
    setDraft(uncontrolled ? (ref.current?.value ?? value) : value)
    setOpen(true)
  }
  const handleModalChange = (v: string) => {
    setDraft(v)
    onChange(v)
    // Keep the uncontrolled inline textarea's DOM value in sync so it reflects
    // the edit once the modal closes.
    if (uncontrolled && ref.current) ref.current.value = v
  }
  const closeModal = () => {
    setOpen(false)
    if (uncontrolled) (onBlur ?? onChange)(ref.current?.value ?? draft)
  }

  return (
    <div className="relative">
      {uncontrolled ? (
        <textarea
          ref={ref}
          rows={rows}
          placeholder={placeholder}
          className={className}
          defaultValue={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onBlur!(e.target.value)}
        />
      ) : (
        <textarea
          ref={ref}
          rows={rows}
          placeholder={placeholder}
          className={className}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      <ExpandIconButton onClick={openModal} className="absolute top-1 right-1" />
      {open && (
        <TextEditorModal label={label} value={draft} onChange={handleModalChange} onClose={closeModal} />
      )}
    </div>
  )
}
