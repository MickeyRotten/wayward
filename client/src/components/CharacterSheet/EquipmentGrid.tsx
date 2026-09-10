import { useRef, useState } from 'react'
import type { Equipment, Rarity } from '@shared/types/models'
import { useItemsStore } from '../../state/itemsStore'
import { itemFitsSlot } from '../../lib/equipSlots'
import { ItemCard } from '../ItemCard'

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
 * PartyInspector's BlockContentInspector), the one place equipment is
 * edited now. Equipment stays editable in Play mode too (managing gear is a
 * play action, not world-editing), so this has no view/edit mode split. */
export function EquipmentGrid({ equipment, onChange }: {
  equipment: Equipment
  onChange: (slotKey: keyof Equipment, instanceId: string | null) => void
}) {
  return (
    <div className="space-y-3">
      {EQUIP_SLOTS.map(({ key, label }) => (
        <EquipSlotField
          key={key}
          slotKey={key}
          label={label}
          value={equipment[key]}
          onChange={(id) => onChange(key, id)}
        />
      ))}
    </div>
  )
}

/* Equipment slot — mirrors the Inventory "Add Item" pattern, sourced from the
   party's Inventory and filtered to items that fit this slot: an "Equip" button
   when empty, the item + a small remove (×) button when full, and a filterable
   dropdown (no minimum query length) when picking. */
function EquipSlotField({ slotKey, label, value, onChange }: {
  slotKey: keyof Equipment
  label: string
  value: string | null  // an item INSTANCE id (or null)
  onChange: (instanceId: string | null) => void
}) {
  const inventory = useItemsStore((s) => s.inventory)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Resolve the equipped instance id → its catalog item.
  const currentItem = value ? inventory.find((s) => s.instanceId === value)?.item : undefined

  const q = search.toLowerCase().trim()
  // STOWED equipment instances that fit this slot (each copy is selectable).
  const results = inventory
    .filter((s) => !s.equippedBy && s.item && s.item.type === 'Equipment' && itemFitsSlot(s.item.slot, slotKey))
    .filter((s) => !q || (s.item!.name.toLowerCase().includes(q)))
    .sort((a, b) => (a.item!.name).localeCompare(b.item!.name))

  const openPicker = () => { setSearch(''); setOpen(true); setTimeout(() => inputRef.current?.focus(), 0) }
  const closePicker = () => { setOpen(false); setSearch('') }

  const handleSelect = (instanceId: string) => {
    onChange(instanceId)
    closePicker()
  }

  const handleClear = () => {
    onChange(null)
    closePicker()
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
        // Filled slot → the item's card (click to swap). The slot name is
        // omitted; the icon + context convey it. A × unequips it.
        <div className="relative">
          <ItemCard item={currentItem} selected={false} onClick={openPicker} />
          <button
            type="button"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 z-10 text-textdim hover:text-danger text-base font-ui leading-none px-1 bg-bg2/80 rounded"
            onClick={(e) => { e.stopPropagation(); handleClear() }}
            title={`Unequip ${label}`}
          >&times;</button>
        </div>
      ) : (
        // Empty slot → a placeholder that reads the slot's name.
        <button
          type="button"
          className="w-full font-ui text-[11px] text-textsec border border-dashed border-line rounded-md px-3 py-2 hover:border-line2 hover:text-text transition-colors text-left"
          onClick={openPicker}
        >
          {label}
        </button>
      )}
    </div>
  )
}
