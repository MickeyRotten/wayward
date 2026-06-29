import { create } from 'zustand'
import type { PartyMember, PlayerCharacter } from '@shared/types/models'
import { api } from '../lib/api'

interface PartyState {
  playerCharacter: PlayerCharacter | null
  partyMembers: PartyMember[]
  lastSavedAt: number | null
  fetchAll: () => Promise<void>
  savePlayerCharacter: (pc: PlayerCharacter) => Promise<void>
  addPartyMember: () => Promise<PartyMember>
  savePartyMember: (pm: PartyMember) => Promise<void>
  removePartyMember: (id: string) => Promise<void>
  setMembership: (id: string, inParty: boolean) => Promise<void>
<<<<<<< Updated upstream
=======
  equipItem: (characterId: string, itemId: string, slot: string, instanceId?: string) => Promise<void>
  unequipSlot: (characterId: string, slot: string) => Promise<void>
>>>>>>> Stashed changes
}

export const usePartyStore = create<PartyState>((set, get) => ({
  playerCharacter: null,
  partyMembers: [],
  lastSavedAt: null,

  fetchAll: async () => {
    const [pc, members] = await Promise.all([
      api.get<PlayerCharacter | null>('/player-character'),
      api.get<PartyMember[]>('/party-members'),
    ])
    set({ playerCharacter: pc, partyMembers: members })
  },

  savePlayerCharacter: async (pc) => {
    const saved = await api.put<PlayerCharacter>('/player-character', {
      basicInfo: pc.basicInfo,
      equipment: pc.equipment,
    })
    set({ playerCharacter: saved, lastSavedAt: Date.now() })
  },

  addPartyMember: async () => {
    const pm = await api.post<PartyMember>('/party-members', {})
    set({ partyMembers: [...get().partyMembers, pm] })
    return pm
  },

  savePartyMember: async (pm) => {
    const saved = await api.put<PartyMember>(`/party-members/${pm.id}`, {
      basicInfo: pm.basicInfo,
      equipment: pm.equipment,
      fieldSkill: pm.fieldSkill,
    })
    set({
      partyMembers: get().partyMembers.map((m) =>
        m.id === saved.id ? saved : m
      ),
      lastSavedAt: Date.now(),
    })
  },

  removePartyMember: async (id) => {
    await api.del(`/party-members/${id}`)
    set({ partyMembers: get().partyMembers.filter((m) => m.id !== id) })
  },

  setMembership: async (id, inParty) => {
    const saved = await api.put<PartyMember>(`/party-members/${id}/in-party`, { inParty })
    set({
      partyMembers: get().partyMembers.map((m) => (m.id === saved.id ? saved : m)),
    })
  },
<<<<<<< Updated upstream
=======

  // Equip/unequip go through the server (instance-aware: reuse a stowed copy or
  // mint one; the prior occupant returns to the pack). Refresh party + inventory.
  equipItem: async (characterId, itemId, slot, instanceId) => {
    await api.post('/characters/equip', { characterId, itemId, slot, instanceId })
    await get().fetchAll()
    await useItemsStore.getState().fetchInventory()
  },

  unequipSlot: async (characterId, slot) => {
    await api.post('/characters/unequip', { characterId, slot })
    await get().fetchAll()
    await useItemsStore.getState().fetchInventory()
  },
>>>>>>> Stashed changes
}))
