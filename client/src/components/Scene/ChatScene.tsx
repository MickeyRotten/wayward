import { useRef, useEffect, useState, useCallback } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useWorldbuildStore } from '../../state/worldbuildStore'
import { useSettingsStore } from '../../state/settingsStore'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'
import { deriveSceneBanner } from '../../lib/location'
import type { ChatMessage, ItemCatalogEntry, InventoryDelta, EquipmentChange } from '@shared/types/models'

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
  const swipe = useChatStore((s) => s.swipe)
  const stopGeneration = useChatStore((s) => s.stopGeneration)
  const deleteMessageAndAfter = useChatStore((s) => s.deleteMessageAndAfter)
  const clearHistory = useChatStore((s) => s.clearHistory)
  const contextTokens = useChatStore((s) => s.contextTokens)
  const maxContextTokens = useChatStore((s) => s.maxContextTokens)
  const worldbuildRunning = useWorldbuildStore((s) => s.running)
  // Block input until the narrator AND the post-turn Chronicler are both done.
  const busy = isLoading || worldbuildRunning
  const activeVariants = useChatStore((s) => s.activeVariants)
  const setActiveVariant = useChatStore((s) => s.setActiveVariant)
  const apiKeySet = useSettingsStore((s) => s.apiKeySet)
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const planningMode = useChatStore((s) => s.planningMode)
  const setPlanningMode = useChatStore((s) => s.setPlanningMode)
  const pendingDeletes = useChatStore((s) => s.pendingDeletes)
  const applyPendingDeletes = useChatStore((s) => s.applyPendingDeletes)
  const dismissPendingDeletes = useChatStore((s) => s.dismissPendingDeletes)

  const playerCharacter = usePartyStore((s) => s.playerCharacter)
  const partyMembers = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)

  const [input, setInput] = useState('')
  const [promptLog, setPromptLog] = useState<PromptLogMessage[] | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)
  const [toolsOpen, setToolsOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages, streamingContent])

  // Auto-grow the input: single row by default, expand with wrapped lines up
  // to a cap, then scroll.
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [input])

  const handleSend = () => {
    const text = input.trim()
    if (!text || busy) return
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

  // Restrict to the active thread: narration vs the Planning conversation.
  const threadMode = planningMode ? 'planner' : 'narrator'
  const threadMessages = messages.filter((m) => (m.mode ?? 'narrator') === threadMode)

  // Build the visible message list — one assistant message per turn (the active variant)
  const visibleMessages = buildVisibleMessages(threadMessages, activeVariants)
  const lastTurn = Math.max(0, ...threadMessages.map((m) => m.turnNumber))

  // Get variant info for each turn
  const variantCounts = getVariantCounts(threadMessages)

  // Determine if we should show the "What do you do?" divider
  const lastVisibleMsg = visibleMessages[visibleMessages.length - 1]
  const showWhatDoYouDo =
    !isLoading &&
    lastVisibleMsg &&
    lastVisibleMsg.role === 'assistant' &&
    visibleMessages.length > 0

  // Show regenerate in input area when last message is from assistant,
  // or user sent something but no assistant response exists yet
  const showInputRegenerate =
    !busy &&
    messages.length > 0 &&
    (
      (lastVisibleMsg && lastVisibleMsg.role === 'assistant') ||
      (lastVisibleMsg && lastVisibleMsg.role === 'user')
    )

  // Find first narrator message index for drop-cap. When a configured First
  // Message is shown, IT carries the drop-cap, so real messages never do.
  const hasFirstMessage = !planningMode && !!firstMessage.trim()
  const firstNarratorIdx = hasFirstMessage
    ? -1
    : visibleMessages.findIndex(
        (m) => m.role === 'assistant' && (m.speaker === 'narrator' || !m.speaker)
      )

  // Build a lookup for party member info by id
  const partyMemberMap = new Map(
    partyMembers.map((pm) => [pm.id, pm])
  )

  // PC info
  const pcName = playerCharacter?.basicInfo?.name || 'Player'
  const pcPortrait = playerCharacter?.basicInfo?.portrait || ''

  // Item and character names to highlight inline in the narration.
  const chipEntities: ChipEntity[] = [
    ...catalog.map((item) => ({ name: item.name, kind: 'item' as const, id: item.id })),
    ...partyMembers.map((m) => ({ name: m.basicInfo?.name || '', kind: 'member' as const, id: m.id })),
    ...(playerCharacter ? [{ name: pcName, kind: 'member' as const, id: playerCharacter.id }] : []),
  ].filter((e) => e.name.trim() && e.name !== 'Player')

  // Item id -> catalog entry, for resolving names in inventory/equipment notices
  const catalogMap = new Map(catalog.map((item) => [item.id, item]))

  // Resolve a character id to a display name (player character or party member)
  const resolveCharName = useCallback(
    (id: string): string => {
      if (playerCharacter && id === playerCharacter.id) {
        return playerCharacter.basicInfo?.name || 'Player'
      }
      return partyMemberMap.get(id)?.basicInfo?.name || 'Someone'
    },
    [playerCharacter, partyMemberMap],
  )

  const banner = deriveSceneBanner(visibleMessages)

  return (
    <div className="flex flex-col h-full">
      {/* Chat header — location banner, or a PLANNING banner in Planning mode */}
      <div
        className="flex-shrink-0 border-b border-line2 bg-bg2 px-4 pt-3 pb-2.5 flex items-start justify-between gap-3"
        style={{
          backgroundImage:
            'radial-gradient(circle, rgba(201,165,88,0.08) 1px, transparent 1px)',
          backgroundSize: '4px 4px',
        }}
      >
        <div className="flex items-start gap-2.5 min-w-0">
          {/* Play / Edit mode toggle (Unity-style): lit while playing (Narration). */}
          <button
            type="button"
            disabled={busy}
            title={planningMode ? 'Exit Edit Mode — back to play' : 'Edit Mode — work on the world'}
            onClick={() => setPlanningMode(!planningMode)}
            className={`shrink-0 mt-[1px] w-7 h-7 flex items-center justify-center border rounded-sm transition-colors disabled:opacity-40 ${
              planningMode
                ? 'border-line2 text-textsec hover:text-text'
                : 'border-gold text-gold bg-gold/10'
            }`}
          >
            {planningMode ? (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83a.996.996 0 0 0 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29z" />
              </svg>
            ) : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
            )}
          </button>
          <div className="min-w-0">
          <span className="font-ui text-[8px] tracking-[0.2em] uppercase text-textdim block">
            {planningMode ? 'Mode' : 'Location'}
          </span>
          <h1 className="font-disp text-[22px] leading-none text-gold pt-[3px] truncate">
            {planningMode ? 'Edit Mode' : banner.location}
          </h1>
          {!planningMode && banner.day && (
            <span className="font-ui text-[9px] tracking-wider uppercase text-textsec block mt-1">
              Day {banner.day}
            </span>
          )}
          </div>
        </div>
        {!planningMode && (banner.timeOfDay || banner.weather) && (
          <div className="shrink-0 text-right">
            {banner.timeOfDay && (
              <div className="flex items-center justify-end gap-1.5 text-gold">
                <TimeOfDayIcon timeOfDay={banner.timeOfDay} />
                <span className="font-ui text-[11px] tracking-wider uppercase">{banner.timeOfDay}</span>
              </div>
            )}
            {banner.weather && (
              <span className="font-body text-[12px] text-textsec block mt-1">{banner.weather}</span>
            )}
          </div>
        )}
      </div>

      {/* Messages */}
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
      >
        {/* Configured opening narration (drop-capped, not editable in chat) */}
        {hasFirstMessage && (
          <div className="max-w-[85%] mr-auto">
            <div className="px-4 py-3">
              <NarrationHtml
                className="chat-prose font-body text-text2 whitespace-pre-wrap first-narrator-dropcap"
                html={applyEntityChips(formatNarrationWithDropCap(firstMessage), chipEntities)}
              />
            </div>
          </div>
        )}

        {threadMessages.length === 0 && !isLoading && !hasFirstMessage && (
          <div className="flex items-center justify-center h-full">
            <p className="font-ui text-[10px] text-textdim tracking-wider text-center px-6">
              {!apiKeySet
                ? 'SET API KEY IN SETTINGS TO BEGIN'
                : planningMode
                  ? 'EDIT MODE — DESCRIBE WHAT TO BUILD OR CHANGE'
                  : 'BEGIN YOUR ADVENTURE'}
            </p>
          </div>
        )}

        {threadMessages.length === 0 && !isLoading && hasFirstMessage && !apiKeySet && (
          <p className="font-ui text-[10px] text-textdim tracking-wider px-4">
            SET API KEY IN SETTINGS TO BEGIN
          </p>
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
            onSwipeNew={m.role === 'assistant' && !busy ? () => swipe(m.turnNumber) : undefined}
            isLastAssistant={m.role === 'assistant' && m.turnNumber === lastTurn}
            onDelete={!busy && m.id > 0 ? () => setConfirmAction({ message: 'Delete this message and everything after it?', action: () => deleteMessageAndAfter(m.id) }) : undefined}
            isFirstNarrator={idx === firstNarratorIdx}
            pcName={pcName}
            pcPortrait={pcPortrait}
            partyMemberMap={partyMemberMap}
            chipEntities={chipEntities}
            catalogMap={catalogMap}
            resolveCharName={resolveCharName}
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
            <NarrationHtml
              className="chat-prose font-body text-text2 whitespace-pre-wrap"
              html={applyEntityChips(formatNarration(streamingContent), chipEntities)}
            />
          </div>
        )}

        {/* Generating indicator — narrator/planner avatar with animated dots */}
        {isLoading && !streamingContent && (
          <div className="flex items-start gap-3 mr-auto px-1 py-3">
            <div className="w-10 h-10 rounded-sm border border-gold bg-bg2 flex items-center justify-center flex-shrink-0">
              <span className="font-disp text-[16px] text-gold pt-[2px]">{planningMode ? 'P' : 'N'}</span>
            </div>
            <div className="pt-2">
              {planningMode ? (
                <span className="font-ui text-[10px] text-textdim tracking-wider">
                  THE EDITOR IS WORKING<span className="animate-pulse"> ···</span>
                </span>
              ) : (
                <ThinkingIndicator startedAt={thinkingStartedAt} isSummarizing={isSummarizing} />
              )}
            </div>
          </div>
        )}

        {/* Chronicler (world-building) indicator — runs after the narration */}
        {!isLoading && worldbuildRunning && (
          <div className="flex items-start gap-3 mr-auto px-1 py-3">
            <div className="w-10 h-10 rounded-sm border border-gold bg-bg2 flex items-center justify-center flex-shrink-0">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-gold">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
              </svg>
            </div>
            <div className="pt-2">
              <span className="font-ui text-[10px] text-textdim tracking-wider">
                THE CHRONICLER IS RECORDING
                <span className="animate-pulse"> ···</span>
              </span>
            </div>
          </div>
        )}

        {error && (
          <div className="mr-auto max-w-[85%] border border-danger-border bg-danger-bg rounded-md px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-danger">
                <circle cx="12" cy="12" r="10" /><path d="M12 8v4" /><path d="M12 16h.01" />
              </svg>
              <span className="font-ui text-[9px] tracking-wider uppercase text-danger">Generation Error</span>
            </div>
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{error}</p>
          </div>
        )}
      </div>

      {/* Context size bar (hidden in Planning mode — no narration context) */}
      {!planningMode && contextTokens !== null && maxContextTokens !== null && (
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
      <div className="border-t border-line2 p-3 bg-bg1">
        <div className="flex items-end gap-2">
          {/* Tools button + dropdown (opens above) */}
          <div className="relative shrink-0">
            {toolsOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setToolsOpen(false)} />
                <div className="absolute bottom-full left-0 mb-2 w-48 bg-bg2 border border-line2 rounded-md z-20 py-1">
                  <ToolMenuItem
                    label="Regenerate"
                    disabled={!showInputRegenerate || planningMode}
                    onClick={() => { setToolsOpen(false); regenerate() }}
                  />
                  <ToolMenuItem
                    label="Clear Chat"
                    disabled={messages.length === 0}
                    onClick={() => {
                      setToolsOpen(false)
                      setConfirmAction({ message: 'Clear the entire chat history? This cannot be undone.', action: clearHistory })
                    }}
                  />
                  <ToolMenuItem
                    label="View Prompt Log"
                    disabled={messages.length === 0}
                    onClick={() => { setToolsOpen(false); handleShowLog() }}
                  />
                </div>
              </>
            )}
            <button
              type="button"
              title="Tools"
              aria-label="Tools"
              className={`border px-2.5 py-2 transition-colors ${
                toolsOpen || planningMode ? 'border-gold text-gold' : 'border-line text-textsec hover:text-text hover:border-line2'
              }`}
              onClick={() => setToolsOpen((o) => !o)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2-2 2.7-2.7z" />
              </svg>
            </button>
          </div>

          <textarea
            ref={inputRef}
            className="flex-1 border border-line bg-bg0 px-3 py-2 text-sm font-body text-text outline-none focus:border-line2 transition-colors resize-none max-h-[160px] overflow-y-auto"
            rows={1}
            placeholder={!apiKeySet ? 'Set API key in Settings...' : planningMode ? 'Describe what to build or change…' : 'What do you do?'}
            value={input}
            disabled={!apiKeySet || busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
          />

          {isLoading ? (
            <button
              type="button"
              className="shrink-0 font-ui text-[10px] bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors"
              onClick={stopGeneration}
            >
              STOP
            </button>
          ) : (
            <button
              type="button"
              className="shrink-0 font-ui text-[10px] bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors disabled:opacity-40"
              disabled={!apiKeySet || !input.trim() || busy}
              onClick={handleSend}
            >
              SEND
            </button>
          )}
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
      {pendingDeletes.length > 0 && (
        <ConfirmDialog
          confirmLabel="DELETE"
          message={`The Editor wants to remove ${pendingDeletes.length} item(s): ${pendingDeletes.map((d) => d.label).join(', ')}. Delete them?`}
          onConfirm={() => applyPendingDeletes()}
          onCancel={() => dismissPendingDeletes()}
        />
      )}
    </div>
  )
}

// ── Time-of-day icon ────────────────────────────────────────────────

function TimeOfDayIcon({ timeOfDay }: { timeOfDay: string }) {
  const key = timeOfDay.trim().toLowerCase()
  const common = {
    width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  if (key === 'night') {
    return <svg {...common}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
  }
  if (key === 'morning') {
    return (
      <svg {...common}>
        <path d="M3 18h18M7 18a5 5 0 0 1 10 0" />
        <path d="M12 3v3M9.5 6.5 12 4l2.5 2.5" />
      </svg>
    )
  }
  if (key === 'evening') {
    return (
      <svg {...common}>
        <path d="M3 18h18M7 18a5 5 0 0 1 10 0" />
        <path d="M12 7V4M9.5 4.5 12 7l2.5-2.5" />
      </svg>
    )
  }
  if (key === 'afternoon') {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="3" />
        <path d="M7 17h8a3 3 0 0 0 .3-6 4.5 4.5 0 0 0-8.7-1.2A3.1 3.1 0 0 0 7 17z" />
      </svg>
    )
  }
  // day (and default): full sun
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  )
}

// ── Tools menu item ─────────────────────────────────────────────────

function ToolMenuItem({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="w-full text-left font-ui text-[10px] tracking-wider uppercase px-3 py-2 text-textsec hover:bg-bg3 hover:text-text transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-textsec disabled:cursor-not-allowed"
    >
      {label}
    </button>
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
      className={`w-10 h-10 rounded-sm border bg-bg2 flex items-center justify-center flex-shrink-0 overflow-hidden ${borderColor}`}
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
  onSwipeNew,
  isLastAssistant,
  onDelete,
  isFirstNarrator,
  pcName,
  pcPortrait,
  partyMemberMap,
  chipEntities,
  catalogMap,
  resolveCharName,
}: {
  message: ChatMessage
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  onSwipeNew?: () => void
  isLastAssistant?: boolean
  onDelete?: () => void
  isFirstNarrator?: boolean
  pcName: string
  pcPortrait: string
  partyMemberMap: Map<string, { id: string; basicInfo: { name: string; portrait?: string } }>
  chipEntities: ChipEntity[]
  catalogMap: Map<string, ItemCatalogEntry>
  resolveCharName: (id: string) => string
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
    // ── Player Character message (left-aligned, like the rest — no alternating) ──
    return (
      <div className="max-w-[85%] mr-auto group">
        <div className="flex items-start gap-3">
          {/* Portrait */}
          <Portrait
            src={pcPortrait}
            name={pcName}
            borderColor="border-blue"
          />

          <div className="flex-1 min-w-0">
            {/* Name header */}
            <div className="mb-1">
              <span className="font-disp text-[13px] text-blue pt-[2px]">
                {pcName} <span className="font-ui text-[9px] text-blue/60 tracking-wider">YOU</span>
              </span>
            </div>

            {/* Message content */}
            <div
              className="bg-bg2 border border-line rounded-md px-4 py-3 cursor-pointer"
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
                <NarrationHtml
                  className="chat-prose font-body text-text whitespace-pre-wrap"
                  html={applyEntityChips(formatNarration(message.content), chipEntities)}
                />
              )}
            </div>
          </div>
        </div>

        {/* Actions bar */}
        {!editing && (
          <div className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
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
                <NarrationHtml
                  className="chat-prose font-body text-text2 whitespace-pre-wrap"
                  html={applyEntityChips(formatNarration(message.content), chipEntities)}
                />
              )}
            </div>
          </div>
        </div>

        {/* Inventory / equipment change notices */}
        <ChangeNotices
          message={message}
          catalogMap={catalogMap}
          resolveCharName={resolveCharName}
        />

        {/* Actions bar */}
        <ActionsBar
          editing={editing}
          isUser={false}
          variantCount={variantCount}
          activeVariant={activeVariant}
          onSwipe={onSwipe}
          onSwipeNew={onSwipeNew}
          isLastAssistant={isLastAssistant}
          onDelete={onDelete}
        />
      </div>
    )
  }

  // ── Narrator / Planner message (default for assistant) ──
  const isPlanner = message.mode === 'planner'
  return (
    <div className="max-w-[85%] mr-auto group">
      {isPlanner && (
        <div className="flex items-center gap-1.5 px-4 pt-1">
          <span className="font-ui text-[9px] tracking-wider text-gold">⚙ EDITOR</span>
        </div>
      )}
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
          <NarrationHtml
            className={`chat-prose font-body text-text2 whitespace-pre-wrap ${
              isFirstNarrator ? 'first-narrator-dropcap' : ''
            }`}
            html={applyEntityChips(
              isFirstNarrator
                ? formatNarrationWithDropCap(message.content)
                : formatNarration(message.content),
              chipEntities,
            )}
          />
        )}
      </div>

      {/* Inventory / equipment change notices */}
      <ChangeNotices
        message={message}
        catalogMap={catalogMap}
        resolveCharName={resolveCharName}
      />

      {/* Actions bar */}
      <ActionsBar
        editing={editing}
        isUser={false}
        variantCount={variantCount}
        activeVariant={activeVariant}
        onSwipe={onSwipe}
        isLastAssistant={isLastAssistant}
        onDelete={onDelete}
      />
    </div>
  )
}

// ── Inventory / Equipment change notices ───────────────────────────

const SLOT_LABELS: Record<string, string> = {
  head: 'Head', neck: 'Neck', torsoOver: 'Torso (over)', torsoUnder: 'Torso (under)',
  leftHand: 'Left Hand', rightHand: 'Right Hand', waist: 'Waist',
  legsOver: 'Legs (over)', legsUnder: 'Legs (under)', feet: 'Feet',
  accessory1: 'Accessory', accessory2: 'Accessory',
}

function ChangeNotices({
  message,
  catalogMap,
  resolveCharName,
}: {
  message: ChatMessage
  catalogMap: Map<string, ItemCatalogEntry>
  resolveCharName: (id: string) => string
}) {
  const invDeltas = (message.appliedInventoryDeltas ?? []) as InventoryDelta[]
  const equipChanges = (message.appliedEquipmentChanges ?? []) as EquipmentChange[]

  if (invDeltas.length === 0 && equipChanges.length === 0) return null

  const itemName = (id: string | null) =>
    id ? (catalogMap.get(id)?.name ?? 'Unknown item') : 'nothing'

  return (
    <div className="px-4 mt-1 space-y-1.5">
      {invDeltas.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-ui text-xs text-textsec tracking-wider">Inventory</span>
          {invDeltas.map((d, i) => {
            const name = catalogMap.get(d.itemId)?.name ?? 'Unknown item'
            const positive = d.delta > 0
            const sign = positive ? '+' : '−' // − minus sign
            return (
              <span
                key={`${d.itemId}-${i}`}
                className="inline-flex items-center gap-1 text-sm"
              >
                <span className="text-gold2 bg-gold/10 px-1 rounded font-ui text-sm">
                  {name}
                </span>
                <span
                  className={`font-ui text-xs ${positive ? 'text-gold2' : 'text-danger'}`}
                >
                  {sign}{Math.abs(d.delta)}
                </span>
              </span>
            )
          })}
        </div>
      )}

      {equipChanges.length > 0 && (
        <div className="flex flex-col gap-1">
          {equipChanges.map((c, i) => (
            <div key={`${c.characterId}-${c.slot}-${i}`} className="flex items-center gap-2 flex-wrap text-sm">
              <span className="font-ui text-xs text-textsec tracking-wider">Equipment</span>
              <span className="font-disp text-[12px] text-gold pt-[2px]">
                {resolveCharName(c.characterId)}
              </span>
              <span className="font-ui text-[10px] text-textdim tracking-wider">
                {SLOT_LABELS[c.slot] ?? c.slot}
              </span>
              <span className="text-textdim line-through">{itemName(c.previousItemId)}</span>
              <span className="font-ui text-[10px] text-textdim">&#8594;</span>
              <span className="text-gold2 bg-gold/10 px-1 rounded font-ui text-sm">
                {itemName(c.newItemId)}
              </span>
            </div>
          ))}
        </div>
      )}
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
  onSwipeNew,
  isLastAssistant,
  onDelete,
}: {
  editing: boolean
  isUser: boolean
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  onSwipeNew?: () => void
  isLastAssistant?: boolean
  onDelete?: () => void
}) {
  if (editing) return null

  return (
    <div
      className="flex items-center gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
      style={(!isUser && (variantCount > 1 || isLastAssistant || onSwipeNew)) ? { opacity: 1 } : undefined}
    >
      {!isUser && (variantCount > 1 || onSwipeNew) && (
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
          {onSwipeNew && (
            <button
              type="button"
              className="font-ui text-[11px] text-textdim hover:text-gold ml-1"
              title="Generate new variant"
              onClick={onSwipeNew}
            >
              &#8635;
            </button>
          )}
        </>
      )}
      <div className="flex items-center gap-1 ml-auto">
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
import { ExpandIconButton, TextEditorModal } from '../common/ExpandableTextarea'

const EditArea = forwardRef<
  HTMLTextAreaElement,
  {
    value: string
    onChange: (v: string) => void
    onSave: () => void
    onCancel: () => void
  }
>(function EditArea({ value, onChange, onSave, onCancel }, ref) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="space-y-2">
      <div className="relative">
        <textarea
          ref={ref}
          title="Edit message"
          className="w-full text-sm font-body text-text bg-bg0 border border-line p-2 outline-none focus:border-line2 resize-y min-h-[48px]"
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
        <ExpandIconButton
          onClick={() => setExpanded(true)}
          className="absolute top-1 right-1"
        />
        {expanded && (
          <div onClick={(e) => e.stopPropagation()}>
            <TextEditorModal
              label="Edit Message"
              value={value}
              onChange={onChange}
              onClose={() => setExpanded(false)}
            />
          </div>
        )}
      </div>
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
      <div className="bg-bg1 border border-line2 rounded-lg w-[720px] max-w-[90vw] max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-line2">
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
              <pre className="text-[12px] font-body text-text leading-relaxed whitespace-pre-wrap bg-bg0 border border-line p-3 overflow-x-auto">
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

export type ChipEntity = { name: string; kind: 'item' | 'member'; id: string }

// Highlight important item and character names inline. Non-interactive — just a
// subtle gold emphasis so they stand out in the narration (no click-to-inspect).
function applyEntityChips(html: string, entities: ChipEntity[]): string {
  const byName = new Map(entities.filter((e) => e.name.trim()).map((e) => [e.name.toLowerCase(), e]))
  if (byName.size === 0) return html
  // Longer names first so multi-word names win over substrings.
  const names = [...byName.values()].map((e) => e.name).sort((a, b) => b.length - a.length)
  const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')
  return html.replace(/(<[^>]*>)|([^<]+)/g, (_, tag, text) => {
    if (tag) return tag
    return text.replace(re, (m: string) => {
      const e = byName.get(m.toLowerCase())
      if (!e) return m
      return `<span class="text-gold2 font-medium">${m}</span>`
    })
  })
}

// Renders narrator/chat HTML (entity names are highlighted but not interactive).
function NarrationHtml({ className, html }: { className: string; html: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />
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
