import { create } from 'zustand'
import type { CharacterBlock, Equipment, PartyMember, PlayerCharacter } from '@shared/types/models'
import { api } from '../lib/api'
import { useItemsStore } from './itemsStore'
import { useChatStore } from './chatStore'

interface PartyState {
  playerCharacter: PlayerCharacter | null
  partyMembers: PartyMember[]
  lastSavedAt: number | null
  fetchAll: () => Promise<void>
  savePlayerCharacterBlocks: (blocks: CharacterBlock[], name?: string) => Promise<void>
  savePlayerCharacterEquipment: (equipment: Equipment) => Promise<void>
  addPartyMember: () => Promise<PartyMember>
  savePartyMemberBlocks: (id: string, blocks: CharacterBlock[], name?: string) => Promise<void>
  savePartyMemberEquipment: (id: string, equipment: Equipment) => Promise<void>
  removePartyMember: (id: string) => Promise<void>
  setMembership: (id: string, inParty: boolean) => Promise<void>
  equipItem: (characterId: string, itemId: string, slot: string, instanceId?: string) => Promise<void>
  unequipSlot: (characterId: string, slot: string) => Promise<void>
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

  // Identity edits go through the block tree directly (see
  // CharacterBlockTree.tsx) — the legacy basicInfo/fieldSkill wire shape
  // can't round-trip Strengths/Other/etc without clobbering them.
  savePlayerCharacterBlocks: async (blocks, name) => {
    const saved = await api.put<PlayerCharacter>('/player-character/blocks', { blocks, name })
    set({ playerCharacter: saved, lastSavedAt: Date.now() })
  },

  savePlayerCharacterEquipment: async (equipment) => {
    const saved = await api.put<PlayerCharacter>('/player-character/equipment', equipment)
    set({ playerCharacter: saved, lastSavedAt: Date.now() })
    // Equipment changed → refresh inventory so equipped/stowed flags (derived
    // from the equipment dicts) stay in sync.
    void useItemsStore.getState().fetchInventory()
  },

  addPartyMember: async () => {
    const pm = await api.post<PartyMember>('/party-members', {})
    set({ partyMembers: [...get().partyMembers, pm] })
    return pm
  },

  savePartyMemberBlocks: async (id, blocks, name) => {
    const saved = await api.put<PartyMember>(`/party-members/${id}/blocks`, { blocks, name })
    set({
      partyMembers: get().partyMembers.map((m) => (m.id === saved.id ? saved : m)),
      lastSavedAt: Date.now(),
    })
  },

  savePartyMemberEquipment: async (id, equipment) => {
    const saved = await api.put<PartyMember>(`/party-members/${id}/equipment`, equipment)
    set({
      partyMembers: get().partyMembers.map((m) => (m.id === saved.id ? saved : m)),
      lastSavedAt: Date.now(),
    })
    void useItemsStore.getState().fetchInventory()
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

  // Equip/unequip go through the server (instance-aware: reuse a stowed copy or
  // mint one; the prior occupant returns to the pack). Refresh party + inventory.
  equipItem: async (characterId, itemId, slot, instanceId) => {
    await api.post('/characters/equip', { characterId, itemId, slot, instanceId })
    await get().fetchAll()
    await useItemsStore.getState().fetchInventory()
    void useChatStore.getState().fetchEvents()  // an equip toast was posted
  },

  unequipSlot: async (characterId, slot) => {
    await api.post('/characters/unequip', { characterId, slot })
    await get().fetchAll()
    await useItemsStore.getState().fetchInventory()
    void useChatStore.getState().fetchEvents()  // an unequip toast was posted
  },
}))
