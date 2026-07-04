import type { Rarity } from '@shared/types/models'

// Shared sorting for the Lorebook and Inventory lists so both stay identical.

export type SortKey = 'newest' | 'alpha' | 'type' | 'rarity'

export const SORT_OPTIONS: { id: SortKey; label: string }[] = [
  { id: 'newest', label: 'By newest' },
  { id: 'alpha', label: 'Alphabetically' },
  { id: 'type', label: 'By type' },
  { id: 'rarity', label: 'By rarity' },
]

export const RARITY_ORDER: Record<Rarity, number> = { c: 0, u: 1, r: 2, e: 3, l: 4 }

/** Sort a list (preserving insertion order as the 'newest' basis / tiebreak). */
export function sortList<T>(
  list: T[],
  key: SortKey,
  asc: boolean,
  get: { name: (x: T) => string; type: (x: T) => string; rarity: (x: T) => number },
): T[] {
  const indexed = list.map((x, i) => ({ x, i }))
  indexed.sort((a, b) => {
    let c = 0
    // Coerce to string so a missing name/type never throws (blanking the panel).
    if (key === 'alpha') c = String(get.name(a.x) ?? '').localeCompare(String(get.name(b.x) ?? ''))
    else if (key === 'type') c = String(get.type(a.x) ?? '').localeCompare(String(get.type(b.x) ?? ''))
    else if (key === 'rarity') c = (get.rarity(a.x) || 0) - (get.rarity(b.x) || 0)
    return c !== 0 ? c : a.i - b.i // stable; 'newest' = pure insertion order
  })
  const out = indexed.map((o) => o.x)
  return asc ? out : out.reverse()
}
