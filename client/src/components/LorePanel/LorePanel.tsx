import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useLoreStore } from '../../state/loreStore'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { SelectionBar } from '../SelectionBar'
import { ItemCard } from '../ItemCard'
import { CategoryIcon } from '../CategoryIcon'
import { ConfirmDialog } from '../ConfirmDialog'
import { ScenarioEditor } from './ScenarioEditor'
import { type SortKey, SORT_OPTIONS, RARITY_ORDER, sortList } from '../../lib/sortEntries'
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
  const deleteEntry = useLoreStore((s) => s.deleteEntry)
  const createItem = useItemsStore((s) => s.createItem)
  const deleteItem = useItemsStore((s) => s.deleteItem)
  const editMode = useChatStore((s) => s.planningMode)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [selectedTab, setSelectedTab] = useState<'scenario' | LoreCategory>('scenario')
  const [createError, setCreateError] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('newest')
  const [sortAsc, setSortAsc] = useState(false)
  const [removeMode, setRemoveMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmRemove, setConfirmRemove] = useState(false)

  const isItems = activeCategory === 'items'
  const query = searchQuery.toLowerCase().trim()

  // Cancel remove-mode when the view changes (category switch or leaving Edit).
  useEffect(() => {
    setRemoveMode(false)
    setSelectedIds(new Set())
  }, [activeCategory, editMode])

  // Items category draws from the catalog (full item data); other categories
  // from the lorebook entries. Both filtered, then sorted.
  const itemList = useMemo(
    () => sortList(
      catalog.filter((i) => !query || i.name.toLowerCase().includes(query)),
      sortKey, sortAsc,
      { name: (i) => i.name, type: (i) => i.type, rarity: (i) => RARITY_ORDER[i.rarity] ?? 0 },
    ),
    [catalog, query, sortKey, sortAsc],
  )
  const filteredEntries = useMemo(
    () => sortList(
      entries
        .filter((e) => e.cat === activeCategory)
        .filter((e) => !(e.locked && e.title === 'Scenario'))
        .filter((e) => !query || e.title.toLowerCase().includes(query) || e.keywords.some((k) => k.toLowerCase().includes(query))),
      sortKey, sortAsc,
      { name: (e) => e.title, type: (e) => e.cat, rarity: () => 0 },
    ),
    [entries, activeCategory, query, sortKey, sortAsc],
  )

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const cancelRemove = () => { setRemoveMode(false); setSelectedIds(new Set()) }

  const handleRemoveSelected = async () => {
    setConfirmRemove(false)
    const ids = [...selectedIds]
    for (const id of ids) {
      try {
        if (isItems) await deleteItem(id)
        else await deleteEntry(id)
      } catch { /* skip (e.g. locked) */ }
    }
    cancelRemove()
  }

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

      {/* Category sub-tabs — Scenario first, then the 5 generic categories */}
      <div className="px-4 pb-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border transition-colors ${
            selectedTab === 'scenario'
              ? 'text-gold border-gold/40 bg-gold/5'
              : 'text-textsec border-line hover:text-text hover:border-line2'
          }`}
          onClick={() => setSelectedTab('scenario')}
        >
          SCENARIO
        </button>
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`font-ui text-[9px] tracking-wider px-2.5 py-1 border transition-colors ${
              selectedTab === tab.id
                ? 'text-gold border-gold/40 bg-gold/5'
                : 'text-textsec border-line hover:text-text hover:border-line2'
            }`}
            onClick={() => { setSelectedTab(tab.id); setCategory(tab.id) }}
          >
            {tab.label.toUpperCase()}
          </button>
        ))}
      </div>

      {selectedTab !== 'scenario' && (
        <>
          {/* Search input */}
          <div className="px-4 pb-2">
            <input
              className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
              placeholder="Search by title or keyword..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Sorting (available in both modes) */}
          <div className="px-4 pb-3 flex items-center gap-2">
            <span className="font-ui text-[9px] tracking-wider text-textdim uppercase shrink-0">Sorting:</span>
            <select
              className="flex-1 min-w-0 border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text outline-none focus:border-line2"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
            <button
              type="button"
              title={sortAsc ? 'Ascending' : 'Descending'}
              className="shrink-0 border border-line text-textsec hover:text-text hover:border-line2 px-1.5 py-1 transition-colors"
              onClick={() => setSortAsc((a) => !a)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {sortAsc ? <path d="M12 19V5M5 12l7-7 7 7" /> : <path d="M12 5v14M5 12l7 7 7-7" />}
              </svg>
            </button>
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
                    <SelectableRow
                      key={item.id}
                      removeMode={removeMode}
                      checked={selectedIds.has(item.id)}
                      removable
                      onToggle={() => toggleSelected(item.id)}
                    >
                      <ItemCard
                        item={item}
                        selected={removeMode ? selectedIds.has(item.id) : isItemSelected(item.id)}
                        onClick={() => (removeMode ? toggleSelected(item.id) : select({ kind: 'item', id: item.id }))}
                      />
                    </SelectableRow>
                  ))
                : filteredEntries.map((entry) => (
                    <SelectableRow
                      key={entry.id}
                      removeMode={removeMode}
                      checked={selectedIds.has(entry.id)}
                      removable={!entry.locked}
                      onToggle={() => toggleSelected(entry.id)}
                    >
                      <LoreCard
                        entry={entry}
                        selected={removeMode ? selectedIds.has(entry.id) : isLoreSelected(entry.id)}
                        onClick={() => {
                          if (!removeMode) select({ kind: 'lore', id: entry.id })
                          else if (!entry.locked) toggleSelected(entry.id)
                        }}
                      />
                    </SelectableRow>
                  ))}
            </div>
          </div>

          {/* Footer — managing entries is the domain of Edit Mode */}
          {editMode && (
            <div className="shrink-0 px-4 pb-4 space-y-1.5">
              {removeMode ? (
                <>
                  <button
                    type="button"
                    disabled={selectedIds.size === 0}
                    className="w-full font-ui text-[10px] tracking-wider text-danger border border-danger-border bg-danger-bg hover:text-danger-hover px-3 py-2 transition-colors text-center disabled:opacity-30 disabled:cursor-not-allowed"
                    onClick={() => setConfirmRemove(true)}
                  >
                    REMOVE SELECTED ENTRIES{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
                  </button>
                  <button
                    type="button"
                    className="w-full font-ui text-[10px] tracking-wider text-textsec border border-line hover:border-line2 hover:text-text px-3 py-2 transition-colors text-center"
                    onClick={cancelRemove}
                  >
                    CANCEL
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="w-full font-ui text-[10px] tracking-wider text-textsec border border-line hover:border-line2 hover:text-text px-3 py-2 transition-colors text-center"
                    onClick={() => setRemoveMode(true)}
                  >
                    REMOVE ENTRIES
                  </button>
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
                </>
              )}
            </div>
          )}

          {confirmRemove && (
            <ConfirmDialog
              confirmLabel="REMOVE"
              message={`Remove ${selectedIds.size} selected ${isItems ? 'item' : 'entry'}(s)? This cannot be undone.`}
              onConfirm={handleRemoveSelected}
              onCancel={() => setConfirmRemove(false)}
            />
          )}
        </>
      )}

      {selectedTab === 'scenario' && <ScenarioEditor />}
    </div>
  )
}

/** Wraps a card with a checkbox when in remove-mode. */
function SelectableRow({
  removeMode, checked, removable, onToggle, children,
}: {
  removeMode: boolean
  checked: boolean
  removable: boolean
  onToggle: () => void
  children: ReactNode
}) {
  if (!removeMode) return <>{children}</>
  return (
    <div className="flex items-center gap-2">
      <input
        type="checkbox"
        className="shrink-0 accent-gold"
        checked={checked}
        disabled={!removable}
        onChange={onToggle}
        title={removable ? undefined : 'Locked — cannot be removed'}
      />
      <div className={`flex-1 min-w-0 ${removable ? '' : 'opacity-40'}`}>{children}</div>
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
