import { create } from 'zustand'
import type { Campaign } from '@shared/types/models'
import { api } from '../lib/api'
import { reloadAll, useAdventuresStore } from './adventuresStore'
import { useChatStore } from './chatStore'

interface CampaignsState {
  campaigns: Campaign[]
  activeId: string | null
  busy: boolean
  fetch: () => Promise<void>
  create: (name?: string, template?: string) => Promise<void>
  load: (id: string) => Promise<void>
  rename: (id: string, name: string) => Promise<void>
  remove: (id: string) => Promise<void>
}

async function afterSwitch() {
  await reloadAll()
  await useAdventuresStore.getState().fetch()
  await useCampaignsStore.getState().fetch()
}

export const useCampaignsStore = create<CampaignsState>((set, get) => ({
  campaigns: [],
  activeId: null,
  busy: false,

  fetch: async () => {
    const res = await api.get<{ activeId: string | null; campaigns: Campaign[] }>('/campaigns')
    set({ campaigns: res.campaigns, activeId: res.activeId })
  },

  create: async (name, template) => {
    set({ busy: true })
    try {
      await api.post('/campaigns', { name: name ?? 'New Campaign', template: template ?? 'empty' })
      await afterSwitch()
      // A new campaign opens in Edit Mode with a structured starter message.
      useChatStore.getState().setPlanningMode(true)
    } finally {
      set({ busy: false })
    }
  },

  load: async (id) => {
    if (id === get().activeId) return
    set({ busy: true })
    try {
      await api.post(`/campaigns/${id}/load`, {})
      await afterSwitch()
    } finally {
      set({ busy: false })
    }
  },

  rename: async (id, name) => {
    await api.put(`/campaigns/${id}`, { name })
    await get().fetch()
  },

  remove: async (id) => {
    set({ busy: true })
    try {
      await api.del(`/campaigns/${id}`)
      await afterSwitch()
    } finally {
      set({ busy: false })
    }
  },
}))
