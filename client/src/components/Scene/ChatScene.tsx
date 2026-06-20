import { useRef, useEffect, useState, useCallback } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useSettingsStore } from '../../state/settingsStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'
import type { ChatMessage } from '@shared/types/models'

interface PromptLogMessage {
  role: string
  content: string
}

export function ChatScene() {
  const messages = useChatStore((s) => s.messages)
  const isLoading = useChatStore((s) => s.isLoading)
  const isSummarizing = useChatStore((s) => s.isSummarizing)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const thinkingStartedAt = useChatStore((s) => s.thinkingStartedAt)
  const error = useChatStore((s) => s.error)
  const sendTurn = useChatStore((s) => s.sendTurn)
  const regenerate = useChatStore((s) => s.regenerate)
  const stopGeneration = useChatStore((s) => s.stopGeneration)
  const deleteMessageAndAfter = useChatStore((s) => s.deleteMessageAndAfter)
  const clearHistory = useChatStore((s) => s.clearHistory)
  const contextTokens = useChatStore((s) => s.contextTokens)
  const maxContextTokens = useChatStore((s) => s.maxContextTokens)
  const activeVariants = useChatStore((s) => s.activeVariants)
  const setActiveVariant = useChatStore((s) => s.setActiveVariant)
  const apiKeySet = useSettingsStore((s) => s.apiKeySet)

  const [input, setInput] = useState('')
  const [promptLog, setPromptLog] = useState<PromptLogMessage[] | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages, streamingContent])

  const handleSend = () => {
    const text = input.trim()
    if (!text || isLoading) return
    setInput('')
    sendTurn(text)
  }

  const handleShowLog = async () => {
    try {
      const log = await api.get<PromptLogMessage[]>('/chat/prompt-log')
      setPromptLog(log)
    } catch {
      setPromptLog([{ role: 'error', content: 'No prompt log available yet.' }])
    }
  }

  // Build the visible message list — one assistant message per turn (the active variant)
  const visibleMessages = buildVisibleMessages(messages, activeVariants)
  const lastTurn = Math.max(0, ...messages.map((m) => m.turnNumber))

  // Get variant info for each turn
  const variantCounts = getVariantCounts(messages)

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div ref={listRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !isLoading && (
          <div className="flex items-center justify-center h-full">
            <p className="font-ui text-[10px] text-textdim tracking-wider">
              {apiKeySet ? 'BEGIN YOUR ADVENTURE' : 'SET API KEY IN SETTINGS TO BEGIN'}
            </p>
          </div>
        )}

        {visibleMessages.map((m) => (
          <MessageBubble
            key={`${m.id}-${m.variant}`}
            message={m}
            variantCount={m.role === 'assistant' ? (variantCounts[m.turnNumber] ?? 1) : 1}
            activeVariant={m.role === 'assistant' ? (activeVariants[m.turnNumber] ?? 0) : 0}
            onSwipe={m.role === 'assistant' ? (dir) => {
              const count = variantCounts[m.turnNumber] ?? 1
              const current = activeVariants[m.turnNumber] ?? 0
              const next = dir === 'left'
                ? Math.max(0, current - 1)
                : Math.min(count - 1, current + 1)
              setActiveVariant(m.turnNumber, next)
            } : undefined}
            isLastAssistant={m.role === 'assistant' && m.turnNumber === lastTurn}
            onRegenerate={!isLoading ? regenerate : undefined}
            onDelete={!isLoading && m.id > 0 ? () => setConfirmAction({ message: 'Delete this message and everything after it?', action: () => deleteMessageAndAfter(m.id) }) : undefined}
          />
        ))}

        {/* Streaming response */}
        {isLoading && streamingContent && (
          <div className="max-w-[85%] mr-auto bg-bg1 border-[1.5px] border-line2 px-4 py-3">
            <div
              className="text-sm font-body text-text leading-relaxed whitespace-pre-wrap"
              dangerouslySetInnerHTML={{ __html: formatNarration(streamingContent) }}
            />
          </div>
        )}

        {/* Thinking / summarizing indicator */}
        {isLoading && !streamingContent && (
          <div className="mr-auto px-4 py-3">
            <ThinkingIndicator startedAt={thinkingStartedAt} isSummarizing={isSummarizing} />
          </div>
        )}

        {error && (
          <div className="mr-auto bg-bg1 border-[1.5px] border-line px-4 py-3">
            <p className="font-ui text-[10px] text-textdim">{error}</p>
          </div>
        )}
      </div>

      {/* Context size bar */}
      {contextTokens !== null && maxContextTokens !== null && (
        <div className="px-4 py-1.5 border-t border-line bg-bg2 flex items-center justify-between">
          <span className="font-ui text-[8px] text-textdim tracking-wider">
            CONTEXT {contextTokens.toLocaleString()} / {maxContextTokens.toLocaleString()} TOKENS
          </span>
          <div className="w-32 h-1.5 bg-bg3 rounded-full overflow-hidden">
            <div
              className="h-full bg-golddeep rounded-full transition-all"
              style={{ width: `${Math.min(100, (contextTokens / maxContextTokens) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t-[1.5px] border-line2 p-4 bg-bg1">
        <div className="flex gap-2">
          <textarea
            className="flex-1 border-[1.5px] border-line bg-bg0 px-3 py-2 text-sm font-body text-text outline-none focus:border-line2 transition-colors resize-none"
            rows={2}
            placeholder={apiKeySet ? 'What do you do?' : 'Set API key in Settings...'}
            value={input}
            disabled={!apiKeySet || isLoading}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
          />
          <div className="flex flex-col gap-1">
            {isLoading ? (
              <button
                type="button"
                className="font-ui text-[10px] bg-golddeep text-bg0 px-3 py-1 hover:bg-gold transition-colors"
                onClick={stopGeneration}
              >
                STOP
              </button>
            ) : (
              <button
                type="button"
                className="font-ui text-[10px] bg-golddeep text-bg0 px-3 py-1 hover:bg-gold transition-colors disabled:opacity-40"
                disabled={!apiKeySet || !input.trim()}
                onClick={handleSend}
              >
                SEND
              </button>
            )}
            {messages.length > 0 && (
              <div className="flex gap-1">
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim hover:text-text px-2 py-1"
                  onClick={handleShowLog}
                >
                  LOG
                </button>
                <button
                  type="button"
                  className="font-ui text-[9px] text-textdim hover:text-text px-2 py-1"
                  onClick={() => setConfirmAction({ message: 'Clear the entire chat history? This cannot be undone.', action: clearHistory })}
                >
                  CLEAR
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {promptLog && (
        <PromptLogModal messages={promptLog} onClose={() => setPromptLog(null)} />
      )}
      {confirmAction && (
        <ConfirmDialog
          message={confirmAction.message}
          onConfirm={() => { confirmAction.action(); setConfirmAction(null) }}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  )
}

// ── Message Bubble with edit, swipe, regenerate ──────────────────

function MessageBubble({
  message,
  variantCount,
  activeVariant,
  onSwipe,
  isLastAssistant,
  onRegenerate,
  onDelete,
}: {
  message: ChatMessage
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  isLastAssistant?: boolean
  onRegenerate?: () => void
  onDelete?: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(message.content)
  const editMessage = useChatStore((s) => s.editMessage)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setEditText(message.content)
  }, [message.content])

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [editing])

  const handleSaveEdit = useCallback(async () => {
    if (message.id < 0) return
    const trimmed = editText.trim()
    if (trimmed && trimmed !== message.content) {
      await editMessage(message.id, trimmed)
    }
    setEditing(false)
  }, [editText, message.id, message.content, editMessage])

  const isUser = message.role === 'user'

  return (
    <div className={`max-w-[85%] group ${isUser ? 'ml-auto' : 'mr-auto'}`}>
      <div
        className={`${
          isUser
            ? 'bg-bg2 border-[1.5px] border-line'
            : 'bg-bg1 border-[1.5px] border-line2'
        } px-4 py-3 cursor-pointer`}
        onClick={() => {
          if (!editing && message.id > 0) {
            setEditing(true)
          }
        }}
      >
        {editing ? (
          <div className="space-y-2">
            <textarea
              ref={textareaRef}
              title="Edit message"
              className="w-full text-sm font-body text-text bg-bg0 border-[1.5px] border-line p-2 outline-none focus:border-line2 resize-y min-h-[48px]"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && e.ctrlKey) {
                  e.preventDefault()
                  handleSaveEdit()
                }
                if (e.key === 'Escape') {
                  setEditText(message.content)
                  setEditing(false)
                }
              }}
              onClick={(e) => e.stopPropagation()}
            />
            <div className="flex gap-2">
              <button
                type="button"
                className="font-ui text-[9px] text-bg0 bg-golddeep px-2 py-0.5 hover:bg-gold"
                onClick={(e) => { e.stopPropagation(); handleSaveEdit() }}
              >
                SAVE
              </button>
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text px-2 py-0.5"
                onClick={(e) => {
                  e.stopPropagation()
                  setEditText(message.content)
                  setEditing(false)
                }}
              >
                CANCEL
              </button>
              <span className="font-ui text-[8px] text-textdim self-center">CTRL+ENTER TO SAVE</span>
            </div>
          </div>
        ) : (
          <div
            className="text-sm font-body text-text leading-relaxed whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ __html: formatNarration(message.content) }}
          />
        )}
      </div>

      {/* Actions bar */}
      {!editing && (
        <div className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
          style={(!isUser && (variantCount > 1 || isLastAssistant)) ? { opacity: 1 } : undefined}
        >
          {!isUser && variantCount > 1 && (
            <>
              <button
                type="button"
                className="font-ui text-[10px] text-textdim hover:text-text disabled:opacity-30"
                disabled={activeVariant === 0}
                onClick={() => onSwipe?.('left')}
              >
                ◀
              </button>
              <span className="font-ui text-[8px] text-textdim tracking-wider">
                {activeVariant + 1}/{variantCount}
              </span>
              <button
                type="button"
                className="font-ui text-[10px] text-textdim hover:text-text disabled:opacity-30"
                disabled={activeVariant === variantCount - 1}
                onClick={() => onSwipe?.('right')}
              >
                ▶
              </button>
            </>
          )}
          <div className="flex items-center gap-1 ml-auto">
            {isLastAssistant && onRegenerate && (
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={onRegenerate}
              >
                REGENERATE
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={onDelete}
              >
                DELETE
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────

function buildVisibleMessages(
  messages: ChatMessage[],
  activeVariants: Record<number, number>,
): ChatMessage[] {
  const result: ChatMessage[] = []
  for (const m of messages) {
    if (m.role === 'user') {
      result.push(m)
    } else if (m.role === 'assistant') {
      const activeV = activeVariants[m.turnNumber] ?? 0
      if (m.variant === activeV) {
        result.push(m)
      }
    }
  }
  return result
}

function getVariantCounts(messages: ChatMessage[]): Record<number, number> {
  const counts: Record<number, number> = {}
  for (const m of messages) {
    if (m.role === 'assistant') {
      counts[m.turnNumber] = (counts[m.turnNumber] ?? 0) + 1
    }
  }
  return counts
}

function ThinkingIndicator({ startedAt, isSummarizing }: { startedAt: number | null; isSummarizing: boolean }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!startedAt) return
    setElapsed(0)
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [startedAt])

  const label = isSummarizing ? 'SUMMARIZING HISTORY' : 'THINKING'

  return (
    <span className="font-ui text-[10px] text-textdim tracking-wider">
      {label}{elapsed > 0 ? ` ${elapsed}s` : ''}
      <span className="animate-pulse"> ···</span>
    </span>
  )
}

function PromptLogModal({ messages, onClose }: { messages: PromptLogMessage[]; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/80">
      <div className="bg-bg1 border-[1.5px] border-line2 w-[720px] max-w-[90vw] max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b-[1.5px] border-line2">
          <h2 className="font-ui text-[11px] tracking-wider">PROMPT LOG</h2>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim hover:text-text"
            onClick={onClose}
          >
            CLOSE
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.map((m, i) => (
            <div key={i} className="space-y-1">
              <span className="font-ui text-[9px] tracking-wider text-textsec uppercase">
                {m.role}
              </span>
              <pre className="text-[12px] font-body text-text leading-relaxed whitespace-pre-wrap bg-bg0 border-[1.5px] border-line p-3 overflow-x-auto">
                {m.content}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function formatNarration(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>')
    .replace(/\n/g, '<br/>')
}
