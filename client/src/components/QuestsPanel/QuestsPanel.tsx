import { useState } from 'react'
import { useQuestsStore } from '../../state/questsStore'
import { useUiStore } from '../../state/uiStore'
import type { Quest } from '@shared/types/models'

export function QuestsPanel() {
  const quests = useQuestsStore((s) => s.quests)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const activeQuests = quests.filter((q) => q.status === 'active')
  const inactiveQuests = quests.filter((q) => q.status !== 'active')

  const isSelected = (id: string) =>
    selection?.kind === 'quest' && selection.id === id

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">QUESTS</h2>
      </div>

      {/* Quest lists */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {/* Active quests */}
        <div className="px-2 pb-1">
          <span className="font-ui text-[9px] text-textsec tracking-wider">ACTIVE</span>
        </div>

        {activeQuests.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-4 py-3 text-center">
            No active quests
          </p>
        )}

        <div className="space-y-1">
          {activeQuests.map((quest) => (
            <QuestRow
              key={quest.id}
              quest={quest}
              selected={isSelected(quest.id)}
              onSelect={() => select({ kind: 'quest', id: quest.id })}
            />
          ))}
        </div>

        {/* Completed / Failed section */}
        {inactiveQuests.length > 0 && (
          <InactiveSection
            quests={inactiveQuests}
            isSelected={isSelected}
            onSelect={(id) => select({ kind: 'quest', id })}
          />
        )}

        {/* Divider */}
        <div className="flex items-center gap-2 px-3 pt-4 pb-1">
          <span className="font-ui text-[9px] text-textdim tracking-wider">NEW QUEST</span>
          <div className="flex-1 border-t border-line" />
        </div>

        {/* New quest input */}
        <NewQuestInput />
      </div>
    </div>
  )
}

function QuestRow({
  quest,
  selected,
  onSelect,
}: {
  quest: Quest
  selected: boolean
  onSelect: () => void
}) {
  const doneCount = quest.objectives.filter((o) => o.done).length
  const totalCount = quest.objectives.length

  return (
    <button
      type="button"
      className={`w-full text-left px-3 py-2.5 border transition-colors ${
        selected
          ? 'border-line2 bg-bg0'
          : 'border-transparent hover:bg-bg2'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-body text-sm text-text truncate">{quest.title}</span>
        {totalCount > 0 && (
          <span className={`font-ui text-[10px] shrink-0 ${
            doneCount === totalCount ? 'text-gold' : 'text-textsec'
          }`}>
            {doneCount}/{totalCount}
          </span>
        )}
      </div>
    </button>
  )
}

function InactiveSection({
  quests,
  isSelected,
  onSelect,
}: {
  quests: Quest[]
  isSelected: (id: string) => boolean
  onSelect: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="mt-3">
      <button
        type="button"
        className="flex items-center gap-2 px-2 pb-1 w-full text-left group"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="font-ui text-[9px] text-textsec tracking-wider group-hover:text-text transition-colors">
          COMPLETED / FAILED
        </span>
        <span className="font-ui text-[9px] text-textdim">{expanded ? '▴' : '▾'}</span>
        <span className="font-ui text-[10px] text-textdim">{quests.length}</span>
      </button>

      {expanded && (
        <div className="space-y-1">
          {quests.map((quest) => (
            <button
              key={quest.id}
              type="button"
              className={`w-full text-left px-3 py-2.5 border transition-colors ${
                isSelected(quest.id)
                  ? 'border-line2 bg-bg0'
                  : 'border-transparent hover:bg-bg2'
              }`}
              onClick={() => onSelect(quest.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-body text-sm text-textdim truncate">{quest.title}</span>
                <span className={`font-ui text-[9px] tracking-wider shrink-0 ${
                  quest.status === 'completed' ? 'text-textsec' : 'text-danger'
                }`}>
                  {quest.status === 'completed' ? 'DONE' : 'FAILED'}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function NewQuestInput() {
  const [title, setTitle] = useState('')
  const [error, setError] = useState('')
  const createQuest = useQuestsStore((s) => s.createQuest)
  const select = useUiStore((s) => s.select)

  const handleSubmit = async () => {
    const trimmed = title.trim()
    if (!trimmed) return
    setError('')
    try {
      const quest = await createQuest(trimmed)
      setTitle('')
      select({ kind: 'quest', id: quest.id })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create quest')
    }
  }

  return (
    <div className="px-2 space-y-2">
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        placeholder="Quest title... (Enter to create)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            handleSubmit()
          }
        }}
      />
      {error && (
        <p className="text-[11px] text-danger font-body px-1">{error}</p>
      )}
    </div>
  )
}
