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

  if (!everSelected) return <EmptyState />

  const hasSelection = (selection?.kind === 'player' && pc) ||
    (selection?.kind === 'member' && members.some((m) => m.id === (selection as { kind: 'member'; id: string }).id))

  return (
    <div className="relative h-full">
      {hasSelection && <SaveIndicator />}
      {selection?.kind === 'player' && pc ? (
        <CharacterSheetEditor />
      ) : selection?.kind === 'member' ? (
        (() => {
          const member = members.find((m) => m.id === selection.id)
          return member ? <PartyMemberEditor key={member.id} member={member} /> : <EmptyState />
        })()
      ) : (
        <EmptyState />
      )}
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
      className={`absolute top-2 right-2 z-10 font-ui text-[9px] text-textdim tracking-wider transition-opacity duration-300 ${
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
