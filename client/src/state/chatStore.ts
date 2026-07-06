import { create } from 'zustand'
import type { ChatEvent, ChatMessage, PlannerDelete } from '@shared/types/models'
import { api } from '../lib/api'
import { useItemsStore } from './itemsStore'
import { usePartyStore } from './partyStore'
import { useWorldbuildStore } from './worldbuildStore'
import { useActionSuggestionsStore } from './actionSuggestionsStore'
import { useTtsStore } from './ttsStore'
import { useLoreStore } from './loreStore'
import { useTasksStore } from './tasksStore'
import { useNarratorStore } from './narratorStore'

const PLANNING_KEY = 'wayward.planningMode'

/** Friendly status labels for narrator + Editor tool calls, shown while a turn works. */
const TOOL_STATUS: Record<string, string> = {
  // Narrator
  set_scene: 'Setting the scene',
  grant_item: 'Granting an item',
  remove_item: 'Removing an item',
  consume_item: 'Using an item',
  equip: 'Equipping gear',
  unequip: 'Stowing gear',
  lookup_item: 'Checking the world',
  search_items: 'Searching items',
  list_inventory: 'Checking inventory',
  get_character: 'Checking gear',
  // Editor (Planning mode)
  create_lore: 'Writing lore',
  update_lore: 'Editing lore',
  delete_lore: 'Removing lore',
  create_item: 'Forging an item',
  update_item: 'Editing an item',
  create_task: 'Adding a task',
  update_task: 'Editing a task',
  delete_task: 'Removing a task',
  update_task_status: 'Updating a task',
  create_member: 'Adding a party member',
  update_member: 'Editing a party member',
  delete_member: 'Removing a party member',
  set_in_party: 'Updating the party',
  update_pc: 'Editing the player character',
  set_scenario: 'Editing the Scenario',
  get_scenario: 'Reading the Scenario',
  set_narrator_instructions: 'Updating Narrator instructions',
  get_narrator_instructions: 'Reading Narrator instructions',
  set_first_message: 'Setting the opening',
  list_world: 'Reviewing the world',
  get_entry: 'Reading an entry',
}

/** Highest turn number within the active thread (narrator vs planner). */
function threadMaxTurn(messages: ChatMessage[], planning: boolean): number {
  const mode = planning ? 'planner' : 'narrator'
  return messages.reduce(
    (mx, m) => ((m.mode ?? 'narrator') === mode ? Math.max(mx, m.turnNumber) : mx),
    0,
  )
}

interface ChatState {
  messages: ChatMessage[]
  events: ChatEvent[]
  currentTurn: number
  planningMode: boolean
  pendingDeletes: PlannerDelete[]
  isLoading: boolean
  isSummarizing: boolean
  streamingContent: string
  thinkingStartedAt: number | null
  toolStatus: string | null
  toolFailures: string[]
  error: string | null
  contextTokens: number | null
  maxContextTokens: number | null
  activeVariants: Record<number, number>
  fetchHistory: () => Promise<void>
  fetchEvents: () => Promise<void>
  sendTurn: (message: string, image?: string | null) => Promise<void>
  regenerate: (guidance?: string) => Promise<void>
  retryLastTurn: () => Promise<void>
  swipe: (turn: number) => Promise<void>
  stopGeneration: () => void
  editMessage: (id: number, content: string) => Promise<void>
  deleteMessageAndAfter: (id: number) => Promise<void>
  setActiveVariant: (turn: number, variant: number) => void
  clearHistory: () => Promise<void>
  setPlanningMode: (v: boolean) => void
  applyPendingDeletes: () => Promise<void>
  dismissPendingDeletes: () => void
  clearToolFailures: () => void
}

let nextOptimisticId = -1
let _activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null
let _aborted = false

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  events: [],
  currentTurn: 0,
  planningMode: (() => { try { return localStorage.getItem(PLANNING_KEY) === '1' } catch { return false } })(),
  pendingDeletes: [],
  isLoading: false,
  isSummarizing: false,
  streamingContent: '',
  thinkingStartedAt: null,
  toolStatus: null,
  toolFailures: [],
  error: null,
  contextTokens: null,
  maxContextTokens: null,
  activeVariants: {},

  fetchHistory: async () => {
    const messages = await api.get<ChatMessage[]>('/chat/messages')
    const maxTurn = threadMaxTurn(messages, get().planningMode)

    const variants: Record<number, number> = { ...get().activeVariants }
    for (const m of messages) {
      if (m.role === 'assistant') {
        const current = variants[m.turnNumber]
        if (current === undefined || m.variant > current) {
          variants[m.turnNumber] = m.variant
        }
      }
    }
    set({ messages, currentTurn: maxTurn, activeVariants: variants })
    void get().fetchEvents()
  },

  fetchEvents: async () => {
    try {
      set({ events: await api.get<ChatEvent[]>('/chat/events') })
    } catch { /* toasts are non-critical */ }
  },

  sendTurn: async (message, image) => {
    const planning = get().planningMode
    const mode = planning ? 'planner' : 'narrator'
    const turn = threadMaxTurn(get().messages, planning) + 1

    const optimisticMsg: ChatMessage = {
      id: nextOptimisticId--,
      role: 'user',
      content: message,
      turnNumber: turn,
      variant: 0,
      speaker: 'player',
      mode,
      // Show the attached image immediately; the server-stored URL replaces it
      // on the next history fetch.
      imageUrl: image ?? null,
      createdAt: new Date().toISOString(),
    }
    set((s) => ({
      messages: [...s.messages, optimisticMsg],
      currentTurn: turn,
      isLoading: true,
      error: null,
      streamingContent: '',
      thinkingStartedAt: Date.now(),
    }))

    await _handleStream('/api/chat/turn', { message, mode, ...(image ? { image } : {}) })
  },

  regenerate: async (guidance) => {
    const turn = get().currentTurn
    const newVariants = { ...get().activeVariants }
    delete newVariants[turn]
    set((s) => ({
      messages: s.messages.filter((m) => !(m.role === 'assistant' && m.turnNumber === turn)),
      activeVariants: newVariants,
      isLoading: true,
      error: null,
      streamingContent: '',
      thinkingStartedAt: Date.now(),
    }))
    const body = guidance && guidance.trim() ? { guidance: guidance.trim() } : {}
    await _handleStream('/api/chat/regenerate', body)
  },

  // Re-run the last turn after a generation error. Same path as regenerate (it
  // re-generates the latest turn's assistant reply), which also recovers a
  // failed sendTurn where the user message persisted but no reply arrived.
  retryLastTurn: async () => {
    if (get().isLoading) return
    await get().regenerate()
  },

  swipe: async (turn) => {
    set({
      isLoading: true,
      error: null,
      streamingContent: '',
      thinkingStartedAt: Date.now(),
    })
    await _handleStream(`/api/chat/messages/${turn}/swipe`, {})
  },

  stopGeneration: () => {
    _aborted = true
    if (_activeReader) {
      _activeReader.cancel().catch(() => {})
      _activeReader = null
    }
  },

  editMessage: async (id, content) => {
    const updated = await api.put<ChatMessage>(`/chat/messages/${id}`, { content })
    set((s) => ({
      messages: s.messages.map((m) => (m.id === updated.id ? updated : m)),
    }))
  },

  deleteMessageAndAfter: async (id) => {
    useTtsStore.getState().stop()
    await api.del(`/chat/messages/${id}/and-after`)
    await get().fetchHistory()
  },

  setActiveVariant: (turn, variant) => {
    set((s) => ({
      activeVariants: { ...s.activeVariants, [turn]: variant },
    }))
  },

  clearHistory: async () => {
    useTtsStore.getState().stop()
    await api.del('/chat/messages')
    set({ messages: [], currentTurn: 0, activeVariants: {}, contextTokens: null, maxContextTokens: null })
  },

  setPlanningMode: (v) => {
    try { localStorage.setItem(PLANNING_KEY, v ? '1' : '0') } catch { /* ignore */ }
    // Re-derive the active thread's turn number on switch.
    set((s) => ({ planningMode: v, currentTurn: threadMaxTurn(s.messages, v), pendingDeletes: [] }))
  },

  applyPendingDeletes: async () => {
    const deletes = get().pendingDeletes
    if (deletes.length === 0) return
    set({ pendingDeletes: [] })
    await api.post('/planner/deletes/apply', { deletes })
    refreshWorldPanels()
  },

  dismissPendingDeletes: () => set({ pendingDeletes: [] }),
  clearToolFailures: () => set({ toolFailures: [] }),
}))

/** Refresh every panel a planner turn may have changed. */
function refreshWorldPanels() {
  useLoreStore.getState().fetchEntries()
  useTasksStore.getState().fetchTasks()
  usePartyStore.getState().fetchAll()
  useItemsStore.getState().fetchCatalog()
  useNarratorStore.getState().fetchConfig()
}

async function _handleStream(url: string, body: object) {
  const { set, get } = { set: useChatStore.setState, get: useChatStore.getState }
  _aborted = false
  set({ toolFailures: [] })  // clear any prior turn's failure notices
  useActionSuggestionsStore.getState().clear()
  useTtsStore.getState().stop()  // a new/regenerated turn silences the old one

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }

    const reader = res.body?.getReader()
    if (!reader) throw new Error('No response stream')
    _activeReader = reader

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      if (_aborted) break
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        try {
          const event = JSON.parse(payload)
          if (event.type === 'summarized') {
            set({ isSummarizing: false })
          } else if (event.type === 'meta') {
            // Planner turns omit contextTokens — only update when present.
            if (event.contextTokens !== undefined) set({ contextTokens: event.contextTokens })
            if (event.maxContextTokens !== undefined) set({ maxContextTokens: event.maxContextTokens })
          } else if (event.type === 'chunk') {
            // Final narration has begun — drop the thinking + tool status.
            if (get().thinkingStartedAt !== null || get().toolStatus !== null) {
              set({ thinkingStartedAt: null, toolStatus: null })
            }
            set({ streamingContent: get().streamingContent + event.content })
          } else if (event.type === 'discard') {
            // Agentic loop: content streamed on a tool-calling round was
            // preamble, not the final narration — clear it.
            set({ streamingContent: '' })
          } else if (event.type === 'tool') {
            // A narrator tool ran mid-turn — surface it as ephemeral status so
            // multi-round turns don't sit silently.
            set({ toolStatus: TOOL_STATUS[event.name as string] || 'Working' })
          } else if (event.type === 'done') {
            if (event.contextTokens !== undefined) set({ contextTokens: event.contextTokens })
            if (event.maxContextTokens !== undefined) set({ maxContextTokens: event.maxContextTokens })
            // The turn may have changed inventory (grant/consume/unequip) or
            // equipment (equip/unequip); refresh the affected panels so the UI
            // reflects the new DB state instead of going stale until reload.
            if (Array.isArray(event.appliedInventoryDeltas) && event.appliedInventoryDeltas.length > 0) {
              useItemsStore.getState().fetchInventory()
            }
            if (Array.isArray(event.appliedEquipmentChanges) && event.appliedEquipmentChanges.length > 0) {
              usePartyStore.getState().fetchAll()
            }
            // Planner turn: surface any queued deletions for confirmation.
            if (Array.isArray(event.pendingDeletes) && event.pendingDeletes.length > 0) {
              set({ pendingDeletes: event.pendingDeletes })
            }
            // A tool the narrator called failed (bad args / missing item) —
            // surface a graceful "the world stayed safe" notice in chat.
            if (Array.isArray(event.toolFailures) && event.toolFailures.length > 0) {
              set({ toolFailures: event.toolFailures })
            }
          } else if (event.type === 'error') {
            set({ error: event.content })
          }
        } catch { /* skip malformed */ }
      }
    }

    _activeReader = null

    const isPlanner = (body as { mode?: string }).mode === 'planner'

    // If stopped mid-stream, save partial content (narrator thread only).
    const partial = get().streamingContent
    if (_aborted && partial && !isPlanner) {
      try {
        await fetch('/api/chat/save-partial', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: partial }),
        })
      } catch { /* best effort */ }
    }

    await get().fetchHistory()

    if (!_aborted) {
      if (isPlanner) {
        // Planner create/edit ops already applied server-side — refresh panels.
        refreshWorldPanels()
      } else {
        // After a narration turn, let the Chronicler review it (no-op when
        // disabled). Fire-and-forget so it never blocks the chat UI.
        const latestTurn = threadMaxTurn(get().messages, false)
        if (latestTurn > 0) void useWorldbuildStore.getState().runForTurn(latestTurn)
        if (latestTurn > 0) void useActionSuggestionsStore.getState().runForTurn(latestTurn)
        if (latestTurn > 0) void useTtsStore.getState().runForTurn(latestTurn)
      }
    }
  } catch (e) {
    if (_aborted) {
      await get().fetchHistory()
    } else {
      const msg = e instanceof Error ? e.message : 'Something went wrong'
      set({ error: msg })
    }
  } finally {
    _activeReader = null
    _aborted = false
    set({ isLoading: false, isSummarizing: false, streamingContent: '', thinkingStartedAt: null, toolStatus: null })
  }
}
