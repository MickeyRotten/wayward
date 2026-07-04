import { ITEM_TYPE_TABS, type ItemTypeTab } from '../lib/itemTypes'

// A compact, wrapping row of type-filter chips shared by the Inventory and
// Lore → Items lists.
export function ItemTypeTabs({ value, onChange }: {
  value: ItemTypeTab
  onChange: (t: ItemTypeTab) => void
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {ITEM_TYPE_TABS.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onChange(t)}
          className={`font-ui text-[9px] tracking-wider uppercase px-2 py-1 border rounded transition-colors ${
            value === t
              ? 'border-gold text-gold bg-gold/10'
              : 'border-line text-textdim hover:text-text hover:border-line2'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
