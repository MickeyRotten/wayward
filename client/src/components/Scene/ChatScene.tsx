import { useRef, useEffect, useState, useCallback } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useSettingsStore } from '../../state/settingsStore'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
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

  const playerCharacter = usePartyStore((s) => s.playerCharacter)
  const partyMembers = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)

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

  // Determine if we should show the "What do you do?" divider
  const lastVisibleMsg = visibleMessages[visibleMessages.length - 1]
  const showWhatDoYouDo =
    !isLoading &&
    lastVisibleMsg &&
    lastVisibleMsg.role === 'assistant' &&
    visibleMessages.length > 0

  // Find first narrator message index for drop-cap
  const firstNarratorIdx = visibleMessages.findIndex(
    (m) => m.role === 'assistant' && (m.speaker === 'narrator' || !m.speaker)
  )

  // Build a lookup for party member info by id
  const partyMemberMap = new Map(
    partyMembers.map((pm) => [pm.id, pm])
  )

  // PC info
  const pcName = playerCharacter?.basicInfo?.name || 'Player'
  const pcPortrait = playerCharacter?.basicInfo?.portrait || ''

  // Item names for inline chip rendering
  const itemNames = catalog.map((item) => item.name).filter(Boolean)

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div ref={listRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !isLoading && (
          <div className="flex items-center justify-center h-full">
            <p className="font-ui text-[10px] text-textdim tracking-wider">
              {apiKeySet ? 'BEGIN YOUR ADVENTURE' : 'SET API KEY IN SETTINGS TO BEGIN'}
            </p>
          </div>
        )}

        {visibleMessages.map((m, idx) => (
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
            isFirstNarrator={idx === firstNarratorIdx}
            pcName={pcName}
            pcPortrait={pcPortrait}
            partyMemberMap={partyMemberMap}
            itemNames={itemNames}
          />
        ))}

        {/* "What do you do?" divider */}
        {showWhatDoYouDo && (
          <div className="flex items-center gap-3 py-1">
            <div className="flex-1 border-t border-line" />
            <span className="font-disp text-[13px] text-golddeep tracking-wide pt-[2px]">
              What do you do?
            </span>
            <div className="flex-1 border-t border-line" />
          </div>
        )}

        {/* Streaming response */}
        {isLoading && streamingContent && (
          <div className="max-w-[85%] mr-auto px-4 py-3">
            <div
              className="text-sm font-body text-text2 leading-relaxed whitespace-pre-wrap"
              dangerouslySetInnerHTML={{ __html: applyItemChips(formatNarration(streamingContent), itemNames) }}
            />
          </div>
        )}

        {/* Generating indicator — narrator avatar with animated dots */}
        {isLoading && !streamingContent && (
          <div className="flex items-start gap-3 mr-auto px-1 py-3">
            <div className="w-10 h-10 rounded-sm border-[1.5px] border-gold bg-bg2 flex items-center justify-center flex-shrink-0">
              <span className="font-disp text-[16px] text-gold pt-[2px]">N</span>
            </div>
            <div className="pt-2">
              <ThinkingIndicator startedAt={thinkingStartedAt} isSummarizing={isSummarizing} />
            </div>
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

// ── Portrait Component ──────────────────────────────────────────────

function Portrait({
  src,
  name,
  borderColor,
}: {
  src?: string
  name: string
  borderColor: string
}) {
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div
      className={`w-10 h-10 rounded-sm border-[1.5px] bg-bg2 flex items-center justify-center flex-shrink-0 overflow-hidden ${borderColor}`}
    >
      {src ? (
        <img
          src={src.startsWith('/') || src.startsWith('http') ? src : `/portraits/${src}`}
          alt={name}
          className="w-full h-full object-cover"
        />
      ) : (
        <span className="font-disp text-[14px] text-textsec pt-[2px]">
          {initials || '?'}
        </span>
      )}
    </div>
  )
}

// ── Message Bubble with speaker differentiation ────────────────────

function MessageBubble({
  message,
  variantCount,
  activeVariant,
  onSwipe,
  isLastAssistant,
  onRegenerate,
  onDelete,
  isFirstNarrator,
  pcName,
  pcPortrait,
  partyMemberMap,
  itemNames,
}: {
  message: ChatMessage
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  isLastAssistant?: boolean
  onRegenerate?: () => void
  onDelete?: () => void
  isFirstNarrator?: boolean
  pcName: string
  pcPortrait: string
  partyMemberMap: Map<string, { id: string; basicInfo: { name: string; portrait?: string } }>
  itemNames: string[]
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
  const isNarrator = message.role === 'assistant' && (message.speaker === 'narrator' || !message.speaker)

  // Check if this is a party member speaking (assistant message with a party member speaker)
  const partyMember = !isUser && !isNarrator && message.speaker
    ? partyMemberMap.get(message.speaker)
    : undefined

  // Determine rendering style based on speaker type
  if (isUser) {
    // ── Player Character message ──
    return (
      <div className="max-w-[85%] ml-auto group">
        <div className="flex items-start gap-3 justify-end">
          <div className="flex-1 min-w-0">
            {/* Name header */}
            <div className="text-right mb-1">
              <span className="font-disp text-[13px] text-blue pt-[2px]">
                {pcName} <span className="font-ui text-[9px] text-blue/60 tracking-wider">YOU</span>
              </span>
            </div>

            {/* Message content */}
            <div
              className="bg-bg2 border-[1.5px] border-line px-4 py-3 cursor-pointer"
              onClick={() => {
                if (!editing && message.id > 0) setEditing(true)
              }}
            >
              {editing ? (
                <EditArea
                  ref={textareaRef}
                  value={editText}
                  onChange={setEditText}
                  onSave={handleSaveEdit}
                  onCancel={() => { setEditText(message.content); setEditing(false) }}
                />
              ) : (
                <div
                  className="text-sm font-body text-text leading-relaxed whitespace-pre-wrap"
                  dangerouslySetInnerHTML={{ __html: applyItemChips(formatNarration(message.content), itemNames) }}
                />
              )}
            </div>
          </div>

          {/* Portrait */}
          <Portrait
            src={pcPortrait}
            name={pcName}
            borderColor="border-blue"
          />
        </div>

        {/* Actions bar */}
        {!editing && (
          <div className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity justify-end">
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
        )}
      </div>
    )
  }

  if (partyMember) {
    // ── Party Member message ──
    const pmName = partyMember.basicInfo?.name || 'Party Member'
    const pmPortrait = partyMember.basicInfo?.portrait || ''

    return (
      <div className="max-w-[85%] mr-auto group">
        <div className="flex items-start gap-3">
          {/* Portrait */}
          <Portrait
            src={pmPortrait}
            name={pmName}
            borderColor="border-line2"
          />

          <div className="flex-1 min-w-0">
            {/* Name header + spotlight badge */}
            <div className="mb-1 flex items-center gap-2">
              <span className="font-disp text-[13px] text-gold pt-[2px]">
                {pmName.split(' ')[0]}
              </span>
              {message.spotlightReason && (
                <span className={`text-[10px] font-ui px-1.5 py-0.5 border rounded-full ${
                  message.spotlightReason === 'Hasn\'t spoken in a while'
                    ? 'border-golddeep text-golddeep'
                    : 'border-gold text-gold'
                }`}>
                  {message.spotlightReason}
                </span>
              )}
            </div>

            {/* Message content */}
            <div
              className="px-4 py-3 cursor-pointer"
              onClick={() => {
                if (!editing && message.id > 0) setEditing(true)
              }}
            >
              {editing ? (
                <EditArea
                  ref={textareaRef}
                  value={editText}
                  onChange={setEditText}
                  onSave={handleSaveEdit}
                  onCancel={() => { setEditText(message.content); setEditing(false) }}
                />
              ) : (
                <div
                  className="text-sm font-body text-text2 leading-relaxed whitespace-pre-wrap"
                  dangerouslySetInnerHTML={{ __html: applyItemChips(formatNarration(message.content), itemNames) }}
                />
              )}
            </div>
          </div>
        </div>

        {/* Actions bar */}
        <ActionsBar
          editing={editing}
          isUser={false}
          variantCount={variantCount}
          activeVariant={activeVariant}
          onSwipe={onSwipe}
          isLastAssistant={isLastAssistant}
          onRegenerate={onRegenerate}
          onDelete={onDelete}
        />
      </div>
    )
  }

  // ── Narrator message (default for assistant) ──
  return (
    <div className="max-w-[85%] mr-auto group">
      <div
        className="px-4 py-3 cursor-pointer"
        onClick={() => {
          if (!editing && message.id > 0) setEditing(true)
        }}
      >
        {editing ? (
          <EditArea
            ref={textareaRef}
            value={editText}
            onChange={setEditText}
            onSave={handleSaveEdit}
            onCancel={() => { setEditText(message.content); setEditing(false) }}
          />
        ) : (
          <div
            className={`text-sm font-body text-text2 leading-relaxed whitespace-pre-wrap ${
              isFirstNarrator ? 'first-narrator-dropcap' : ''
            }`}
            dangerouslySetInnerHTML={{
              __html: applyItemChips(
                isFirstNarrator
                  ? formatNarrationWithDropCap(message.content)
                  : formatNarration(message.content),
                itemNames,
              ),
            }}
          />
        )}
      </div>

      {/* Actions bar */}
      <ActionsBar
        editing={editing}
        isUser={false}
        variantCount={variantCount}
        activeVariant={activeVariant}
        onSwipe={onSwipe}
        isLastAssistant={isLastAssistant}
        onRegenerate={onRegenerate}
        onDelete={onDelete}
      />
    </div>
  )
}

// ── Shared Actions Bar ──────────────────────────────────────────────

function ActionsBar({
  editing,
  isUser,
  variantCount,
  activeVariant,
  onSwipe,
  isLastAssistant,
  onRegenerate,
  onDelete,
}: {
  editing: boolean
  isUser: boolean
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  isLastAssistant?: boolean
  onRegenerate?: () => void
  onDelete?: () => void
}) {
  if (editing) return null

  return (
    <div
      className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
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
            &#9664;
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
            &#9654;
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
  )
}

// ── Edit Area (shared between all message types) ────────────────────

import { forwardRef } from 'react'

const EditArea = forwardRef<
  HTMLTextAreaElement,
  {
    value: string
    onChange: (v: string) => void
    onSave: () => void
    onCancel: () => void
  }
>(function EditArea({ value, onChange, onSave, onCancel }, ref) {
  return (
    <div className="space-y-2">
      <textarea
        ref={ref}
        title="Edit message"
        className="w-full text-sm font-body text-text bg-bg0 border-[1.5px] border-line p-2 outline-none focus:border-line2 resize-y min-h-[48px]"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault()
            onSave()
          }
          if (e.key === 'Escape') {
            onCancel()
          }
        }}
        onClick={(e) => e.stopPropagation()}
      />
      <div className="flex gap-2">
        <button
          type="button"
          className="font-ui text-[9px] text-bg0 bg-golddeep px-2 py-0.5 hover:bg-gold"
          onClick={(e) => { e.stopPropagation(); onSave() }}
        >
          SAVE
        </button>
        <button
          type="button"
          className="font-ui text-[9px] text-textdim hover:text-text px-2 py-0.5"
          onClick={(e) => {
            e.stopPropagation()
            onCancel()
          }}
        >
          CANCEL
        </button>
        <span className="font-ui text-[8px] text-textdim self-center">CTRL+ENTER TO SAVE</span>
      </div>
    </div>
  )
})

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

function applyItemChips(html: string, itemNames: string[]): string {
  if (itemNames.length === 0) return html
  // Sort by length descending so longer names match first (e.g. "Tide-Salt Draught" before "Salt")
  const sorted = [...itemNames].sort((a, b) => b.length - a.length)
  // Build a single regex that matches any item name (case-insensitive, word-boundary)
  const escaped = sorted.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const itemRe = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')
  // Split HTML into tags and text segments, only process text segments
  return html.replace(/(<[^>]*>)|([^<]+)/g, (_, tag, text) => {
    if (tag) return tag
    return text.replace(itemRe, '<span class="text-gold2 bg-gold/10 px-1 rounded text-sm font-ui">$1</span>')
  })
}

function formatNarrationWithDropCap(text: string): string {
  // Extract the first character for the drop cap
  const formatted = formatNarration(text)

  // Find the first actual text character (skip any leading HTML tags)
  const match = formatted.match(/^(<[^>]*>)*([^<])/)
  if (!match) return formatted

  const leadingTags = match[1] || ''
  const firstChar = match[2]
  const rest = formatted.slice(leadingTags.length + 1)

  return (
    leadingTags +
    `<span class="font-disp text-gold text-[3rem] float-left leading-[0.8] mr-2 mt-[0.15rem]">${firstChar}</span>` +
    rest
  )
}
