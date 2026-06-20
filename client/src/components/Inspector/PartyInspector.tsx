import { useEffect, useState } from 'react'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { CharacterSheetEditor } from '../CharacterSheet/CharacterSheetEditor'
import { PartyMemberEditor } from '../PartyMember/PartyMemberEditor'

export function PartyInspector() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const selection = useUiStore((s) => s.selection)
  const everSelected = useUiStore((s) => s.everSelected)
  const mode = useUiStore((s) => s.mode)
  const editDirty = useUiStore((s) => s.editDirty)
  const setMode = useUiStore((s) => s.setMode)

  if (!everSelected) return <EmptyState />

  // Resolve the selected entity
  const selIsPC = selection?.kind === 'player' && !!pc
  const selMember = selection?.kind === 'member'
    ? members.find((m) => m.id === selection.id)
    : undefined
  const selIsMember = !!selMember

  const hasSelection = selIsPC || selIsMember

  // Derive entity name for the header
  const entityName = selIsPC
    ? (pc!.basicInfo.name || 'New Character')
    : selIsMember
      ? (selMember!.basicInfo.name || 'New Member')
      : ''

  const entityLabel = selIsPC ? 'PLAYER CHARACTER' : selIsMember ? 'PARTY MEMBER' : ''

  return (
    <div className="flex flex-col h-full">
      {/* Inspector Header */}
      {hasSelection && (
        <div className="shrink-0 border-b border-line px-6 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="font-ui text-[9px] text-textdim tracking-wider">{entityLabel}</span>
              <h2 className="font-disp text-[24px] pt-0.75 leading-none text-text truncate">
                {entityName}
              </h2>
            </div>
            <div className="flex items-center gap-2 shrink-0 mt-1">
              {/* Edit dirty indicator */}
              {editDirty && (
                <span
                  className="w-1.5 h-1.5 rounded-full bg-gold"
                  title="Unsaved changes"
                />
              )}
              {/* View/Edit toggle */}
              <button
                type="button"
                className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border-[1.5px] transition-colors ${
                  mode === 'view'
                    ? 'text-textsec border-line hover:text-text hover:border-line2'
                    : 'text-gold border-gold/40 hover:border-gold/60'
                }`}
                onClick={() => setMode(mode === 'view' ? 'edit' : 'view')}
              >
                {mode === 'view' ? 'EDIT' : 'VIEW'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Inspector Body — single scrollable child */}
      <div className="flex-1 overflow-y-auto">
        {hasSelection && <SaveIndicator />}
        {selIsPC ? (
          <CharacterSheetEditor mode={mode} />
        ) : selIsMember ? (
          <PartyMemberEditor key={selMember!.id} member={selMember!} mode={mode} />
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  )
}

function SaveIndicator() {
  const lastSavedAt = usePartyStore((s) => s.lastSavedAt)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!lastSavedAt) return
    setVisible(true)
    const timer = setTimeout(() => setVisible(false), 1500)
    return () => clearTimeout(timer)
  }, [lastSavedAt])

  return (
    <div
      className={`sticky top-0 z-10 text-right pr-6 pt-2 font-ui text-[9px] text-textdim tracking-wider transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
    >
      SAVED
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-2">
        <p className="font-ui text-[10px] text-textdim tracking-wider">INSPECTOR</p>
        <p className="text-[12px] text-textsec font-body">
          Select a character from the party to view and edit their sheet.
        </p>
      </div>
    </div>
  )
}
