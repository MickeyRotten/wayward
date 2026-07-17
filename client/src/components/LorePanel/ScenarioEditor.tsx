import { useUiStore } from '../../state/uiStore'
import { useScenarioStore } from '../../state/scenarioStore'
import { useNarratorStore } from '../../state/narratorStore'
import { useChatStore } from '../../state/chatStore'
import { SelectionBar } from '../SelectionBar'
import { CategoryIcon } from '../CategoryIcon'
import { SCENARIO_FIELD_DEFS, buildOpenings, openingSelId } from '../../lib/scenarioFields'

/* The Scenario tab — the 6 structured fields rendered as lorebook-style cards,
   followed by the Opening Messages section. Clicking a card opens it in the
   right-hand Inspector (view in Play, edit in Edit Mode). Scenario fields still
   save via PUT /scenario; openings live on the NarratorConfig. */
export function ScenarioEditor() {
  const scenario = useScenarioStore((s) => s)
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const firstMessageOptions = useNarratorStore((s) => s.firstMessageOptions)
  const firstMessageAlternates = useNarratorStore((s) => s.firstMessageAlternates)
  const saveNarrator = useNarratorStore((s) => s.save)
  const editMode = useChatStore((s) => s.planningMode)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const isSelected = (id: string) => selection?.kind === 'scenario' && selection.id === id

  // Every opening (primary first, then alternates) — empties included so a
  // freshly created card is still listed and editable.
  const openings = buildOpenings(firstMessage, firstMessageOptions, firstMessageAlternates)

  const addOpening = async () => {
    const newIndex = firstMessageAlternates.length + 1  // its index in `openings`
    await saveNarrator({ firstMessageAlternates: [...firstMessageAlternates, { message: '', options: [] }] })
    select({ kind: 'scenario', id: openingSelId(newIndex) })
  }

  return (
    <div className="flex-1 overflow-y-auto px-3 pb-3">
      <div className="space-y-1.5">
        {SCENARIO_FIELD_DEFS.map(({ key, label }) => (
          <ScenarioCard
            key={key}
            label={label}
            empty={!(scenario[key] || '').trim()}
            selected={isSelected(key)}
            onClick={() => select({ kind: 'scenario', id: key })}
          />
        ))}
      </div>

      {/* Opening Messages. They live on the NarratorConfig (not the Scenario)
          but are surfaced here — each card is one opening, with its own options.
          At turn 0 the player swipes between them; the chosen one is anchored. */}
      <div className="pt-3 mt-3 border-t border-line space-y-1.5">
        <div className="flex items-center justify-between px-1 pb-0.5">
          <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">Opening Messages</span>
          {editMode && (
            <button
              type="button"
              className="font-ui text-[9px] tracking-wider text-textsec border border-line rounded-sm px-1.5 py-0.5 hover:text-gold hover:border-gold/50 transition-colors"
              onClick={() => void addOpening()}
            >
              + NEW
            </button>
          )}
        </div>
        {openings.map((o, i) => (
          <ScenarioCard
            key={openingSelId(i)}
            label={i === 0 ? 'First Message' : `Alternate ${i}`}
            empty={!o.message.trim()}
            selected={isSelected(openingSelId(i))}
            onClick={() => select({ kind: 'scenario', id: openingSelId(i) })}
          />
        ))}
        <span className="block text-[10px] text-textdim font-body px-1">
          The drop-capped opening, included in context. Each has its own scripted options. Not part of the Scenario.
        </span>
      </div>
    </div>
  )
}

/* Same card layout as the generic LoreCard (icon + title, bordered, gold
   selection bar) so the Scenario fields read as ordinary lore entries. */
function ScenarioCard({ label, empty, selected, onClick }: {
  label: string
  empty: boolean
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`group relative w-full text-left border rounded-md overflow-hidden transition-colors pl-3 pr-3 py-1.5 ${
        selected ? 'border-line bg-bg3' : 'border-line bg-bg2 hover:border-line2'
      }`}
      onClick={onClick}
    >
      <SelectionBar show={selected} />
      <div className="flex items-center gap-2.5">
        <CategoryIcon cat="world" className="text-gold shrink-0" />
        <span className="font-body text-sm text-text truncate flex-1 min-w-0">{label}</span>
        {empty && <span className="font-ui text-[9px] tracking-wider text-textdim shrink-0">EMPTY</span>}
      </div>
    </button>
  )
}
