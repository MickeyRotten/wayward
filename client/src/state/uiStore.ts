import { create } from 'zustand'

export type TabId = 'home' | 'items' | 'tasks' | 'lore' | 'suggestions' | 'saves' | 'config'

export type SelectionKind =
  | { kind: 'player' }
  | { kind: 'member'; id: string }
  | { kind: 'item'; id: string; instanceId?: string }  // instanceId: a specific owned copy
  | { kind: 'task'; id: string }
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
  back: SelectionKind  // breadcrumb target when drilling into a sub-inspector

  select: (sel: SelectionKind) => void
  selectInto: (sel: SelectionKind) => void  // drill-down: remembers current as `back`
  goBack: () => void
  setMode: (mode: 'view' | 'edit') => void
  setEditDirty: (dirty: boolean) => void
}

function selectionKey(sel: SelectionKind): string | null {
  if (!sel) return null
  if (sel.kind === 'player') return 'player'
  if (sel.kind === 'item') return `item:${sel.id}:${sel.instanceId ?? ''}`
  return `${sel.kind}:${sel.id}`
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'home',
  setActiveTab: (tab) => set({ activeTab: tab }),

  selection: null,
  everSelected: false,
  mode: 'view',
  modeMemory: {},
  editDirty: false,
  back: null,

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
      back: null,  // normal navigation clears the breadcrumb
    })
  },

  // Drill into a sub-inspector, remembering the current selection as the
  // breadcrumb target so the inspector can show a "Back" link.
  selectInto: (sel) => {
    const prev = get().selection
    get().select(sel)
    set({ back: prev })
  },

  goBack: () => {
    const b = get().back
    if (b) get().select(b)
  },

  setMode: (mode) => set({ mode }),
  setEditDirty: (dirty) => set({ editDirty: dirty }),
}))
