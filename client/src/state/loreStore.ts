import { create } from 'zustand'
import { api } from '../lib/api'
import type { LorebookEntry, LorebookConfig, LoreCategory } from '@shared/types/models'

interface LoreState {
  entries: LorebookEntry[]
  config: LorebookConfig | null
  activeCategory: LoreCategory
  searchQuery: string

  fetchEntries: () => Promise<void>
  fetchConfig: () => Promise<void>
  createEntry: (cat: LoreCategory) => Promise<LorebookEntry>
  updateEntry: (id: string, data: Partial<Omit<LorebookEntry, 'id'>>) => Promise<void>
  deleteEntry: (id: string) => Promise<void>
  saveConfig: (data: Partial<LorebookConfig>) => Promise<void>
  setCategory: (cat: LoreCategory) => void
  setSearchQuery: (query: string) => void
}

export const useLoreStore = create<LoreState>((set, get) => ({
  entries: [],
  config: null,
  activeCategory: 'world',
  searchQuery: '',

  fetchEntries: async () => {
    const entries = await api.get<LorebookEntry[]>('/lore')
    set({ entries })
  },

  fetchConfig: async () => {
    const config = await api.get<LorebookConfig>('/lore/config')
    set({ config })
  },

  createEntry: async (cat: LoreCategory) => {
    const entry = await api.post<LorebookEntry>('/lore', {
      title: '',
      content: '',
      keywords: [],
      enabled: true,
      permanent: false,
      cat,
    })
    set({ entries: [...get().entries, entry] })
    return entry
  },

  updateEntry: async (id, data) => {
    const updated = await api.put<LorebookEntry>(`/lore/${id}`, data)
    set({
      entries: get().entries.map((e) => (e.id === id ? updated : e)),
    })
  },

  deleteEntry: async (id) => {
    await api.del(`/lore/${id}`)
    set({
      entries: get().entries.filter((e) => e.id !== id),
    })
  },

  saveConfig: async (data) => {
    const updated = await api.put<LorebookConfig>('/lore/config', data)
    set({ config: updated })
  },

  setCategory: (cat) => set({ activeCategory: cat, searchQuery: '' }),
  setSearchQuery: (query) => set({ searchQuery: query }),
}))
