import { useState, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { ItemCard, RARITY_COLORS } from '../ItemCard'
import { ConfirmDialog } from '../ConfirmDialog'
import { type SortKey, SORT_OPTIONS, RARITY_ORDER, sortList } from '../../lib/sortEntries'
import { type ItemTypeTab, matchesTypeTab } from '../../lib/itemTypes'
import { ItemTypeTabs } from '../ItemTypeTabs'
import type { ItemCatalogEntry, Rarity } from '@shared/types/models'

export function ItemsPanel() {
  const inventory = useItemsStore((s) => s.inventory)
  const removeInstance = useItemsStore((s) => s.removeInstance)
  const editMode = useChatStore((s) => s.planningMode)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [removeMode, setRemoveMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('newest')
  const [sortAsc, setSortAsc] = useState(false)
  const [typeTab, setTypeTab] = useState<ItemTypeTab>('All')

  const sortedInventory = useMemo(
    () => sortList(
      inventory.filter((s) => matchesTypeTab(s.item?.type, typeTab)),
      sortKey, sortAsc,
      {
        name: (s) => s.item?.name ?? '',
        type: (s) => s.item?.type ?? '',
        rarity: (s) => RARITY_ORDER[s.item?.rarity as Rarity] ?? 0,
      },
    ),
    [inventory, typeTab, sortKey, sortAsc],
  )

  // The inventory now lists every owned instance (stowed + equipped). The
  // header count shows how many copies are stowed in the pack (worn gear aside).
  const stowedCount = inventory.filter((s) => !s.equippedBy).length

  // Select a *specific copy*: a given instance highlights (and inspects) only
  // that row, so two copies of the same item are independently selectable.
  const isSelected = (instanceId: string) =>
    selection?.kind === 'item' && selection.instanceId === instanceId

  // Cancel remove-mode when leaving Edit Mode.
  useEffect(() => {
    setRemoveMode(false)
    setSelectedIds(new Set())
  }, [editMode])

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
    for (const instanceId of [...selectedIds]) {
      try {
        await removeInstance(instanceId)
      } catch { /* skip */ }
    }
    cancelRemove()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-baseline justify-between">
          <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">INVENTORY</h2>
          <span className="font-ui text-[11px] text-textsec tracking-wider">
            {stowedCount} {stowedCount === 1 ? 'item' : 'items'}
          </span>
        </div>
      </div>

      {/* Type filter tabs */}
      <div className="px-4 pb-2">
        <ItemTypeTabs value={typeTab} onChange={setTypeTab} />
      </div>

      {/* Sorting (mirrors the Lorebook) */}
      <div className="px-4 pb-3 flex items-center gap-2">
        <span className="font-ui text-[9px] tracking-wider text-textdim uppercase shrink-0">Sorting:</span>
        <select
          aria-label="Sort inventory"
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

      {/* Inventory list — every owned instance; worn gear is flagged "Equipped". */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1">
        {sortedInventory.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-2 py-4 text-center">
            {inventory.length === 0 ? 'No items in inventory' : 'No matching items'}
          </p>
        )}
        {sortedInventory.map((stack) => {
          const item = stack.item
          if (!item) return null
          const removable = !stack.equippedBy // can't remove worn gear from the pack
          return (
            <SelectableRow
              key={stack.instanceId}
              removeMode={removeMode}
              removable={removable}
              checked={selectedIds.has(stack.instanceId)}
              onToggle={() => toggleSelected(stack.instanceId)}
            >
              <ItemCard
                item={item}
                count={stack.count}
                selected={removeMode ? selectedIds.has(stack.instanceId) : isSelected(stack.instanceId)}
                onClick={() => (
                  removeMode
                    ? (removable && toggleSelected(stack.instanceId))
                    : select({ kind: 'item', id: stack.itemId, instanceId: stack.instanceId })
                )}
                equippedBy={stack.equippedByName ? [stack.equippedByName] : undefined}
              />
            </SelectableRow>
          )
        })}

        {/* Add item — hidden while removing */}
        {!removeMode && (
          <div className="pt-3">
            <AddItemSection />
          </div>
        )}
      </div>

      {/* Footer — removing inventory items is the domain of Edit Mode */}
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
                REMOVE SELECTED ITEMS{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
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
            <button
              type="button"
              disabled={inventory.length === 0}
              className="w-full font-ui text-[10px] tracking-wider text-textsec border border-line hover:border-line2 hover:text-text px-3 py-2 transition-colors text-center disabled:opacity-30 disabled:cursor-not-allowed"
              onClick={() => setRemoveMode(true)}
            >
              REMOVE ITEMS
            </button>
          )}
        </div>
      )}

      {confirmRemove && (
        <ConfirmDialog
          confirmLabel="REMOVE"
          message={`Remove ${selectedIds.size} selected item(s) from inventory? This cannot be undone.`}
          onConfirm={handleRemoveSelected}
          onCancel={() => setConfirmRemove(false)}
        />
      )}
    </div>
  )
}

/** Wraps a card with a checkbox when in remove-mode. Worn gear isn't removable. */
function SelectableRow({
  removeMode, checked, removable = true, onToggle, children,
}: {
  removeMode: boolean
  checked: boolean
  removable?: boolean
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
        title={removable ? undefined : 'Equipped — unequip it first'}
      />
      <div className={`flex-1 min-w-0 ${removable ? '' : 'opacity-40'}`}>{children}</div>
    </div>
  )
}

function AddItemSection() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedItem, setSelectedItem] = useState<ItemCatalogEntry | null>(null)
  const [quantity, setQuantity] = useState(1)
  const [error, setError] = useState('')
  const catalog = useItemsStore((s) => s.catalog)
  const addToInventory = useItemsStore((s) => s.addToInventory)

  // All Lorebook items, filtered live by the typed query (no minimum length).
  const q = query.toLowerCase().trim()
  const results = catalog
    .filter((i) => !q || i.name.toLowerCase().includes(q) || i.type.toLowerCase().includes(q))
    .sort((a, b) => a.name.localeCompare(b.name))

  const reset = () => {
    setOpen(false)
    setQuery('')
    setSelectedItem(null)
    setQuantity(1)
    setError('')
  }

  const handleSelect = (item: ItemCatalogEntry) => {
    setSelectedItem(item)
    setQuantity(1)
  }

  const handleAdd = async () => {
    if (!selectedItem) return
    setError('')
    try {
      await addToInventory(selectedItem.id, quantity)
      reset()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to add item'
      setError(msg)
    }
  }

  // Collapsed: just the Add Item button.
  if (!open) {
    return (
      <div className="px-2">
        <button
          type="button"
          className="w-full font-ui text-[10px] tracking-wider text-textsec border border-dashed border-line px-3 py-2.5 hover:border-line2 hover:text-text transition-colors"
          onClick={() => setOpen(true)}
        >
          + ADD ITEM
        </button>
      </div>
    )
  }

  return (
    <div className="px-2 space-y-2 border border-line bg-bg1 rounded-md p-2">
      {/* Filter input over the full Lorebook item list */}
      {!selectedItem && (
        <input
          autoFocus
          className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
          placeholder="Filter items..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}

      {/* Item list */}
      {!selectedItem && (
        <div className="border border-line bg-bg0 max-h-[220px] overflow-y-auto">
          {results.length === 0 ? (
            <p className="text-[11px] text-textdim font-body px-3 py-2">No items found</p>
          ) : (
            results.map((item) => (
              <button
                key={item.id}
                type="button"
                className="w-full text-left px-3 py-2 hover:bg-bg2 transition-colors border-b border-line last:border-b-0"
                onClick={() => handleSelect(item)}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[item.rarity as Rarity] || RARITY_COLORS.c}`}
                  />
                  <span className="font-body text-sm text-text truncate">{item.name}</span>
                  <span className="font-ui text-[8px] text-textdim tracking-wider uppercase ml-auto shrink-0">
                    {item.type}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      )}

      {/* Close the picker without selecting */}
      {!selectedItem && (
        <button
          type="button"
          className="w-full font-ui text-[10px] text-textdim border border-line hover:border-line2 hover:text-text px-3 py-1.5 transition-colors tracking-wider"
          onClick={reset}
        >
          CANCEL
        </button>
      )}

      {/* Selected item — quantity + confirm */}
      {selectedItem && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-1">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${RARITY_COLORS[selectedItem.rarity as Rarity] || RARITY_COLORS.c}`}
            />
            <span className="font-body text-sm text-text truncate flex-1">{selectedItem.name}</span>
            <span className="font-ui text-[8px] text-textdim tracking-wider uppercase">
              {selectedItem.type}
            </span>
          </div>

          {/* Quantity picker — only if stackable */}
          {(selectedItem.maxStack ?? 1) > 1 && (
            <div className="flex items-center gap-2 px-1">
              <span className="text-[11px] text-textdim font-body">Qty</span>
              <input
                type="number"
                min={1}
                max={selectedItem.maxStack ?? 1}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                className="w-16 border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 transition-colors text-center"
              />
            </div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              className="flex-1 font-ui text-[10px] text-bg0 bg-gold hover:bg-gold2 px-3 py-1.5 transition-colors tracking-wider"
              onClick={handleAdd}
            >
              ADD TO INVENTORY
            </button>
            <button
              type="button"
              className="font-ui text-[10px] text-textdim border border-line hover:border-line2 hover:text-text px-3 py-1.5 transition-colors tracking-wider"
              onClick={() => setSelectedItem(null)}
            >
              BACK
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-[11px] text-danger font-body px-1">{error}</p>
      )}
    </div>
  )
}
