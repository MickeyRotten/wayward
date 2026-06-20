import { useState } from 'react'
import { useLoreStore } from '../../state/loreStore'
import { useUiStore } from '../../state/uiStore'
import type { LoreCategory } from '@shared/types/models'

const CATEGORY_TABS: { id: LoreCategory; label: string }[] = [
  { id: 'world', label: 'World' },
  { id: 'characters', label: 'Characters' },
  { id: 'items', label: 'Items' },
  { id: 'monsters', label: 'Monsters' },
  { id: 'spells', label: 'Spells' },
]

export function LorePanel() {
  const entries = useLoreStore((s) => s.entries)
  const activeCategory = useLoreStore((s) => s.activeCategory)
  const searchQuery = useLoreStore((s) => s.searchQuery)
  const setCategory = useLoreStore((s) => s.setCategory)
  const setSearchQuery = useLoreStore((s) => s.setSearchQuery)
  const createEntry = useLoreStore((s) => s.createEntry)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [createError, setCreateError] = useState('')

  // Filter entries by active category
  const categoryEntries = entries.filter((e) => e.cat === activeCategory)

  // Filter by search query (title or keywords)
  const query = searchQuery.toLowerCase().trim()
  const filteredEntries = query
    ? categoryEntries.filter(
        (e) =>
          e.title.toLowerCase().includes(query) ||
          e.keywords.some((k) => k.toLowerCase().includes(query))
      )
    : categoryEntries

  const isSelected = (id: string) =>
    selection?.kind === 'lore' && selection.id === id

  const handleCreate = async () => {
    setCreateError('')
    try {
      const entry = await createEntry(activeCategory)
      select({ kind: 'lore', id: entry.id })
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create entry')
    }
  }

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
            className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border-[1.5px] transition-colors ${
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
          className="w-full border-[1.5px] border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
          placeholder="Search by title or keyword..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Entry list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {filteredEntries.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-4 py-3 text-center">
            {query ? 'No matching entries' : 'No entries in this category'}
          </p>
        )}

        <div className="space-y-1">
          {filteredEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`w-full text-left px-3 py-2.5 border-[1.5px] transition-colors ${
                isSelected(entry.id)
                  ? 'border-line2 bg-bg0'
                  : 'border-transparent hover:bg-bg2'
              }`}
              onClick={() => select({ kind: 'lore', id: entry.id })}
            >
              <div className="flex items-center gap-2">
                {/* Enabled indicator dot */}
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    entry.enabled ? 'bg-[#5a9e6f]' : 'bg-textdim/40'
                  }`}
                  title={entry.enabled ? 'Enabled' : 'Disabled'}
                />
                <span className="font-body text-sm text-text truncate flex-1">
                  {entry.title || 'Untitled'}
                </span>
                {entry.keywords.length > 0 && (
                  <span className="font-ui text-[10px] text-textsec shrink-0">
                    {entry.keywords.length} kw
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* New entry button */}
      <div className="shrink-0 px-4 pb-4">
        <button
          type="button"
          className="w-full font-ui text-[10px] tracking-wider text-textsec border-[1.5px] border-line hover:border-line2 hover:text-text px-3 py-2 transition-colors text-center"
          onClick={handleCreate}
        >
          + NEW ENTRY
        </button>
        {createError && (
          <p className="text-[11px] text-red-400 font-body mt-1 px-1">{createError}</p>
        )}
      </div>
    </div>
  )
}
