import { create } from 'zustand'

type Selection =
  | { type: 'player' }
  | { type: 'member'; id: string }
  | null

interface UiState {
  selection: Selection
  select: (sel: Selection) => void
}

export const useUiStore = create<UiState>((set) => ({
  selection: null,
  select: (selection) => set({ selection }),
}))
