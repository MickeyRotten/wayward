import { create } from 'zustand'
import { api } from '../lib/api'
import type { StoryStyleFields, StyleFieldDef } from '@shared/types/models'

const EMPTY_FIELDS: StoryStyleFields = {
  genre: '',
  tone: '',
  writingStyle: '',
  verbosity: '',
  contentLimit: '',
  perspective: '',
  structure: '',
  customInstructions: '',
}

interface StoryStyleState {
  /** Picker definitions (fields + options), served by /campaign-style/options.
   *  Campaign-agnostic; fetched once. */
  defs: StyleFieldDef[]
  /** The active campaign's selections. */
  fields: StoryStyleFields
  fetchOptions: () => Promise<void>
  fetchFields: () => Promise<void>
  save: (update: Partial<StoryStyleFields>) => Promise<void>
  /** Optimistic local update (no network) — paired with a debounced save() so
   *  edits show instantly (same pattern as narratorStore). */
  patchLocal: (partial: Partial<StoryStyleFields>) => void
}

export const useStoryStyleStore = create<StoryStyleState>((set) => ({
  defs: [],
  fields: { ...EMPTY_FIELDS },

  fetchOptions: async () => {
    const r = await api.get<{ fields: StyleFieldDef[] }>('/campaign-style/options')
    set({ defs: r.fields })
  },

  fetchFields: async () => {
    const f = await api.get<StoryStyleFields>('/campaign-style')
    set({ fields: { ...EMPTY_FIELDS, ...f } })
  },

  save: async (update) => {
    const f = await api.put<StoryStyleFields>('/campaign-style', update)
    set({ fields: { ...EMPTY_FIELDS, ...f } })
  },

  patchLocal: (partial) => set((s) => ({ fields: { ...s.fields, ...partial } })),
}))
