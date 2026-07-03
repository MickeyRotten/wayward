import { create } from 'zustand'
import type { Adventure } from '@shared/types/models'
import { api } from '../lib/api'
import { usePartyStore } from './partyStore'
import { useNarratorStore } from './narratorStore'
import { useChatStore } from './chatStore'
import { useSettingsStore } from './settingsStore'
import { useItemsStore } from './itemsStore'
import { useQuestsStore } from './questsStore'
import { useLoreStore } from './loreStore'
import { useScenarioStore } from './scenarioStore'
import { useWorldbuildStore } from './worldbuildStore'
import { useUiStore } from './uiStore'

interface AdventuresState {
  adventures: Adventure[]
  activeId: string | null
  busy: boolean
  fetch: () => Promise<void>
  create: (name?: string) => Promise<void>
  load: (id: string) => Promise<void>
  rename: (id: string, name: string) => Promise<void>
  remove: (id: string) => Promise<void>
}

/** Re-fetch every store after the active adventure/campaign changed.
 *  Uses allSettled so one failing fetch can't abort the whole switch (which
 *  left the UI blank/stale until a manual refresh). */
export async function reloadAll() {
  useUiStore.getState().select(null)
  const results = await Promise.allSettled([
    usePartyStore.getState().fetchAll(),
    useNarratorStore.getState().fetchConfig(),
    useChatStore.getState().fetchHistory(),
    useSettingsStore.getState().fetchSettings(),
    useItemsStore.getState().fetchCatalog(),
    useItemsStore.getState().fetchInventory(),
    useQuestsStore.getState().fetchQuests(),
    useLoreStore.getState().fetchEntries(),
    useLoreStore.getState().fetchConfig(),
    useScenarioStore.getState().fetchScenario(),
    useWorldbuildStore.getState().fetchProposals(),
  ])
  for (const r of results) {
    if (r.status === 'rejected') console.error('reloadAll: a store failed to refresh', r.reason)
  }
}

export const useAdventuresStore = create<AdventuresState>((set, get) => ({
  adventures: [],
  activeId: null,
  busy: false,

  fetch: async () => {
    const res = await api.get<{ activeId: string | null; adventures: Adventure[] }>('/adventures')
    set({ adventures: res.adventures, activeId: res.activeId })
  },

  create: async (name) => {
    set({ busy: true })
    try {
      await api.post('/adventures', { name: name ?? 'New Adventure' })
      await reloadAll()
      await get().fetch()
    } finally {
      set({ busy: false })
    }
  },

  load: async (id) => {
    if (id === get().activeId) return
    set({ busy: true })
    try {
      await api.post(`/adventures/${id}/load`, {})
      await reloadAll()
      await get().fetch()
    } finally {
      set({ busy: false })
    }
  },

  rename: async (id, name) => {
    await api.put(`/adventures/${id}`, { name })
    await get().fetch()
  },

  remove: async (id) => {
    set({ busy: true })
    try {
      await api.del(`/adventures/${id}`)
      await reloadAll() // harmless if we didn't switch; refreshes if we did
      await get().fetch()
    } finally {
      set({ busy: false })
    }
  },
}))
