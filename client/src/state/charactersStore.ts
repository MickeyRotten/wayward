import { create } from 'zustand'
import type { CharacterCard } from '@shared/types/models'
import { api } from '../lib/api'
import { usePartyStore } from './partyStore'

interface CharactersState {
  cards: CharacterCard[]
  fetchCards: () => Promise<void>
  importCard: (id: string) => Promise<void>
  duplicateCard: (id: string) => Promise<void>
  deleteCard: (id: string) => Promise<void>
  uploadCard: (file: File) => Promise<void>
  exportCard: (id: string) => void
}

export const useCharactersStore = create<CharactersState>((set, get) => ({
  cards: [],

  fetchCards: async () => {
    const cards = await api.get<CharacterCard[]>('/characters')
    set({ cards })
  },

  importCard: async (id) => {
    await api.post(`/characters/${id}/import`, {})
    // A new party member was bound into the active adventure.
    await usePartyStore.getState().fetchAll()
  },

  duplicateCard: async (id) => {
    await api.post(`/characters/${id}/duplicate`, {})
    await get().fetchCards()
  },

  deleteCard: async (id) => {
    await api.del(`/characters/${id}`)
    set({ cards: get().cards.filter((c) => c.id !== id) })
    // Deleting may have unbound a live member — refresh the party too.
    await usePartyStore.getState().fetchAll()
  },

  uploadCard: async (file) => {
    const form = new FormData()
    form.append('file', file, file.name || 'character.zip')
    await fetch('/api/characters/import-file', { method: 'POST', body: form })
    await get().fetchCards()
  },

  exportCard: (id) => {
    // Browser download of the character's shareable zip.
    const a = document.createElement('a')
    a.href = `/api/characters/${id}/export`
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  },
}))
