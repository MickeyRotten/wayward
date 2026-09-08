import { create } from 'zustand'

export type TabId = 'home' | 'items' | 'tasks' | 'lore' | 'journal' | 'suggestions' | 'saves' | 'config'

export type SelectionKind =
  | { kind: 'player' }
  | { kind: 'member'; id: string }
  | { kind: 'item'; id: string; instanceId?: string }  // instanceId: a specific owned copy
  | { kind: 'task'; id: string }
  | { kind: 'lore'; id: string }
  | { kind: 'scenario'; id: string }  // a Scenario field key (or 'firstMessage')
  | { kind: 'block'; ownerType: 'player' | 'member'; ownerId: string; blockId: string }  // a character-sheet block, opened full-screen from BlockTreeEditor
  | null

/** Mobile-only: which full-screen view the MobileShell shows. Desktop ignores it. */
export type MobileView = 'chat' | TabId

interface UiState {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void

  // True while a campaign/adventure switch is reloading every store. App.tsx
  // unmounts the panes and shows a loading screen so nothing renders against
  // half-swapped state.
  scopeLoading: string | null  // the loading-screen label, null when idle
  setScopeLoading: (label: string | null) => void

  mobileView: MobileView
  setMobileView: (view: MobileView) => void

  selection: SelectionKind
  everSelected: boolean
  editDirty: boolean
  back: SelectionKind  // breadcrumb target when drilling into a sub-inspector

  select: (sel: SelectionKind) => void
  selectInto: (sel: SelectionKind) => void  // drill-down: remembers current as `back`
  goBack: () => void
  setEditDirty: (dirty: boolean) => void
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'home',
  setActiveTab: (tab) => set({ activeTab: tab }),

  scopeLoading: null,
  setScopeLoading: (label) => set({ scopeLoading: label }),

  mobileView: 'chat',
  setMobileView: (view) => set({ mobileView: view }),

  selection: null,
  everSelected: false,
  editDirty: false,
  back: null,

  select: (sel) => {
    set({
      selection: sel,
      everSelected: true,
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

  setEditDirty: (dirty) => set({ editDirty: dirty }),
}))
