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
      className={`relative w-full text-left pl-4 pr-2.5 py-1.5 border rounded-md overflow-hidden transition-colors ${
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
      {selected && <span className="absolute left-[6px] top-1.5 bottom-1.5 w-[2px] bg-gold" aria-hidden="true" />}
      <div className="flex items-center gap-2.5">
        {/* The type icon conveys the item type — no text sub-header needed. */}
        <ItemTypeIcon type={item.type} className="text-gold shrink-0" title={item.type} />
        <span className="font-body text-sm text-text truncate flex-1 min-w-0">{item.name || 'Unnamed'}</span>
        {count !== undefined && count > 1 && (
          <span className="font-ui text-[10px] text-textsec shrink-0">x{count}</span>
        )}
        {/* Equipped copies → a first-letter badge per wearer on the right. */}
        {equippedBy && equippedBy.length > 0 && (
          <span className="flex items-center gap-1 shrink-0">
            {equippedBy.map((name, i) => (
              <EquippedByBadge key={i} name={name} />
            ))}
          </span>
        )}
      </div>
    </button>
  )
}

/** A small gold rounded-rectangle badge showing the first letter of an
    equipping character's name. */
function EquippedByBadge({ name }: { name: string }) {
  const letter = (name || '?').trim()[0]?.toUpperCase() || '?'
  return (
    <span
      className="inline-flex items-center justify-center w-[18px] h-[18px] rounded-[4px] bg-gold/15 border border-gold/40 text-gold2 font-ui text-[10px] leading-none"
      title={`Equipped · ${name}`}
    >
      {letter}
    </span>
  )
}
