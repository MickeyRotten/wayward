import { useState } from 'react'
import { useLoreStore } from '../../state/loreStore'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { SelectionBar } from '../SelectionBar'
import { ItemCard } from '../ItemCard'
import { CategoryIcon } from '../CategoryIcon'
import type { LoreCategory, LorebookEntry } from '@shared/types/models'

const CATEGORY_TABS: { id: LoreCategory; label: string }[] = [
  { id: 'world', label: 'World' },
  { id: 'characters', label: 'Characters' },
  { id: 'items', label: 'Items' },
  { id: 'monsters', label: 'Monsters' },
  { id: 'spells', label: 'Spells' },
]

export function LorePanel() {
  const entries = useLoreStore((s) => s.entries)
  const catalog = useItemsStore((s) => s.catalog)
  const activeCategory = useLoreStore((s) => s.activeCategory)
  const searchQuery = useLoreStore((s) => s.searchQuery)
  const setCategory = useLoreStore((s) => s.setCategory)
  const setSearchQuery = useLoreStore((s) => s.setSearchQuery)
  const createEntry = useLoreStore((s) => s.createEntry)
  const createItem = useItemsStore((s) => s.createItem)
  const editMode = useChatStore((s) => s.planningMode)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [createError, setCreateError] = useState('')

  const isItems = activeCategory === 'items'
  const query = searchQuery.toLowerCase().trim()

  // Items category draws from the catalog (full item data); other categories
  // from the lorebook entries.
  const itemList = catalog.filter((i) => !query || i.name.toLowerCase().includes(query))
  const filteredEntries = entries
    .filter((e) => e.cat === activeCategory)
    .filter((e) => !query || e.title.toLowerCase().includes(query) || e.keywords.some((k) => k.toLowerCase().includes(query)))

  const isItemSelected = (id: string) => selection?.kind === 'item' && selection.id === id
  const isLoreSelected = (id: string) => selection?.kind === 'lore' && selection.id === id

  const handleCreate = async () => {
    setCreateError('')
    try {
      if (isItems) {
        const item = await createItem({ name: '', type: 'Other', rarity: 'c', desc: '', maxStack: 1 })
        select({ kind: 'item', id: item.id })
      } else {
        const entry = await createEntry(activeCategory)
        select({ kind: 'lore', id: entry.id })
      }
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create entry')
    }
  }

  const empty = isItems ? itemList.length === 0 : filteredEntries.length === 0

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">LOREBOOK</h2>
      </div>

      {/* Category sub-tabs */}
      <div className="px-4 pb-3 flex flex-wrap gap-1.5">
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border transition-colors ${
              activeCategory === tab.id
                ? 'text-gold border-gold/40 bg-gold/5'
                : 'text-textsec border-line hover:text-text hover:border-line2'
            }`}
            onClick={() => setCategory(tab.id)}
          >
            {tab.label.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Search input */}
      <div className="px-4 pb-3">
        <input
          className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
          placeholder="Search by title or keyword..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Entry list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {empty && (
          <p className="text-[12px] text-textdim font-body px-4 py-3 text-center">
            {query ? 'No matching entries' : 'No entries in this category'}
          </p>
        )}

        <div className="space-y-1.5">
          {isItems
            ? itemList.map((item) => (
                <ItemCard
                  key={item.id}
                  item={item}
                  selected={isItemSelected(item.id)}
                  onClick={() => select({ kind: 'item', id: item.id })}
                />
              ))
            : filteredEntries.map((entry) => (
                <LoreCard
                  key={entry.id}
                  entry={entry}
                  selected={isLoreSelected(entry.id)}
                  onClick={() => select({ kind: 'lore', id: entry.id })}
                />
              ))}
        </div>
      </div>

      {/* New entry button — adding entries is the domain of Edit Mode */}
      {editMode && (
        <div className="shrink-0 px-4 pb-4">
          <button
            type="button"
            className="w-full font-ui text-[10px] tracking-wider text-textsec border border-line hover:border-line2 hover:text-text px-3 py-2 transition-colors text-center"
            onClick={handleCreate}
          >
            + NEW ENTRY
          </button>
          {createError && (
            <p className="text-[11px] text-danger font-body mt-1 px-1">{createError}</p>
          )}
        </div>
      )}
    </div>
  )
}

function LockGlyph() {
  return <span className="font-ui text-[10px] text-gold2 shrink-0" title="Locked">&#128274;</span>
}

/* Lorebook card. Characters use a PC-style edge-to-edge initial avatar; other
   categories use the item-card layout with a category icon and no rarity bar.
   Disabled entries are dimmed. */
function LoreCard({ entry, selected, onClick }: { entry: LorebookEntry; selected: boolean; onClick: () => void }) {
  const subtitle = `${entry.cat}${entry.keywords.length ? ` · ${entry.keywords.length} kw` : ''}`
  const base = `group relative w-full text-left border rounded-md overflow-hidden transition-colors ${
    selected ? 'border-line bg-bg3' : 'border-line bg-bg2 hover:border-line2'
  } ${entry.enabled ? '' : 'opacity-60'}`

  if (entry.cat === 'characters') {
    return (
      <button type="button" className={`${base} flex items-stretch`} onClick={onClick}>
        <SelectionBar show={selected} />
        <div className="w-14 self-stretch shrink-0 border-r border-line bg-bg3 flex items-center justify-center">
          <span className="font-disp text-[20px] text-textdim pt-[2px]">{(entry.title || '?')[0].toUpperCase()}</span>
        </div>
        <div className="min-w-0 flex-1 px-3 py-3 flex flex-col justify-center">
          <div className="flex items-center gap-2">
            <span className="font-body text-sm text-text truncate flex-1">{entry.title || 'Untitled'}</span>
            {entry.locked && <LockGlyph />}
          </div>
          <span className="font-ui text-[8px] text-textdim tracking-wider uppercase">{subtitle}</span>
        </div>
      </button>
    )
  }

  return (
    <button type="button" className={`${base} pl-3 pr-3 py-2.5`} onClick={onClick}>
      <SelectionBar show={selected} />
      <div className="flex items-center gap-2.5">
        <CategoryIcon cat={entry.cat} className="text-gold shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-body text-sm text-text truncate flex-1">{entry.title || 'Untitled'}</span>
            {entry.locked && <LockGlyph />}
          </div>
          <span className="font-ui text-[8px] text-textdim tracking-wider uppercase">{subtitle}</span>
        </div>
      </div>
    </button>
  )
}
