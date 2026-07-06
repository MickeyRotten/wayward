import { create } from 'zustand'
import { api } from '../lib/api'

interface JournalState {
  // "The Story So Far" — the auto-maintained StorySummary, read-only here.
  summary: string
  upToTurn: number
  // The "Previously on…" chat banner: shown once per adventure load, until
  // dismissed. Re-armed only via fetch(rearmBanner) on boot/adventure switch —
  // NOT on the routine post-turn refresh, or it would keep reappearing.
  bannerDismissed: boolean
  fetch: (rearmBanner?: boolean) => Promise<void>
  dismissBanner: () => void
}

export const useJournalStore = create<JournalState>((set) => ({
  summary: '',
  upToTurn: 0,
  bannerDismissed: false,

  fetch: async (rearmBanner = false) => {
    try {
      const j = await api.get<{ summary: string; upToTurn: number }>('/journal')
      set({
        summary: j.summary || '',
        upToTurn: j.upToTurn || 0,
        ...(rearmBanner ? { bannerDismissed: false } : {}),
      })
    } catch {
      // recap is a nicety — never break the app over it
    }
  },

  dismissBanner: () => set({ bannerDismissed: true }),
}))
