import { create } from 'zustand'
import { api } from '../lib/api'
import type { Wish, WishPriority } from '@shared/types/models'

interface WishlistState {
  wishes: Wish[]

  fetchWishes: () => Promise<void>
  createWish: (text: string, priority?: WishPriority) => Promise<Wish>
  updateWish: (id: string, data: Partial<Pick<Wish, 'text' | 'priority'>>) => Promise<void>
  deleteWish: (id: string) => Promise<void>
}

export const useWishlistStore = create<WishlistState>((set, get) => ({
  wishes: [],

  fetchWishes: async () => {
    const wishes = await api.get<Wish[]>('/wishes')
    set({ wishes })
  },

  createWish: async (text: string, priority: WishPriority = 0) => {
    const wish = await api.post<Wish>('/wishes', { text, priority })
    set({ wishes: [...get().wishes, wish] })
    return wish
  },

  updateWish: async (id, data) => {
    const updated = await api.put<Wish>(`/wishes/${id}`, data)
    set({ wishes: get().wishes.map((w) => (w.id === id ? updated : w)) })
  },

  deleteWish: async (id) => {
    await api.del(`/wishes/${id}`)
    set({ wishes: get().wishes.filter((w) => w.id !== id) })
  },
}))
