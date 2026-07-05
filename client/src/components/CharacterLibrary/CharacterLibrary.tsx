import { useEffect, useRef, useState } from 'react'
import { useCharactersStore } from '../../state/charactersStore'
import { ConfirmDialog } from '../ConfirmDialog'
import type { CharacterCard } from '@shared/types/models'

/**
 * The Character Library: browse portable character files (personas + party
 * characters), import one into the current adventure, duplicate/delete, and
 * upload/download a shareable character file. Opened from Home.
 */
export function CharacterLibrary({ onClose }: { onClose: () => void }) {
  const cards = useCharactersStore((s) => s.cards)
  const fetchCards = useCharactersStore((s) => s.fetchCards)
  const importCard = useCharactersStore((s) => s.importCard)
  const duplicateCard = useCharactersStore((s) => s.duplicateCard)
  const deleteCard = useCharactersStore((s) => s.deleteCard)
  const uploadCard = useCharactersStore((s) => s.uploadCard)
  const exportCard = useCharactersStore((s) => s.exportCard)

  const [busy, setBusy] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<CharacterCard | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => { void fetchCards() }, [fetchCards])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const doImport = async (c: CharacterCard) => {
    setBusy(c.id)
    try { await importCard(c.id) } finally { setBusy(null) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-bg0/80 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-bg2 border border-line2 rounded-md w-[560px] max-w-full max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-line">
          <h2 className="font-disp text-[20px] pt-[2px] leading-none text-text">Character Library</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
              onClick={() => fileRef.current?.click()}
            >
              UPLOAD
            </button>
            <button type="button" className="font-ui text-[13px] text-textdim hover:text-text" onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-4">
          {cards.length === 0 ? (
            <p className="text-[12px] text-textdim font-body text-center py-8">
              No saved characters yet. Party members you create are saved here automatically.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {cards.map((c) => (
                <div key={c.id} className="border border-line rounded-md bg-bg1 overflow-hidden flex flex-col">
                  <div className="flex items-stretch gap-2 p-2">
                    <div className="w-16 aspect-[3/4] shrink-0 border border-line rounded-sm bg-bg3 overflow-hidden flex items-center justify-center">
                      {c.cropUrl ? (
                        <img src={c.cropUrl} alt="" className="w-full h-full object-cover" />
                      ) : (
                        <span className="font-disp text-[20px] text-textdim pt-[2px]">
                          {(c.basicInfo?.name || '?')[0].toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-body text-sm text-text truncate">{c.basicInfo?.name || 'Unnamed'}</div>
                      <div className="font-ui text-[8px] tracking-wider uppercase text-textdim mt-0.5">
                        {c.type} · {c.basicInfo?.species || '—'}
                      </div>
                    </div>
                  </div>
                  <div className="mt-auto grid grid-cols-2 border-t border-line divide-x divide-line">
                    <button
                      type="button"
                      disabled={busy === c.id}
                      className="font-ui text-[9px] tracking-wider text-gold hover:bg-bg3 py-1.5 transition-colors disabled:opacity-40"
                      onClick={() => doImport(c)}
                    >
                      {busy === c.id ? '…' : 'IMPORT'}
                    </button>
                    <div className="grid grid-cols-3 divide-x divide-line">
                      <button type="button" title="Duplicate" className="font-ui text-[9px] text-textdim hover:bg-bg3 hover:text-text py-1.5 transition-colors" onClick={() => void duplicateCard(c.id)}>DUP</button>
                      <button type="button" title="Download" className="font-ui text-[9px] text-textdim hover:bg-bg3 hover:text-text py-1.5 transition-colors" onClick={() => exportCard(c.id)}>GET</button>
                      <button type="button" title="Delete" className="font-ui text-[9px] text-textdim hover:bg-bg3 hover:text-danger py-1.5 transition-colors" onClick={() => setConfirmDelete(c)}>DEL</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void uploadCard(f)
            e.target.value = ''
          }}
        />
      </div>

      {confirmDelete && (
        <ConfirmDialog
          confirmLabel="DELETE"
          message={`Delete "${confirmDelete.basicInfo?.name || 'this character'}" from the library? This removes the file and unbinds it from this adventure.`}
          onConfirm={() => { void deleteCard(confirmDelete.id); setConfirmDelete(null) }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  )
}
