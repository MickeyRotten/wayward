import { useState, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { useChatStore } from '../../state/chatStore'
import { usePartyStore } from '../../state/partyStore'
import { ItemCard, RARITY_COLORS } from '../ItemCard'
import { ConfirmDialog } from '../ConfirmDialog'
import { EQUIP_SLOT_KEYS } from '../../lib/equipSlots'
import type { ItemCatalogEntry, Rarity, Equipment, PlayerCharacter, PartyMember } from '@shared/types/models'

/** Build itemId → list of character display-names currently wearing it. */
function buildEquippedBy(pc: PlayerCharacter | null, members: PartyMember[]): Map<string, string[]> {
  const map = new Map<string, string[]>()
  const add = (equipment: Equipment, name: string) => {
    for (const key of EQUIP_SLOT_KEYS) {
      const id = equipment[key]
      if (!id) continue
      const list = map.get(id) ?? []
      if (!list.includes(name)) list.push(name)
      map.set(id, list)
    }
  }
  if (pc) add(pc.equipment, pc.basicInfo?.name || 'You')
  for (const m of members) add(m.equipment, m.basicInfo?.name || 'Unnamed')
  return map
}

export function ItemsPanel() {
  const inventory = useItemsStore((s) => s.inventory)
  const maxCarrySlots = useItemsStore((s) => s.maxCarrySlots)
  const removeFromInventory = useItemsStore((s) => s.removeFromInventory)
  const editMode = useChatStore((s) => s.planningMode)
  const playerCharacter = usePartyStore((s) => s.playerCharacter)
  const partyMembers = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const [removeMode, setRemoveMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmRemove, setConfirmRemove] = useState(false)

  const equippedBy = useMemo(
    () => buildEquippedBy(playerCharacter, partyMembers),
    [playerCharacter, partyMembers],
  )

  // Equipped items are always shown in the inventory, even when worn rather than
  // carried as a stack — surface those as extra (non-removable) rows.
  const equippedOnly = useMemo(() => {
    const carried = new Set(inventory.map((s) => s.itemId))
    return [...equippedBy.keys()]
      .filter((id) => !carried.has(id))
      .map((id) => catalog.find((i) => i.id === id))
      .filter((i): i is ItemCatalogEntry => !!i)
  }, [equippedBy, inventory, catalog])

  const isSelected = (itemId: string) =>
    selection?.kind === 'item' && selection.id === itemId

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
    for (const id of [...selectedIds]) {
      const stack = inventory.find((s) => s.itemId === id)
      if (!stack) continue
      try {
        await removeFromInventory(id, stack.count) // clear the whole stack
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
            {inventory.length} / {maxCarrySlots}
          </span>
        </div>
      </div>

      {/* Inventory list */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1">
        {inventory.length === 0 && equippedOnly.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-2 py-4 text-center">
            No items in inventory
          </p>
        )}
        {inventory.map((stack) => {
          const item = stack.item
          if (!item) return null
          return (
            <SelectableRow
              key={stack.itemId}
              removeMode={removeMode}
              checked={selectedIds.has(stack.itemId)}
              onToggle={() => toggleSelected(stack.itemId)}
            >
              <ItemCard
                item={item}
                count={stack.count}
                selected={removeMode ? selectedIds.has(stack.itemId) : isSelected(stack.itemId)}
                onClick={() => (removeMode ? toggleSelected(stack.itemId) : select({ kind: 'item', id: stack.itemId }))}
                equippedBy={equippedBy.get(stack.itemId)}
              />
            </SelectableRow>
          )
        })}

        {/* Equipped but not carried — shown so all gear is visible (not removable). */}
        {!removeMode && equippedOnly.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            selected={isSelected(item.id)}
            onClick={() => select({ kind: 'item', id: item.id })}
            equippedBy={equippedBy.get(item.id)}
          />
        ))}

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

/** Wraps a card with a checkbox when in remove-mode. */
function SelectableRow({
  removeMode, checked, onToggle, children,
}: {
  removeMode: boolean
  checked: boolean
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
        onChange={onToggle}
      />
      <div className="flex-1 min-w-0">{children}</div>
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
