import { create } from 'zustand'
import { api } from '../lib/api'
import type { Objective, TaskStatus } from '@shared/types/models'

interface ObjectivesState {
  objectives: Objective[]

  fetchObjectives: () => Promise<void>
  createObjective: (text: string) => Promise<Objective>
  updateObjective: (id: string, data: Partial<Pick<Objective, 'text' | 'status' | 'detail'>>) => Promise<void>
  setStatus: (id: string, status: TaskStatus) => Promise<void>
  deleteObjective: (id: string) => Promise<void>
}

export const useObjectivesStore = create<ObjectivesState>((set, get) => ({
  objectives: [],

  fetchObjectives: async () => {
    const objectives = await api.get<Objective[]>('/objectives')
    set({ objectives })
  },

  createObjective: async (text: string) => {
    const obj = await api.post<Objective>('/objectives', { text })
    set({ objectives: [...get().objectives, obj] })
    return obj
  },

  updateObjective: async (id, data) => {
    const updated = await api.put<Objective>(`/objectives/${id}`, data)
    set({ objectives: get().objectives.map((o) => (o.id === id ? updated : o)) })
  },

  setStatus: async (id, status) => {
    const updated = await api.put<Objective>(`/objectives/${id}`, { status })
    set({ objectives: get().objectives.map((o) => (o.id === id ? updated : o)) })
  },

  deleteObjective: async (id) => {
    await api.del(`/objectives/${id}`)
    set({ objectives: get().objectives.filter((o) => o.id !== id) })
  },
}))
