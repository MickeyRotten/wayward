// Type filter tabs shared by the Inventory and Lore → Items lists.

export const ITEM_TYPE_TABS = [
  'All', 'Equipment', 'Tool', 'Consumable', 'Key Item', 'Artifact', 'Other',
] as const

export type ItemTypeTab = (typeof ITEM_TYPE_TABS)[number]

// The concrete types a tab named after a type matches; "Other" is the catch-all.
const KNOWN_TYPES = ['Equipment', 'Tool', 'Consumable', 'Key Item', 'Artifact']

export function matchesTypeTab(itemType: string | undefined | null, tab: ItemTypeTab): boolean {
  if (tab === 'All') return true
  const t = itemType || ''
  if (tab === 'Other') return !KNOWN_TYPES.includes(t)
  return t === tab
}
