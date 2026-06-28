import { ItemTypeIcon } from './ItemTypeIcon'
import type { ItemCatalogEntry, Rarity } from '@shared/types/models'

export const RARITY_COLORS: Record<Rarity, string> = {
  c: 'bg-rarity-c', u: 'bg-rarity-u', r: 'bg-rarity-r', e: 'bg-rarity-e', l: 'bg-rarity-l',
}
const RARITY_LABELS: Record<Rarity, string> = {
  c: 'Common', u: 'Uncommon', r: 'Rare', e: 'Epic', l: 'Legendary',
}

/* Inventory / catalog item card: a type icon, a thick rarity bar on the left
   edge, and (when selected) a gold accent bar offset to the right of the rarity
   bar so the two never overlap. Used by the Inventory panel and Lore → Items. */
export function ItemCard({
  item, selected, count, onClick, equippedBy,
}: {
  item: ItemCatalogEntry
  selected: boolean
  count?: number
  onClick: () => void
  /** Names of characters currently wearing this item (inventory view). */
  equippedBy?: string[]
}) {
  const rarity = item.rarity as Rarity
  return (
    <button
      type="button"
      className={`relative w-full text-left pl-4 pr-3 py-2.5 border rounded-md overflow-hidden transition-colors ${
        selected ? 'border-line bg-bg3' : 'border-line bg-bg2 hover:border-line2'
      }`}
      onClick={onClick}
    >
      {/* Rarity — thick bar on the very left edge */}
      <span
        className={`absolute left-0 top-0 bottom-0 w-[3px] ${RARITY_COLORS[rarity] || RARITY_COLORS.c}`}
        title={RARITY_LABELS[rarity] || 'Common'}
      />
      {/* Selection accent — offset right of the rarity bar so they don't overlap */}
      {selected && <span className="absolute left-[6px] top-2.5 bottom-2.5 w-[2px] bg-gold" aria-hidden="true" />}
      <div className="flex items-center gap-2.5">
        <ItemTypeIcon type={item.type} className="text-gold shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-body text-sm text-text truncate">{item.name || 'Unnamed'}</span>
            {count !== undefined && count > 1 && (
              <span className="font-ui text-[10px] text-textsec shrink-0">x{count}</span>
            )}
          </div>
          <span className="font-ui text-[8px] text-textdim tracking-wider uppercase">{item.type}</span>
          {equippedBy && equippedBy.length > 0 && (
            <div className="flex items-center gap-1 mt-0.5 text-gold2">
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                <path d="M20 6 9 17l-5-5" />
              </svg>
              <span className="font-ui text-[8px] tracking-wider uppercase truncate">
                Equipped · {equippedBy.join(', ')}
              </span>
            </div>
          )}
        </div>
      </div>
    </button>
  )
}
