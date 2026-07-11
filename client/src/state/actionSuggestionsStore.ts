import { create } from 'zustand'
import type { ActionSuggestionsResponse } from '@shared/types/models'
import { api } from '../lib/api'
import { useNarratorStore } from './narratorStore'

interface ActionSuggestionsState {
  suggestions: string[]
  loading: boolean
  lastTurn: number | null
  // null → the server targets the latest turn (used by reroll after a refresh,
  // when the client no longer knows which turn it's on).
  runForTurn: (turn: number | null) => Promise<void>
  regenerate: () => Promise<void>  // reroll the options for the same turn
  clear: () => void
}

export const useActionSuggestionsStore = create<ActionSuggestionsState>((set, get) => ({
  suggestions: [],
  loading: false,
  lastTurn: null,

  runForTurn: async (turn) => {
    if (!useNarratorStore.getState().actionSuggestionsEnabled) {
      set({ suggestions: [], lastTurn: turn })
      return
    }
    set({ loading: true, lastTurn: turn })
    try {
      const result = await api.post<ActionSuggestionsResponse>('/action-suggestions/run', { turn })
      // A newer turn may have started while we waited — don't clobber it.
      if (get().lastTurn === turn) set({ suggestions: result.suggestions || [] })
    } catch {
      // best effort — suggestions shouldn't break the turn
      if (get().lastTurn === turn) set({ suggestions: [] })
    } finally {
      if (get().lastTurn === turn) set({ loading: false })
    }
  },

  regenerate: async () => {
    if (get().loading) return
    await get().runForTurn(get().lastTurn)
  },

  clear: () => set({ suggestions: [] }),
}))
