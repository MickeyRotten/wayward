import { useEffect, useMemo, useState } from 'react'
import { useAdventuresStore } from '../../state/adventuresStore'
import { useCampaignsStore } from '../../state/campaignsStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'
import type { Adventure } from '@shared/types/models'

function portraitSrc(p: string): string | null {
  if (!p) return null
  // Legacy sidecars stored a filename or full URL; new ones store a character id
  // whose crop is served per-character.
  if (p.startsWith('/') || p.startsWith('http')) return p
  if (p.includes('.')) return `/portraits/${p}`  // legacy filename
  return `/api/characters/${p}/portrait/crop`     // character id
}

/** Compact "time ago" label from an ISO timestamp. */
function relativeTime(iso: string): string {
  const then = iso ? new Date(iso).getTime() : NaN
  if (Number.isNaN(then)) return ''
  const s = Math.max(0, (Date.now() - then) / 1000)
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d === 1) return 'yesterday'
  if (d < 7) return `${d}d ago`
  const w = Math.floor(d / 7)
  if (w < 5) return `${w}w ago`
  const mo = Math.floor(d / 30)
  if (mo < 12) return `${mo}mo ago`
  return `${Math.floor(d / 365)}y ago`
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
  const rename = useAdventuresStore((s) => s.rename)

  const [confirmDelete, setConfirmDelete] = useState<Adventure | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  // Most recently played first.
  const sorted = useMemo(
    () => [...adventures].sort(
      (a, b) => new Date(b.lastPlayedAt).getTime() - new Date(a.lastPlayedAt).getTime(),
    ),
    [adventures],
  )

  const startRename = (a: Adventure) => { setRenamingId(a.id); setRenameValue(a.name) }
  const commitRename = async () => {
    const id = renamingId
    const name = renameValue.trim()
    setRenamingId(null)
    if (id && name) {
      const current = adventures.find((a) => a.id === id)
      if (current && name !== current.name) await rename(id, name)
    }
  }

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

        {sorted.map((a) => {
          const isActive = a.id === activeId
          const isRenaming = renamingId === a.id
          return (
            <div
              key={a.id}
              className={`border rounded-md p-3 ${isActive ? 'border-line2 bg-bg3' : 'border-line bg-bg2'}`}
            >
              <div className="flex items-stretch gap-3">
                <Avatar src={a.pcPortrait} name={a.pcName || a.name} size={48} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 group">
                    {isRenaming ? (
                      <input
                        autoFocus
                        className="flex-1 min-w-0 border border-line2 bg-bg0 px-2 py-0.5 text-[14px] font-disp text-text outline-none"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.preventDefault(); commitRename() }
                          else if (e.key === 'Escape') setRenamingId(null)
                        }}
                      />
                    ) : (
                      <>
                        <span className="font-disp text-[15px] text-text truncate pt-[1px]">{a.name}</span>
                        <button
                          type="button"
                          title="Rename"
                          aria-label="Rename adventure"
                          className="shrink-0 text-textdim hover:text-gold opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={() => startRename(a)}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                          </svg>
                        </button>
                      </>
                    )}
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
                  {relativeTime(a.lastPlayedAt) && (
                    <div className="font-ui text-[9px] text-textdim tracking-wider mt-0.5">
                      Last played {relativeTime(a.lastPlayedAt)}
                    </div>
                  )}
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
                {isActive && (
                  <button
                    type="button"
                    title="Download this adventure as a readable Markdown story"
                    className="font-ui text-[9px] tracking-wider text-textsec border border-line px-3 py-1 hover:text-gold hover:border-line2 transition-colors"
                    onClick={() => window.open('/api/adventure/story-export', '_blank')}
                  >
                    EXPORT STORY
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

      <BackupsSection />
    </div>
  )
}

interface BackupInfo {
  file: string
  size: number
  createdAt: string
}

/** Automatic rotating campaign snapshots (taken at launch and on campaign
 *  switch). Restoring imports the snapshot as a NEW campaign — live data is
 *  never overwritten. */
function BackupsSection() {
  const loadCampaign = useCampaignsStore((s) => s.load)
  const [backups, setBackups] = useState<BackupInfo[]>([])
  const [confirmRestore, setConfirmRestore] = useState<BackupInfo | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get<BackupInfo[]>('/backups').then(setBackups).catch(() => setBackups([]))
  }, [])

  const restore = async (b: BackupInfo) => {
    setBusy(true)
    try {
      const res = await api.post<{ id: string; name: string }>(`/backups/${encodeURIComponent(b.file)}/restore`, {})
      await loadCampaign(res.id) // switch to the freshly restored campaign
    } finally {
      setBusy(false)
    }
  }

  if (backups.length === 0) return null

  return (
    <div className="shrink-0 border-t border-line px-4 py-3">
      <span className="block font-ui text-[10px] tracking-wider text-textsec uppercase mb-1">Backups</span>
      <span className="block text-[10px] text-textdim font-body mb-2">
        Automatic campaign snapshots, taken at launch and on campaign switch. Restoring
        creates a <span className="text-textsec">new</span> campaign — nothing is overwritten.
      </span>
      <div className="space-y-1 max-h-40 overflow-y-auto">
        {backups.map((b) => (
          <div key={b.file} className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-body text-[11px] text-textsec" title={b.file}>
              {b.file.replace(/\.zip$/, '')}
            </span>
            <span className="shrink-0 font-ui text-[9px] text-textdim">{relativeTime(b.createdAt)}</span>
            <button
              type="button"
              disabled={busy}
              className="shrink-0 font-ui text-[9px] tracking-wider text-textsec border border-line px-2 py-0.5 hover:text-gold hover:border-line2 transition-colors disabled:opacity-40"
              onClick={() => setConfirmRestore(b)}
            >
              RESTORE
            </button>
          </div>
        ))}
      </div>
      {confirmRestore && (
        <ConfirmDialog
          confirmLabel="RESTORE"
          message={`Restore "${confirmRestore.file}" as a new campaign? Your current campaigns stay untouched.`}
          onConfirm={() => { void restore(confirmRestore); setConfirmRestore(null) }}
          onCancel={() => setConfirmRestore(null)}
        />
      )}
    </div>
  )
}
