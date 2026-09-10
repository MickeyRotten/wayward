import { useRef, useState } from 'react'
import type { Equipment, Rarity } from '@shared/types/models'
import { useItemsStore } from '../../state/itemsStore'
import { usePartyStore } from '../../state/partyStore'
import { useUiStore } from '../../state/uiStore'
import { itemFitsSlot, EQUIP_SLOT_TO_ITEM_SLOT } from '../../lib/equipSlots'
import { ItemCard } from '../ItemCard'
import { ThreeDotMenu } from '../common/ThreeDotMenu'

const RARITY_COLORS: Record<Rarity, string> = {
  c: 'bg-rarity-c',
  u: 'bg-rarity-u',
  r: 'bg-rarity-r',
  e: 'bg-rarity-e',
  l: 'bg-rarity-l',
}

const RARITY_LABELS: Record<Rarity, string> = {
  c: 'Common',
  u: 'Uncommon',
  r: 'Rare',
  e: 'Epic',
  l: 'Legendary',
}

const EQUIP_SLOTS: { key: keyof Equipment; label: string }[] = [
  { key: 'head', label: 'Head' },
  { key: 'neck', label: 'Neck' },
  { key: 'torsoOver', label: 'Torso · Over' },
  { key: 'torsoUnder', label: 'Torso · Under' },
  { key: 'leftHand', label: 'Left Hand' },
  { key: 'rightHand', label: 'Right Hand' },
  { key: 'waist', label: 'Waist' },
  { key: 'legsOver', label: 'Legs · Over' },
  { key: 'legsUnder', label: 'Legs · Under' },
  { key: 'feet', label: 'Feet' },
  { key: 'accessory1', label: 'Accessory I' },
  { key: 'accessory2', label: 'Accessory II' },
]

/** The PC/party member's 12-slot equipment editor — lives inside the block
 * tree's Equipment block/row (see BlockTreeEditor/BlockTreeView and
 * BlockContentInspector), the one place equipment is edited now. Equipment
 * stays editable in Play mode too (managing gear is a play action, not
 * world-editing), so this has no view/edit mode split.
 *
 * Slots follow the same tap-to-open / three-dots-for-actions pattern as the
 * character sheet's Prompt Blocks: tapping a filled slot opens the item's
 * info in place, below the character's still-visible header (CharacterSheetPanel
 * renders it directly rather than navigating away); the three-dot menu offers
 * View/Unequip on a filled slot, or Create an Item on an empty one. */
export function EquipmentGrid({ equipment, onChange, characterId }: {
  equipment: Equipment
  onChange: (slotKey: keyof Equipment, instanceId: string | null) => void
  characterId: string
}) {
  const [openMenuKey, setOpenMenuKey] = useState<keyof Equipment | null>(null)

  return (
    <div className="space-y-3">
      {EQUIP_SLOTS.map(({ key, label }) => (
        <EquipSlotField
          key={key}
          slotKey={key}
          label={label}
          value={equipment[key]}
          onChange={(id) => onChange(key, id)}
          characterId={characterId}
          menuOpen={openMenuKey === key}
          onToggleMenu={() => setOpenMenuKey(openMenuKey === key ? null : key)}
          onCloseMenu={() => setOpenMenuKey(null)}
        />
      ))}
    </div>
  )
}

/* Equipment slot. Empty: a placeholder that opens a filterable picker of
   fitting stowed inventory (unchanged), plus a three-dot menu to create a
   brand-new item straight into the slot. Filled: tapping the item opens its
   info in place under the character's header (clicking a tab backs back out);
   the three-dot menu offers View/Unequip — there is no more "tap to swap",
   swapping is Unequip then re-pick. */
function EquipSlotField({ slotKey, label, value, onChange, characterId, menuOpen, onToggleMenu, onCloseMenu }: {
  slotKey: keyof Equipment
  label: string
  value: string | null  // an item INSTANCE id (or null)
  onChange: (instanceId: string | null) => void
  characterId: string
  menuOpen: boolean
  onToggleMenu: () => void
  onCloseMenu: () => void
}) {
  const inventory = useItemsStore((s) => s.inventory)
  const createItem = useItemsStore((s) => s.createItem)
  const equipItem = usePartyStore((s) => s.equipItem)
  const unequipSlot = usePartyStore((s) => s.unequipSlot)
  const selectInto = useUiStore((s) => s.selectInto)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Resolve the equipped instance id → its catalog item.
  const currentItem = value ? inventory.find((s) => s.instanceId === value)?.item : undefined

  const q = search.toLowerCase().trim()
  // STOWED equipment instances that fit this slot (each copy is selectable).
  const results = inventory
    .filter((s) => !s.equippedBy && s.item && s.item.type === 'Equipment' && itemFitsSlot(s.item.slot, slotKey))
    .filter((s) => !q || (s.item!.name.toLowerCase().includes(q)))
    .sort((a, b) => (a.item!.name).localeCompare(b.item!.name))

  const openPicker = () => { setSearch(''); setOpen(true); onCloseMenu(); setTimeout(() => inputRef.current?.focus(), 0) }
  const closePicker = () => { setOpen(false); setSearch('') }

  const handleSelect = (instanceId: string) => {
    onChange(instanceId)
    closePicker()
  }

  const viewItem = () => {
    if (!value) return
    onCloseMenu()
    selectInto({ kind: 'item', id: currentItem!.id, instanceId: value })
  }

  const handleUnequip = async () => {
    onCloseMenu()
    await unequipSlot(characterId, slotKey)
  }

  const handleCreateItem = async () => {
    onCloseMenu()
    setCreateError('')
    setCreating(true)
    try {
      const item = await createItem({
        name: '', type: 'Equipment', slot: EQUIP_SLOT_TO_ITEM_SLOT[slotKey],
        rarity: 'c', desc: '', maxStack: 1, keywords: [], enabled: true, permanent: false,
      })
      await equipItem(characterId, item.id, slotKey)
      const minted = useItemsStore.getState().inventory.find((s) => s.itemId === item.id && s.equippedBy === characterId)
      selectInto({ kind: 'item', id: item.id, instanceId: minted?.instanceId, lockTypeSlot: true, openInEdit: true })
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create item')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="relative">
      {open ? (
        <div>
          <input
            ref={inputRef}
            className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
            placeholder={`Filter for ${label}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onBlur={() => setTimeout(closePicker, 200)}
          />
          <div className="absolute z-20 left-0 right-0 mt-0.5 border border-line bg-bg1 max-h-40 overflow-y-auto shadow-lg">
            {results.length === 0 ? (
              <div className="px-2.5 py-2 text-xs text-textdim font-body">No matching items in inventory</div>
            ) : (
              results.map((stack) => {
                const item = stack.item!
                return (
                  <button
                    key={stack.instanceId}
                    type="button"
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-bg2 text-left"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleSelect(stack.instanceId)}
                  >
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[item.rarity] || RARITY_COLORS.c}`}
                      title={RARITY_LABELS[item.rarity] || 'Common'}
                    />
                    <span className="text-sm font-body text-text truncate">{item.name}</span>
                    {item.slot && (
                      <span className="text-[10px] text-textdim font-ui ml-auto shrink-0">{item.slot}</span>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>
      ) : currentItem ? (
        // Filled slot → tap opens the item's info; the three-dot menu offers
        // View (same thing) / Unequip.
        <div className="flex items-start gap-1">
          <ThreeDotMenu
            open={menuOpen}
            onToggle={onToggleMenu}
            items={[
              { label: 'View', onClick: viewItem },
              { label: 'Unequip', danger: true, onClick: handleUnequip },
            ]}
          />
          <div className="flex-1 min-w-0">
            <ItemCard item={currentItem} selected={false} onClick={viewItem} />
          </div>
        </div>
      ) : (
        // Empty slot → tap opens the existing stowed-item picker; the
        // three-dot menu offers Create an Item straight into this slot.
        <div className="flex items-start gap-1">
          <ThreeDotMenu
            open={menuOpen}
            onToggle={onToggleMenu}
            items={[
              { label: 'Create an Item', onClick: handleCreateItem },
            ]}
          />
          <button
            type="button"
            disabled={creating}
            className="flex-1 min-w-0 font-ui text-[11px] text-textsec border border-dashed border-line rounded-md px-3 py-2 hover:border-line2 hover:text-text transition-colors text-left disabled:opacity-50"
            onClick={openPicker}
          >
            {creating ? 'Creating…' : label}
          </button>
        </div>
      )}
      {createError && <p className="text-[11px] text-danger font-body mt-1">{createError}</p>}
    </div>
  )
}
