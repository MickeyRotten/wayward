import { create } from 'zustand'
import type { ChatMessage } from '@shared/types/models'
import { api } from '../lib/api'

interface ChatState {
  messages: ChatMessage[]
  currentTurn: number
  isLoading: boolean
  isSummarizing: boolean
  streamingContent: string
  thinkingStartedAt: number | null
  error: string | null
  contextTokens: number | null
  maxContextTokens: number | null
  activeVariants: Record<number, number>
  fetchHistory: () => Promise<void>
  sendTurn: (message: string) => Promise<void>
  regenerate: () => Promise<void>
  stopGeneration: () => void
  editMessage: (id: number, content: string) => Promise<void>
  deleteMessageAndAfter: (id: number) => Promise<void>
  setActiveVariant: (turn: number, variant: number) => void
  clearHistory: () => Promise<void>
}

let nextOptimisticId = -1
let _activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null
let _aborted = false

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  currentTurn: 0,
  isLoading: false,
  isSummarizing: false,
  streamingContent: '',
  thinkingStartedAt: null,
  error: null,
  contextTokens: null,
  maxContextTokens: null,
  activeVariants: {},

  fetchHistory: async () => {
    const messages = await api.get<ChatMessage[]>('/chat/messages')
    const maxTurn = messages.reduce((max, m) => Math.max(max, m.turnNumber), 0)

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
  },

  sendTurn: async (message) => {
    const turn = get().currentTurn + 1

    const optimisticMsg: ChatMessage = {
      id: nextOptimisticId--,
      role: 'user',
      content: message,
      turnNumber: turn,
      variant: 0,
      speaker: 'player',
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

    await _handleStream('/api/chat/turn', { message })
  },

  regenerate: async () => {
    const turn = get().currentTurn
    set((s) => ({
      messages: s.messages.filter((m) => !(m.role === 'assistant' && m.turnNumber === turn)),
      isLoading: true,
      error: null,
      streamingContent: '',
      thinkingStartedAt: Date.now(),
    }))
    await _handleStream('/api/chat/regenerate', {})
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
    await api.del(`/chat/messages/${id}/and-after`)
    await get().fetchHistory()
  },

  setActiveVariant: (turn, variant) => {
    set((s) => ({
      activeVariants: { ...s.activeVariants, [turn]: variant },
    }))
  },

  clearHistory: async () => {
    await api.del('/chat/messages')
    set({ messages: [], currentTurn: 0, activeVariants: {}, contextTokens: null, maxContextTokens: null })
  },
}))

async function _handleStream(url: string, body: object) {
  const { set, get } = { set: useChatStore.setState, get: useChatStore.getState }
  _aborted = false

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
            set({ contextTokens: event.contextTokens, maxContextTokens: event.maxContextTokens })
          } else if (event.type === 'chunk') {
            if (get().thinkingStartedAt !== null) {
              set({ thinkingStartedAt: null })
            }
            set({ streamingContent: get().streamingContent + event.content })
          } else if (event.type === 'done') {
            set({ contextTokens: event.contextTokens, maxContextTokens: event.maxContextTokens })
          } else if (event.type === 'error') {
            set({ error: event.content })
          }
        } catch { /* skip malformed */ }
      }
    }

    _activeReader = null

    // If stopped mid-stream, save partial content
    const partial = get().streamingContent
    if (_aborted && partial) {
      try {
        await fetch('/api/chat/save-partial', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: partial }),
        })
      } catch { /* best effort */ }
    }

    await get().fetchHistory()
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
    set({ isLoading: false, isSummarizing: false, streamingContent: '', thinkingStartedAt: null })
  }
}
