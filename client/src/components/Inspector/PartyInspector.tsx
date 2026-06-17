import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { CharacterSheetEditor } from '../CharacterSheet/CharacterSheetEditor'
import { PartyMemberEditor } from '../PartyMember/PartyMemberEditor'

export function PartyInspector() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const members = usePartyStore((s) => s.partyMembers)
  const selection = useUiStore((s) => s.selection)

  if (selection?.type === 'player' && pc) {
    return <CharacterSheetEditor />
  }

  if (selection?.type === 'member') {
    const member = members.find((m) => m.id === selection.id)
    if (member) {
      return <PartyMemberEditor key={member.id} member={member} />
    }
  }

  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-2">
        <p className="font-ui text-[10px] text-text-dim tracking-wider">INSPECTOR</p>
        <p className="text-[12px] text-text-sec font-b">
          Select a character from the party to view and edit their sheet.
        </p>
      </div>
    </div>
  )
}
