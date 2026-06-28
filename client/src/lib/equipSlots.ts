import type { Equipment } from '@shared/types/models'

// Items carry a coarse, free-text `slot` ("Head", "Torso", "Hands", …) while
// the equipment grid has 12 fine slots. This maps each fine slot to the coarse
// slot category tokens an item may use to fill it.
const SLOT_CATEGORIES: Record<keyof Equipment, string[]> = {
  head: ['head'],
  neck: ['neck'],
  torsoOver: ['torso', 'chest', 'body'],
  torsoUnder: ['torso', 'chest', 'body'],
  leftHand: ['hand', 'weapon', 'shield', 'offhand'],
  rightHand: ['hand', 'weapon'],
  waist: ['waist', 'belt'],
  legsOver: ['leg', 'legs'],
  legsUnder: ['leg', 'legs'],
  feet: ['feet', 'foot', 'boot'],
  accessory1: ['accessory', 'ring', 'trinket', 'charm'],
  accessory2: ['accessory', 'ring', 'trinket', 'charm'],
}

// The 12 equipment slots in display order.
export const EQUIP_SLOT_KEYS = Object.keys(SLOT_CATEGORIES) as (keyof Equipment)[]

export const EQUIP_SLOT_LABELS: Record<keyof Equipment, string> = {
  head: 'Head', neck: 'Neck', torsoOver: 'Torso (over)', torsoUnder: 'Torso (under)',
  leftHand: 'Left Hand', rightHand: 'Right Hand', waist: 'Waist',
  legsOver: 'Legs (over)', legsUnder: 'Legs (under)', feet: 'Feet',
  accessory1: 'Accessory I', accessory2: 'Accessory II',
}

/**
 * Whether an item's free-text slot fits the given equipment slot. An item with
 * no slot is allowed everywhere (we can't know where it goes), so user-created
 * equipment that omits a slot still appears.
 */
export function itemFitsSlot(itemSlot: string | undefined | null, slotKey: keyof Equipment): boolean {
  if (!itemSlot) return true
  const s = itemSlot.toLowerCase()
  return SLOT_CATEGORIES[slotKey].some((cat) => s.includes(cat))
}

/**
 * Pick the best equipment slot on a character for an item: prefer an empty slot
 * the item fits, else the first fitting slot (whose occupant will be replaced).
 * Falls back to all slots if the item's slot string matches none.
 */
export function pickEquipSlot(
  itemSlot: string | undefined | null,
  equipment: Equipment,
): keyof Equipment {
  let candidates = EQUIP_SLOT_KEYS.filter((k) => itemFitsSlot(itemSlot, k))
  if (candidates.length === 0) candidates = EQUIP_SLOT_KEYS
  return candidates.find((k) => !equipment[k]) ?? candidates[0]
}
