import { usePartyStore } from '../../state/partyStore'
import { CharacterSheetPanel } from './CharacterSheetPanel'

export function CharacterSheetEditor() {
  const pc = usePartyStore((s) => s.playerCharacter)
  const saveBlocks = usePartyStore((s) => s.savePlayerCharacterBlocks)
  const saveEquipment = usePartyStore((s) => s.savePlayerCharacterEquipment)
  const fetchAll = usePartyStore((s) => s.fetchAll)

  if (!pc) return null

  return (
    <CharacterSheetPanel
      owner={pc}
      ownerType="player"
      onSaveBlocks={(blocks, name) => void saveBlocks(blocks, name)}
      onSaveEquipment={(equipment) => void saveEquipment(equipment)}
      onPortraitUpdated={() => void fetchAll()}
    />
  )
}
