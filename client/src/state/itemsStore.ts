import { create } from 'zustand'
import { api } from '../lib/api'
import { useLoreStore } from './loreStore'
import type { ItemCatalogEntry, InventoryStack } from '@shared/types/models'

// Items are stored as lorebook entries (cat === 'items'). Keep the lore list in
// sync after item mutations so Lore → Items reflects changes immediately.
const syncLore = () => { void useLoreStore.getState().fetchEntries() }

export interface InventoryStackWithItem extends InventoryStack {
  item?: ItemCatalogEntry
}

interface ItemsState {
  catalog: ItemCatalogEntry[]
  inventory: InventoryStackWithItem[]
  maxCarrySlots: number
  searchResults: ItemCatalogEntry[]

  fetchCatalog: () => Promise<void>
  fetchInventory: () => Promise<void>
  searchItems: (q: string) => Promise<void>
  clearSearch: () => void
  addToInventory: (itemId: string, count?: number) => Promise<void>
  removeFromInventory: (itemId: string, count?: number) => Promise<void>
  createItem: (data: Omit<ItemCatalogEntry, 'id' | 'kind'>) => Promise<ItemCatalogEntry>
  updateItem: (id: string, data: Partial<ItemCatalogEntry>) => Promise<void>
  deleteItem: (id: string) => Promise<void>
}

export const useItemsStore = create<ItemsState>((set, get) => ({
  catalog: [],
  inventory: [],
  maxCarrySlots: 12,
  searchResults: [],

  fetchCatalog: async () => {
    const items = await api.get<ItemCatalogEntry[]>('/items')
    set({ catalog: items })
  },

  fetchInventory: async () => {
    const [stacks, capacity] = await Promise.all([
      api.get<InventoryStackWithItem[]>('/inventory'),
      api.get<{ used: number; max: number }>('/inventory/capacity'),
    ])
    set({ inventory: stacks, maxCarrySlots: capacity.max })
  },

  searchItems: async (q: string) => {
    if (q.length < 3) {
      set({ searchResults: [] })
      return
    }
    const results = await api.get<ItemCatalogEntry[]>(`/items/search?q=${encodeURIComponent(q)}`)
    set({ searchResults: results })
  },

  clearSearch: () => set({ searchResults: [] }),

  addToInventory: async (itemId, count = 1) => {
    await api.post('/inventory/add', { itemId, count })
    await get().fetchInventory()
  },

  removeFromInventory: async (itemId, count = 1) => {
    await api.post('/inventory/remove', { itemId, count })
    await get().fetchInventory()
  },

  createItem: async (data) => {
    const item = await api.post<ItemCatalogEntry>('/items', data)
    set({ catalog: [...get().catalog, item] })
    syncLore()
    return item
  },

  updateItem: async (id, data) => {
    const updated = await api.put<ItemCatalogEntry>(`/items/${id}`, data)
    set({
      catalog: get().catalog.map((i) => (i.id === id ? updated : i)),
      // Also update in inventory if present
      inventory: get().inventory.map((s) =>
        s.itemId === id ? { ...s, item: updated } : s
      ),
    })
    syncLore()
  },

  deleteItem: async (id) => {
    await api.del(`/items/${id}`)
    set({
      catalog: get().catalog.filter((i) => i.id !== id),
      inventory: get().inventory.filter((s) => s.itemId !== id),
    })
    syncLore()
  },
}))
