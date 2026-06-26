import { create } from 'zustand'
import type { WorldbuildProposal } from '@shared/types/models'
import { api } from '../lib/api'
import { useLoreStore } from './loreStore'
import { useQuestsStore } from './questsStore'
import { usePartyStore } from './partyStore'
import { useItemsStore } from './itemsStore'
import { useSettingsStore } from './settingsStore'

interface WorldbuildState {
  proposals: WorldbuildProposal[]
  pendingCount: number
  running: boolean
  fetchProposals: () => Promise<void>
  runForTurn: (turn: number) => Promise<void>
  accept: (id: string) => Promise<void>
  reject: (id: string) => Promise<void>
  acceptAll: () => Promise<void>
  rejectAll: () => Promise<void>
}

/** Refresh the panels a world-building change may have touched. */
function refreshWorld() {
  useLoreStore.getState().fetchEntries()
  useQuestsStore.getState().fetchQuests()
  usePartyStore.getState().fetchAll()
  useItemsStore.getState().fetchCatalog()
}

export const useWorldbuildStore = create<WorldbuildState>((set, get) => ({
  proposals: [],
  pendingCount: 0,
  running: false,

  fetchProposals: async () => {
    const proposals = await api.get<WorldbuildProposal[]>('/worldbuild/proposals?status=pending')
    set({ proposals, pendingCount: proposals.length })
  },

  runForTurn: async (turn) => {
    const mode = useSettingsStore.getState().worldbuildingMode
    if (mode === 'disabled') return
    set({ running: true })
    try {
      await api.post<WorldbuildProposal[]>('/worldbuild/run', { turn })
      await get().fetchProposals()
      // Auto-mode may have applied lore/quests already — reflect them.
      if (mode === 'auto') refreshWorld()
    } catch {
      // best effort — world-building shouldn't break the turn
    } finally {
      set({ running: false })
    }
  },

  accept: async (id) => {
    await api.post<WorldbuildProposal>(`/worldbuild/proposals/${id}/accept`, {})
    await get().fetchProposals()
    refreshWorld()
  },

  reject: async (id) => {
    await api.post<WorldbuildProposal>(`/worldbuild/proposals/${id}/reject`, {})
    await get().fetchProposals()
  },

  acceptAll: async () => {
    await api.post<WorldbuildProposal[]>('/worldbuild/proposals/accept-all', {})
    await get().fetchProposals()
    refreshWorld()
  },

  rejectAll: async () => {
    await api.post('/worldbuild/proposals/reject-all', {})
    await get().fetchProposals()
  },
}))
