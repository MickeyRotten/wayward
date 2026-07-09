import { useUiStore } from '../../state/uiStore'
import { useScenarioStore } from '../../state/scenarioStore'
import { useNarratorStore } from '../../state/narratorStore'
import { SelectionBar } from '../SelectionBar'
import { CategoryIcon } from '../CategoryIcon'
import { SCENARIO_FIELD_DEFS, FIRST_MESSAGE_ID } from '../../lib/scenarioFields'

/* The Scenario tab — the 6 structured fields rendered as lorebook-style cards.
   Clicking a card opens that field in the right-hand Inspector (view in Play,
   edit in Edit Mode), exactly like every other lore entry. The underlying
   storage/save logic is unchanged: fields still save via PUT /scenario and
   compose into the locked World entry. */
export function ScenarioEditor() {
  const scenario = useScenarioStore((s) => s)
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const isSelected = (id: string) => selection?.kind === 'scenario' && selection.id === id

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

      {/* The opening narration. It lives on the NarratorConfig (not the
          Scenario) but is surfaced here on the Scenario tab — clearly separated. */}
      <div className="pt-3 mt-3 border-t border-line space-y-1.5">
        <ScenarioCard
          label="First Message"
          empty={!(firstMessage || '').trim()}
          selected={isSelected(FIRST_MESSAGE_ID)}
          onClick={() => select({ kind: 'scenario', id: FIRST_MESSAGE_ID })}
        />
        <span className="block text-[10px] text-textdim font-body px-1">
          The drop-capped opening message, included in context. Not part of the Scenario.
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
