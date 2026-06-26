import { useWorldbuildStore } from '../../state/worldbuildStore'
import type { WorldbuildProposal } from '@shared/types/models'

const KIND_LABELS: Record<WorldbuildProposal['kind'], string> = {
  lore: 'Lore',
  quest: 'Quest',
  quest_objective: 'Objective',
  member: 'Party Member',
}

function detailText(p: WorldbuildProposal): string {
  const pl = p.payload as Record<string, unknown>
  const val =
    (pl.content as string) ||
    (pl.desc as string) ||
    (pl.description as string) ||
    (pl.text as string) ||
    (pl.status ? `→ ${pl.status}` : '') ||
    (pl.done !== undefined ? (pl.done ? 'mark done' : 'reopen') : '')
  return typeof val === 'string' ? val : ''
}

export function SuggestionsPanel() {
  const proposals = useWorldbuildStore((s) => s.proposals)
  const running = useWorldbuildStore((s) => s.running)
  const accept = useWorldbuildStore((s) => s.accept)
  const reject = useWorldbuildStore((s) => s.reject)
  const acceptAll = useWorldbuildStore((s) => s.acceptAll)
  const rejectAll = useWorldbuildStore((s) => s.rejectAll)

  const pending = proposals.filter((p) => p.status === 'pending')

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">IDEAS</h2>
        <p className="text-[10px] text-textdim font-body mt-1">
          The Chronicler's suggested additions to your world.
        </p>
      </div>

      {pending.length > 0 && (
        <div className="flex items-center gap-2 px-4 pb-2">
          <button
            type="button"
            className="font-ui text-[9px] bg-golddeep text-bg0 px-3 py-1 hover:bg-gold transition-colors"
            onClick={() => acceptAll()}
          >
            ACCEPT ALL
          </button>
          <button
            type="button"
            className="font-ui text-[9px] text-textdim border border-line px-3 py-1 hover:border-line2 hover:text-text"
            onClick={() => rejectAll()}
          >
            REJECT ALL
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {running && (
          <p className="text-[11px] text-textdim font-body px-4 py-2 text-center">
            Weaving the world…
          </p>
        )}

        {!running && pending.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-4 py-6 text-center">
            No suggestions right now. As you play, the Chronicler proposes new lore, quests, and companions here.
          </p>
        )}

        {pending.map((p) => {
          const detail = detailText(p)
          return (
            <div key={p.id} className="border border-line2 bg-bg2 p-2.5">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-ui text-[8px] tracking-wider text-bg0 bg-textsec px-1.5 py-0.5 rounded-sm">
                  {KIND_LABELS[p.kind]}
                </span>
                <span className="font-ui text-[8px] tracking-wider text-textdim">
                  {p.operation === 'create' ? 'NEW' : 'UPDATE'}
                </span>
              </div>
              <div className="font-disp text-[15px] text-text pt-[1px] leading-tight">{p.summary}</div>
              {detail && (
                <p className="text-[12px] text-text2 font-body mt-1 line-clamp-3">{detail}</p>
              )}
              <div className="flex items-center gap-2 mt-2">
                <button
                  type="button"
                  className="font-ui text-[9px] bg-golddeep text-bg0 px-3 py-1 hover:bg-gold transition-colors"
                  onClick={() => accept(p.id)}
                >
                  ACCEPT
                </button>
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim border border-line px-3 py-1 hover:border-line2 hover:text-text"
                  onClick={() => reject(p.id)}
                >
                  REJECT
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
