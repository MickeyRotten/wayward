import { create } from 'zustand'
import { api } from '../lib/api'
import type { Task, TaskStatus } from '@shared/types/models'

interface TasksState {
  tasks: Task[]

  fetchTasks: () => Promise<void>
  createTask: (text: string) => Promise<Task>
  updateTask: (id: string, data: Partial<Pick<Task, 'text' | 'status' | 'notes'>>) => Promise<void>
  setStatus: (id: string, status: TaskStatus) => Promise<void>
  deleteTask: (id: string) => Promise<void>
}

export const useTasksStore = create<TasksState>((set, get) => ({
  tasks: [],

  fetchTasks: async () => {
    const tasks = await api.get<Task[]>('/tasks')
    set({ tasks })
  },

  createTask: async (text: string) => {
    const task = await api.post<Task>('/tasks', { text })
    set({ tasks: [...get().tasks, task] })
    return task
  },

  updateTask: async (id, data) => {
    const updated = await api.put<Task>(`/tasks/${id}`, data)
    set({ tasks: get().tasks.map((t) => (t.id === id ? updated : t)) })
  },

  setStatus: async (id, status) => {
    const updated = await api.put<Task>(`/tasks/${id}`, { status })
    set({ tasks: get().tasks.map((t) => (t.id === id ? updated : t)) })
  },

  deleteTask: async (id) => {
    await api.del(`/tasks/${id}`)
    set({ tasks: get().tasks.filter((t) => t.id !== id) })
  },
}))
