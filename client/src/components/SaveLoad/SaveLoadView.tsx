import { useState } from 'react'
import { useAdventuresStore } from '../../state/adventuresStore'
import { ConfirmDialog } from '../ConfirmDialog'
import type { Adventure } from '@shared/types/models'

function portraitSrc(p: string): string | null {
  if (!p) return null
  return p.startsWith('/') || p.startsWith('http') ? p : `/portraits/${p}`
}

function Avatar({ src, name, size }: { src: string; name: string; size: number }) {
  const url = portraitSrc(src)
  return (
    <div
      className="rounded-sm border border-line2 bg-bg3 overflow-hidden flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
    >
      {url ? (
        <img src={url} alt={name} className="w-full h-full object-cover" />
      ) : (
        <span className="font-disp text-textdim pt-[2px]" style={{ fontSize: size * 0.42 }}>
          {(name || '?')[0].toUpperCase()}
        </span>
      )}
    </div>
  )
}

export function SaveLoadView() {
  const adventures = useAdventuresStore((s) => s.adventures)
  const activeId = useAdventuresStore((s) => s.activeId)
  const busy = useAdventuresStore((s) => s.busy)
  const create = useAdventuresStore((s) => s.create)
  const load = useAdventuresStore((s) => s.load)
  const remove = useAdventuresStore((s) => s.remove)

  const [confirmDelete, setConfirmDelete] = useState<Adventure | null>(null)

  return (
    <div className="flex flex-col h-full">
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">ADVENTURES</h2>
        <p className="text-[10px] text-textdim font-body mt-1">Save files in the active campaign.</p>
      </div>

      <div className="px-4 pb-3">
        <button
          type="button"
          disabled={busy}
          className="w-full font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors disabled:opacity-40"
          onClick={() => create()}
        >
          + NEW ADVENTURE
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {adventures.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-4 py-6 text-center">No adventures yet.</p>
        )}

        {adventures.map((a) => {
          const isActive = a.id === activeId
          return (
            <div
              key={a.id}
              className={`border rounded-md p-3 ${isActive ? 'border-line2 bg-bg3' : 'border-line bg-bg2'}`}
            >
              <div className="flex items-stretch gap-3">
                <Avatar src={a.pcPortrait} name={a.pcName || a.name} size={48} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-disp text-[15px] text-text truncate pt-[1px]">{a.name}</span>
                    {isActive && (
                      <span className="font-ui text-[8px] tracking-wider text-gold border border-gold/40 px-1.5 py-0.5 rounded-sm shrink-0">
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <div className="font-body text-[12px] text-textsec truncate">
                    {a.pcName || 'Unnamed hero'}
                    {a.location ? ` · ${a.location}` : ''} · Day {a.day || 1}
                  </div>
                  {a.partyPortraits.length > 0 && (
                    <div className="flex items-center gap-1 mt-1.5">
                      {a.partyPortraits.slice(0, 5).map((p, i) => (
                        <Avatar key={i} src={p} name="" size={20} />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 mt-2.5">
                {!isActive && (
                  <button
                    type="button"
                    disabled={busy}
                    className="font-ui text-[9px] tracking-wider bg-golddeep text-bg0 px-3 py-1 hover:bg-gold transition-colors disabled:opacity-40"
                    onClick={() => load(a.id)}
                  >
                    LOAD
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy || adventures.length <= 1}
                  title={adventures.length <= 1 ? "Can't delete the only adventure" : undefined}
                  className="font-ui text-[9px] tracking-wider text-danger border border-danger-border px-3 py-1 hover:text-danger-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  onClick={() => setConfirmDelete(a)}
                >
                  DELETE
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {confirmDelete && (
        <ConfirmDialog
          confirmLabel="DELETE"
          message={`Delete "${confirmDelete.name}"? This save and its progress are gone for good.`}
          onConfirm={() => { remove(confirmDelete.id); setConfirmDelete(null) }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  )
}
