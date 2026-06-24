import { useEffect } from 'react'

export function ConfirmDialog({
  message,
  confirmLabel = 'CONFIRM',
  onConfirm,
  onCancel,
}: {
  message: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/80">
      <div className="bg-bg1 border border-line2 w-[360px] p-5 space-y-4">
        <p className="text-sm font-body text-text leading-relaxed">{message}</p>
        <div className="flex gap-3">
          <button
            type="button"
            className="font-ui text-[10px] bg-golddeep text-bg0 px-4 py-2 hover:bg-gold transition-colors"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim border border-line px-4 py-2 hover:border-line2 transition-colors"
            onClick={onCancel}
          >
            CANCEL
          </button>
        </div>
      </div>
    </div>
  )
}
