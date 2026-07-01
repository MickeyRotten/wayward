import { create } from 'zustand'
import type { ActionSuggestionsResponse } from '@shared/types/models'
import { api } from '../lib/api'
import { useNarratorStore } from './narratorStore'

interface ActionSuggestionsState {
  suggestions: string[]
  loading: boolean
  runForTurn: (turn: number) => Promise<void>
  clear: () => void
}

export const useActionSuggestionsStore = create<ActionSuggestionsState>((set) => ({
  suggestions: [],
  loading: false,

  runForTurn: async (turn) => {
    if (!useNarratorStore.getState().actionSuggestionsEnabled) {
      set({ suggestions: [] })
      return
    }
    set({ loading: true })
    try {
      const result = await api.post<ActionSuggestionsResponse>('/action-suggestions/run', { turn })
      set({ suggestions: result.suggestions || [] })
    } catch {
      // best effort — suggestions shouldn't break the turn
      set({ suggestions: [] })
    } finally {
      set({ loading: false })
    }
  },

  clear: () => set({ suggestions: [] }),
}))
