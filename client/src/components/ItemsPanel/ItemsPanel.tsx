import { useState, useRef, useCallback } from 'react'
import { useItemsStore } from '../../state/itemsStore'
import { useUiStore } from '../../state/uiStore'
import { ItemCard, RARITY_COLORS } from '../ItemCard'
import type { ItemCatalogEntry, Rarity } from '@shared/types/models'

export function ItemsPanel() {
  const inventory = useItemsStore((s) => s.inventory)
  const maxCarrySlots = useItemsStore((s) => s.maxCarrySlots)
  const selection = useUiStore((s) => s.selection)
  const select = useUiStore((s) => s.select)

  const isSelected = (itemId: string) =>
    selection?.kind === 'item' && selection.id === itemId

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
        {inventory.length === 0 && (
          <p className="text-[12px] text-textdim font-body px-2 py-4 text-center">
            No items in inventory
          </p>
        )}
        {inventory.map((stack) => {
          const item = stack.item
          if (!item) return null
          return (
            <ItemCard
              key={stack.itemId}
              item={item}
              count={stack.count}
              selected={isSelected(stack.itemId)}
              onClick={() => select({ kind: 'item', id: stack.itemId })}
            />
          )
        })}

        {/* Divider */}
        <div className="flex items-center gap-2 px-3 pt-3 pb-1">
          <span className="font-ui text-[9px] text-textdim tracking-wider">ADD ITEM</span>
          <div className="flex-1 border-t border-line" />
        </div>

        {/* Add item search */}
        <AddItemSection />
      </div>
    </div>
  )
}

function AddItemSection() {
  const [query, setQuery] = useState('')
  const [selectedItem, setSelectedItem] = useState<ItemCatalogEntry | null>(null)
  const [quantity, setQuantity] = useState(1)
  const [error, setError] = useState('')
  const searchItems = useItemsStore((s) => s.searchItems)
  const clearSearch = useItemsStore((s) => s.clearSearch)
  const searchResults = useItemsStore((s) => s.searchResults)
  const addToInventory = useItemsStore((s) => s.addToInventory)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const handleSearch = useCallback(
    (value: string) => {
      setQuery(value)
      setSelectedItem(null)
      setError('')
      clearTimeout(debounceRef.current)
      if (value.length < 3) {
        clearSearch()
        return
      }
      debounceRef.current = setTimeout(() => {
        searchItems(value)
      }, 250)
    },
    [searchItems, clearSearch],
  )

  const handleSelect = (item: ItemCatalogEntry) => {
    setSelectedItem(item)
    setQuery(item.name)
    setQuantity(1)
    clearSearch()
  }

  const handleAdd = async () => {
    if (!selectedItem) return
    setError('')
    try {
      await addToInventory(selectedItem.id, quantity)
      setSelectedItem(null)
      setQuery('')
      setQuantity(1)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to add item'
      setError(msg)
    }
  }

  return (
    <div className="px-2 space-y-2">
      {/* Search input */}
      <input
        className="w-full border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2 transition-colors"
        placeholder="Type to search..."
        value={query}
        onChange={(e) => handleSearch(e.target.value)}
      />

      {/* Hint for short queries */}
      {query.length > 0 && query.length < 3 && !selectedItem && (
        <p className="text-[11px] text-textdim font-body px-1">Keep typing...</p>
      )}

      {/* Search results */}
      {searchResults.length > 0 && !selectedItem && (
        <div className="border border-line bg-bg1 max-h-[200px] overflow-y-auto">
          {searchResults.map((item) => (
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
          ))}
        </div>
      )}

      {/* No results */}
      {query.length >= 3 && searchResults.length === 0 && !selectedItem && (
        <p className="text-[11px] text-textdim font-body px-1">No items found</p>
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
              onClick={() => {
                setSelectedItem(null)
                setQuery('')
                clearSearch()
              }}
            >
              CANCEL
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
