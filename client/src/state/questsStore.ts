import { create } from 'zustand'
import { api } from '../lib/api'
import type { Quest } from '@shared/types/models'

interface QuestsState {
  quests: Quest[]

  fetchQuests: () => Promise<void>
  createQuest: (title: string) => Promise<Quest>
  updateQuest: (id: string, data: Partial<Pick<Quest, 'title' | 'status' | 'desc' | 'notes' | 'relatedLore'>>) => Promise<void>
  deleteQuest: (id: string) => Promise<void>
  addObjective: (questId: string, text: string) => Promise<void>
  updateObjective: (questId: string, objectiveId: string, data: { text?: string; done?: boolean }) => Promise<void>
  deleteObjective: (questId: string, objectiveId: string) => Promise<void>
}

export const useQuestsStore = create<QuestsState>((set, get) => ({
  quests: [],

  fetchQuests: async () => {
    const quests = await api.get<Quest[]>('/quests')
    set({ quests })
  },

  createQuest: async (title: string) => {
    const quest = await api.post<Quest>('/quests', { title })
    set({ quests: [...get().quests, quest] })
    return quest
  },

  updateQuest: async (id, data) => {
    const updated = await api.put<Quest>(`/quests/${id}`, data)
    set({
      quests: get().quests.map((q) => (q.id === id ? updated : q)),
    })
  },

  deleteQuest: async (id) => {
    await api.del(`/quests/${id}`)
    set({
      quests: get().quests.filter((q) => q.id !== id),
    })
  },

  addObjective: async (questId, text) => {
    const updated = await api.post<Quest>(`/quests/${questId}/objectives`, { text })
    set({
      quests: get().quests.map((q) => (q.id === questId ? updated : q)),
    })
  },

  updateObjective: async (questId, objectiveId, data) => {
    const updated = await api.put<Quest>(`/quests/${questId}/objectives/${objectiveId}`, data)
    set({
      quests: get().quests.map((q) => (q.id === questId ? updated : q)),
    })
  },

  deleteObjective: async (questId, objectiveId) => {
    await api.del(`/quests/${questId}/objectives/${objectiveId}`)
    // Re-fetch the quest to get the updated objectives list
    try {
      const updated = await api.get<Quest>(`/quests/${questId}`)
      set({
        quests: get().quests.map((q) => (q.id === questId ? updated : q)),
      })
    } catch {
      // Quest might have been deleted; just remove the objective locally
      set({
        quests: get().quests.map((q) =>
          q.id === questId
            ? { ...q, objectives: q.objectives.filter((o) => o.id !== objectiveId) }
            : q
        ),
      })
    }
  },
}))
