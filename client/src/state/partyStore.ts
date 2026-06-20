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
}))
