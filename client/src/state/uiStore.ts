import { create } from 'zustand'

export type TabId = 'scene' | 'party' | 'items' | 'quests' | 'lore' | 'config'

export type SelectionKind =
  | { kind: 'player' }
  | { kind: 'member'; id: string }
  | { kind: 'item'; id: string }
  | { kind: 'quest'; id: string }
  | { kind: 'lore'; id: string }
  | null

interface UiState {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void

  selection: SelectionKind
  everSelected: boolean
  mode: 'view' | 'edit'
  modeMemory: Record<string, 'view' | 'edit'>
  editDirty: boolean

  select: (sel: SelectionKind) => void
  setMode: (mode: 'view' | 'edit') => void
  setEditDirty: (dirty: boolean) => void
}

function selectionKey(sel: SelectionKind): string | null {
  if (!sel) return null
  if (sel.kind === 'player') return 'player'
  return `${sel.kind}:${sel.id}`
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'party',
  setActiveTab: (tab) => set({ activeTab: tab }),

  selection: null,
  everSelected: false,
  mode: 'view',
  modeMemory: {},
  editDirty: false,

  select: (sel) => {
    const prev = get().selection
    const prevKey = selectionKey(prev)
    const currentMode = get().mode

    // Save current mode for the entity we're leaving
    if (prevKey) {
      set((s) => ({ modeMemory: { ...s.modeMemory, [prevKey]: currentMode } }))
    }

    // Restore remembered mode for the entity we're navigating to
    const newKey = selectionKey(sel)
    const remembered = newKey ? get().modeMemory[newKey] : undefined

    set({
      selection: sel,
      everSelected: true,
      mode: remembered ?? 'view',
      editDirty: false,
    })
  },

  setMode: (mode) => set({ mode }),
  setEditDirty: (dirty) => set({ editDirty: dirty }),
}))
