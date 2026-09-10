import type { PartyMember } from '@shared/types/models'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { CharacterSheetPanel } from '../CharacterSheet/CharacterSheetPanel'

export function PartyMemberEditor({ member }: { member: PartyMember }) {
  const saveBlocks = usePartyStore((s) => s.savePartyMemberBlocks)
  const saveEquipment = usePartyStore((s) => s.savePartyMemberEquipment)
  const remove = usePartyStore((s) => s.removePartyMember)
  const fetchAll = usePartyStore((s) => s.fetchAll)
  const select = useUiStore((s) => s.select)

  return (
    <CharacterSheetPanel
      owner={member}
      ownerType="member"
      onSaveBlocks={(blocks, name) => void saveBlocks(member.id, blocks, name)}
      onSaveEquipment={(equipment) => void saveEquipment(member.id, equipment)}
      onRemove={async () => { await remove(member.id); select(null) }}
      onPortraitUpdated={() => void fetchAll()}
    />
  )
}
