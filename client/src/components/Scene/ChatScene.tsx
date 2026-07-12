import { useRef, useEffect, useState, useCallback, useMemo, memo } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useWorldbuildStore } from '../../state/worldbuildStore'
import { useSettingsStore } from '../../state/settingsStore'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { useActionSuggestionsStore } from '../../state/actionSuggestionsStore'
import { useTtsStore } from '../../state/ttsStore'
import { useJournalStore } from '../../state/journalStore'
import { ItemCard } from '../ItemCard'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'
import { deriveSceneBanner } from '../../lib/location'
import { fetchBackdrops, pickBackdrop, type Backdrop } from '../../lib/backdrops'
import { weatherKind } from '../../lib/weather'
import { WeatherEffects } from './WeatherEffects'
import { useAppearanceStore } from '../../state/appearanceStore'
import { parseSegments, buildMemberResolver, type Segment, type MemberLite } from '../../lib/narration'
import type { ChatEvent, ChatMessage, ItemCatalogEntry, InventoryDelta, EquipmentChange } from '@shared/types/models'

interface PromptLogMessage {
  role: string
  content: string
}

export function ChatScene() {
  const messages = useChatStore((s) => s.messages)
  const isLoading = useChatStore((s) => s.isLoading)
  // NOTE: streamingContent/thinkingStartedAt/toolStatus/isSummarizing are
  // deliberately NOT subscribed here — only <StreamingWindow/> reads them, so
  // per-chunk SSE updates re-render that one small node, not the whole scene.
  const toolFailures = useChatStore((s) => s.toolFailures)
  const clearToolFailures = useChatStore((s) => s.clearToolFailures)
  const error = useChatStore((s) => s.error)
  const sendTurn = useChatStore((s) => s.sendTurn)
  const regenerate = useChatStore((s) => s.regenerate)
  const retryLastTurn = useChatStore((s) => s.retryLastTurn)
  const swipe = useChatStore((s) => s.swipe)
  const stopGeneration = useChatStore((s) => s.stopGeneration)
  const deleteMessageAndAfter = useChatStore((s) => s.deleteMessageAndAfter)
  const clearHistory = useChatStore((s) => s.clearHistory)
  const contextTokens = useChatStore((s) => s.contextTokens)
  const maxContextTokens = useChatStore((s) => s.maxContextTokens)
  const worldbuildRunning = useWorldbuildStore((s) => s.running)
  const worldbuildStartedAt = useWorldbuildStore((s) => s.runningStartedAt)
  // Destructive/turn-editing actions (swipe, regenerate, delete) wait for the
  // narrator AND the post-turn Chronicler; typing and sending only wait for
  // the narration itself — the Chronicler records in the background.
  const busy = isLoading || worldbuildRunning
  const inputLocked = isLoading
  const activeVariants = useChatStore((s) => s.activeVariants)
  const events = useChatStore((s) => s.events)
  const setActiveVariant = useChatStore((s) => s.setActiveVariant)
  const apiKeySet = useSettingsStore((s) => s.apiKeySet)
  const firstMessage = useNarratorStore((s) => s.firstMessage)
  const planningMode = useChatStore((s) => s.planningMode)
  const setPlanningMode = useChatStore((s) => s.setPlanningMode)
  const pendingDeletes = useChatStore((s) => s.pendingDeletes)
  const applyPendingDeletes = useChatStore((s) => s.applyPendingDeletes)
  const dismissPendingDeletes = useChatStore((s) => s.dismissPendingDeletes)
  const failedInput = useChatStore((s) => s.failedInput)
  const clearFailedInput = useChatStore((s) => s.clearFailedInput)
  const recapSummary = useJournalStore((s) => s.summary)
  const recapDismissed = useJournalStore((s) => s.bannerDismissed)
  const dismissRecap = useJournalStore((s) => s.dismissBanner)

  const playerCharacter = usePartyStore((s) => s.playerCharacter)
  const partyMembers = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const inventory = useItemsStore((s) => s.inventory)
  const actionSuggestionsEnabled = useNarratorStore((s) => s.actionSuggestionsEnabled)
  const actionOptionRules = useNarratorStore((s) => s.actionOptionRules)
  const firstMessageOptions = useNarratorStore((s) => s.firstMessageOptions)
  const actionSuggestions = useActionSuggestionsStore((s) => s.suggestions)
  const actionSuggestionsLoading = useActionSuggestionsStore((s) => s.loading)
  const actionSuggestionsTurn = useActionSuggestionsStore((s) => s.lastTurn)
  const runSuggestionsForTurn = useActionSuggestionsStore((s) => s.runForTurn)
  const rerollSuggestions = useActionSuggestionsStore((s) => s.regenerate)

  const [input, setInput] = useState('')
  const [itemPickerOpen, setItemPickerOpen] = useState(false)
  const [promptLog, setPromptLog] = useState<PromptLogMessage[] | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [regenNoteOpen, setRegenNoteOpen] = useState(false)
  const [regenNote, setRegenNote] = useState('')
  const [editTargetId, setEditTargetId] = useState<number | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [matchIdx, setMatchIdx] = useState(0)
  const [atBottom, setAtBottom] = useState(true)
  const [pendingImage, setPendingImage] = useState<string | null>(null)  // data URL, attached to the next send
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)

  // Downscale an attached image client-side (phones produce 10+ MB photos) to
  // a JPEG data URL capped at 1024px on the long edge.
  const handleImageFile = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const MAX = 1024
        const scale = Math.min(1, MAX / Math.max(img.width, img.height))
        const canvas = document.createElement('canvas')
        canvas.width = Math.round(img.width * scale)
        canvas.height = Math.round(img.height * scale)
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
        setPendingImage(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  }

  const submitRegenNote = () => {
    const note = regenNote.trim()
    setRegenNoteOpen(false)
    setRegenNote('')
    regenerate(note || undefined)
  }

  const scrollToBottom = () => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }

  const handleListScroll = () => {
    const el = listRef.current
    if (el) setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }

  // Sticky auto-scroll: follow new content only when already near the bottom, so
  // scrolling up to read isn't yanked back down mid-turn. (Streaming chunks are
  // followed by StreamingWindow's own effect.) rAF batches the scrollHeight
  // read/write after paint instead of forcing a sync reflow.
  useEffect(() => {
    if (!atBottom || !listRef.current) return
    const el = listRef.current
    const raf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
    return () => cancelAnimationFrame(raf)
  }, [messages, atBottom])

  // A failed send restores the typed text into the (now empty) input box so a
  // generation error never eats the player's prose.
  useEffect(() => {
    if (!failedInput) return
    setInput((cur) => (cur.trim() ? cur : failedInput))
    clearFailedInput()
  }, [failedInput, clearFailedInput])

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
    if ((!text && !pendingImage) || inputLocked) return
    setInput('')
    const image = pendingImage
    setPendingImage(null)
    setAtBottom(true) // snap to newest on send
    sendTurn(text || (image ? 'I show this.' : ''), image)
  }

  const handleShowLog = async () => {
    try {
      const log = await api.get<PromptLogMessage[]>('/chat/prompt-log')
      setPromptLog(log)
    } catch {
      setPromptLog([{ role: 'error', content: 'No prompt log available yet.' }])
    }
  }

  const handleExportTranscript = () => {
    const lines: string[] = ['# Wayward — Transcript', '']
    for (const m of visibleMessages) {
      if (m.role === 'user') lines.push(`**${pcName}:** ${m.content}`, '')
      else lines.push(m.content, '')
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `wayward-transcript-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Restrict to the active thread: narration vs the Planning conversation.
  // All list derivations are memoized so their identities are stable across
  // unrelated re-renders — that's what lets React.memo(MessageBubble) hold.
  const threadMode = planningMode ? 'planner' : 'narrator'
  const threadMessages = useMemo(
    () => messages.filter((m) => (m.mode ?? 'narrator') === threadMode),
    [messages, threadMode],
  )

  // Build the visible message list — one assistant message per turn (the active variant)
  const visibleMessages = useMemo(
    () => buildVisibleMessages(threadMessages, activeVariants),
    [threadMessages, activeVariants],
  )
  const lastTurn = Math.max(0, ...threadMessages.map((m) => m.turnNumber))

  // Get variant info for each turn
  const variantCounts = useMemo(() => getVariantCounts(threadMessages), [threadMessages])

  // Persistent in-chat toasts (Chronicler notices + player item actions), only
  // in the story thread. Group by their anchor turn so each renders right after
  // that turn's last visible message; toasts anchored to a turn with no visible
  // message (turn 0, or a turn later deleted) fall through to the bottom.
  const eventsByTurn = new Map<number, typeof events>()
  if (!planningMode) {
    for (const ev of events) {
      const list = eventsByTurn.get(ev.turnNumber) ?? []
      list.push(ev)
      eventsByTurn.set(ev.turnNumber, list)
    }
  }
  const visibleTurns = new Set(visibleMessages.map((m) => m.turnNumber))
  const orphanEvents = planningMode
    ? []
    : events.filter((ev) => !visibleTurns.has(ev.turnNumber))

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

  // The unified text-adventure action panel: numbered choice options (scripted
  // on the opening beat, AI-generated afterwards) + the fixed actions. Shown
  // whenever the player could act — idle after a narrator beat, or on a fresh
  // adventure showing only the First Message.
  const isOpening = !visibleMessages.some((m) => m.role === 'user')
  const panelOptions = isOpening
    ? (hasFirstMessage ? firstMessageOptions : [])
    : (actionSuggestionsEnabled ? actionSuggestions : [])
  const showActionPanel =
    !planningMode && !inputLocked && (showWhatDoYouDo || visibleMessages.length === 0)

  // Self-healing fetch: whenever the panel is visible mid-adventure and no
  // attempt has been made for the current chat state (boot, refresh, save/
  // campaign switches, aborted or failed turns), fetch the options. Loop-safe:
  // runForTurn stamps lastTurn immediately, so an empty result doesn't retrigger
  // — retrying an empty roll stays manual (↻ REROLL).
  useEffect(() => {
    if (!showActionPanel || isOpening || !actionSuggestionsEnabled || !apiKeySet) return
    if (actionSuggestionsLoading || actionSuggestionsTurn !== null) return
    const latestTurn = lastVisibleMsg?.turnNumber
    if (latestTurn && latestTurn > 0) void runSuggestionsForTurn(latestTurn)
  }, [showActionPanel, isOpening, actionSuggestionsEnabled, apiKeySet, actionSuggestionsLoading, actionSuggestionsTurn, lastVisibleMsg, runSuggestionsForTurn])
  const firstNarratorIdx = hasFirstMessage
    ? -1
    : visibleMessages.findIndex(
        (m) => m.role === 'assistant' && (m.speaker === 'narrator' || !m.speaker)
      )

  // Build a lookup for party member info by id
  const partyMemberMap = useMemo(
    () => new Map(partyMembers.map((pm) => [pm.id, pm])),
    [partyMembers],
  )

  // Name → in-party member resolver, for parsing party dialogue out of narration.
  const memberResolver = useMemo(() => buildMemberResolver(partyMembers), [partyMembers])

  // Per-message cinematic scene header: shown above a narrator message when its
  // declared location/time differs from the last one established (a scene change).
  const sceneHeaders = useMemo(() => computeSceneHeaders(visibleMessages), [visibleMessages])

  // PC info
  const pcName = playerCharacter?.basicInfo?.name || 'Player'
  const pcPortrait = playerCharacter?.portraitCrop || ''

  // Item and character names to highlight inline in the narration. Stable
  // identity also keys applyEntityChips' compiled-regex cache.
  const chipEntities: ChipEntity[] = useMemo(
    () =>
      [
        ...catalog.map((item) => ({ name: item.name, kind: 'item' as const, id: item.id })),
        ...partyMembers.map((m) => ({ name: m.basicInfo?.name || '', kind: 'member' as const, id: m.id })),
        ...(playerCharacter ? [{ name: pcName, kind: 'member' as const, id: playerCharacter.id }] : []),
      ].filter((e) => e.name.trim() && e.name !== 'Player'),
    [catalog, partyMembers, playerCharacter, pcName],
  )

  // Item id -> catalog entry, for resolving names in inventory/equipment notices
  const catalogMap = useMemo(() => new Map(catalog.map((item) => [item.id, item])), [catalog])

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

  // Backdrop art behind the messages — picked deterministically from the
  // declared scene (location + time of day), defaulting to forest_day.png.
  // The dark wash over it is --chat-overlay-opacity (Config → Appearance).
  const [backdrops, setBackdrops] = useState<Backdrop[]>([])
  useEffect(() => {
    let alive = true
    void fetchBackdrops().then((list) => { if (alive) setBackdrops(list) })
    return () => { alive = false }
  }, [])
  const backdrop = useMemo(
    () => (planningMode ? null : pickBackdrop(backdrops, banner.location, banner.timeOfDay)),
    [backdrops, planningMode, banner.location, banner.timeOfDay],
  )

  // Ambient weather over the backdrop, from the narrator-declared weather —
  // shown even when no backdrop art matches (the weather belongs to the scene,
  // not the art). `wayward.weatherOverride` in localStorage forces a kind
  // (debug/testing). Never in Edit Mode.
  const weatherFxOn = useAppearanceStore((s) => s.weatherFx)
  const weatherFx = useMemo(() => {
    if (planningMode || !weatherFxOn) return null
    const override = typeof localStorage !== 'undefined' ? localStorage.getItem('wayward.weatherOverride') : null
    return weatherKind(override || banner.weather)
  }, [planningMode, weatherFxOn, banner.weather])

  // Message search — ids of visible messages whose content matches the query.
  const q = searchQuery.trim().toLowerCase()
  const searchMatches = q
    ? visibleMessages.filter((m) => m.content.toLowerCase().includes(q)).map((m) => m.id)
    : []
  const currentMatchId = searchMatches[matchIdx] ?? null

  const jumpToMatch = (idx: number) => {
    if (searchMatches.length === 0) return
    const wrapped = (idx + searchMatches.length) % searchMatches.length
    setMatchIdx(wrapped)
    document.getElementById(`msg-${searchMatches[wrapped]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  // When the query changes, jump to the first match.
  useEffect(() => {
    setMatchIdx(0)
    if (q && searchMatches.length > 0) {
      document.getElementById(`msg-${searchMatches[0]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  // Keyboard shortcuts (ignored while typing in a field): ←/→ switch the active
  // variant of the last assistant turn; ↑ edits the last player message.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const el = document.activeElement as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const lastAssistant = [...visibleMessages].reverse().find((m) => m.role === 'assistant')
        if (!lastAssistant) return
        const turn = lastAssistant.turnNumber
        const count = variantCounts[turn] ?? 1
        if (count <= 1) return
        const cur = activeVariants[turn] ?? 0
        const next = e.key === 'ArrowLeft' ? Math.max(0, cur - 1) : Math.min(count - 1, cur + 1)
        if (next !== cur) { e.preventDefault(); setActiveVariant(turn, next) }
      } else if (e.key === 'ArrowUp') {
        const lastUser = [...visibleMessages].reverse().find((m) => m.role === 'user')
        if (lastUser && lastUser.id > 0) { e.preventDefault(); setEditTargetId(lastUser.id) }
      } else if (e.key >= '1' && e.key <= '9') {
        // Text-adventure style: number keys pick the matching panel option.
        const idx = Number(e.key) - 1
        if (showActionPanel && apiKeySet && idx < panelOptions.length) {
          e.preventDefault()
          sendTurn(panelOptions[idx])
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [visibleMessages, variantCounts, activeVariants, setActiveVariant, showActionPanel, apiKeySet, panelOptions, sendTurn])

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
            disabled={inputLocked}
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
          <h1 className="font-disp text-[22px] max-lg:text-[18px] leading-none text-gold pt-[3px] truncate">
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
      <div className="relative flex-1 min-h-0 flex flex-col">
        {/* Backdrop art + the semi-transparent dark wash over it. The message
            list below is `relative`, so it paints above these layers. */}
        {(backdrop || weatherFx) && (
          <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
            {backdrop && (
              <>
                <img src={backdrop.url} alt="" className="w-full h-full object-cover" />
                <div
                  className="absolute inset-0"
                  style={{ background: 'var(--chat-bg)', opacity: 'var(--chat-overlay-opacity, 0.85)' }}
                />
              </>
            )}
            {weatherFx && <WeatherEffects kind={weatherFx} />}
          </div>
        )}
        {searchOpen && (
          <SearchBar
            query={searchQuery}
            onQuery={setSearchQuery}
            count={searchMatches.length}
            index={matchIdx}
            onPrev={() => jumpToMatch(matchIdx - 1)}
            onNext={() => jumpToMatch(matchIdx + 1)}
            onClose={() => { setSearchOpen(false); setSearchQuery('') }}
          />
        )}
        <div
          ref={listRef}
          onScroll={handleListScroll}
          className="relative flex-1 overflow-y-auto p-4 max-lg:px-3 space-y-4"
        >
        {/* "Previously on…" — the story-so-far recap, once per adventure load */}
        {!planningMode && recapSummary && !recapDismissed && visibleMessages.length > 0 && (
          <div className="max-w-[85%] max-lg:max-w-full mr-auto border-l-2 border-gold/50 bg-bg2/60 rounded-r-md px-4 py-3">
            <div className="flex items-center justify-between gap-3 mb-1">
              <span className="font-disp text-[12px] tracking-[0.14em] text-gold uppercase pt-[2px]">
                Previously on your adventure
              </span>
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={dismissRecap}
              >
                DISMISS
              </button>
            </div>
            <p className="font-body text-sm text-text2 leading-relaxed italic whitespace-pre-wrap line-clamp-6">
              {recapSummary}
            </p>
          </div>
        )}

        {/* Configured opening narration (drop-capped, not editable in chat) */}
        {hasFirstMessage && (
          <div className="max-w-[85%] max-lg:max-w-full mr-auto">
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

        {visibleMessages.map((m, idx) => {
          const isLastOfTurn =
            idx === visibleMessages.length - 1 ||
            visibleMessages[idx + 1].turnNumber !== m.turnNumber
          const turnEvents = isLastOfTurn ? eventsByTurn.get(m.turnNumber) : undefined
          return (
          <div key={`${m.id}-${m.variant}`}>
          <div
            id={`msg-${m.id}`}
            className={currentMatchId === m.id ? 'rounded-md ring-2 ring-gold/60 ring-offset-2 ring-offset-bg0' : undefined}
          >
          <MessageBubble
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
            memberResolver={memberResolver}
            chipEntities={chipEntities}
            catalogMap={catalogMap}
            resolveCharName={resolveCharName}
            sceneHeader={sceneHeaders[idx]}
            editTargetId={editTargetId}
            onEditOpened={() => setEditTargetId(null)}
          />
          </div>
          {turnEvents && turnEvents.map((ev) => <EventToast key={ev.id} event={ev} />)}
          </div>
          )
        })}

        {orphanEvents.map((ev) => <EventToast key={ev.id} event={ev} />)}

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

        {/* Live streaming text + thinking indicator — its own component so
            per-chunk store updates re-render only this node. */}
        <StreamingWindow
          planningMode={planningMode}
          memberResolver={memberResolver}
          chipEntities={chipEntities}
          listRef={listRef}
          atBottom={atBottom}
        />

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
                THE CHRONICLER IS RECORDING<Elapsed startedAt={worldbuildStartedAt} />
                <span className="animate-pulse"> ···</span>
              </span>
            </div>
          </div>
        )}

        {/* Graceful tool-failure notices — a bad tool call (missing item, empty
            slot, …) is surfaced here instead of silently corrupting state. */}
        {!busy && toolFailures.length > 0 && (
          <button
            type="button"
            onClick={clearToolFailures}
            className="mr-auto max-w-[85%] max-lg:max-w-full text-left flex flex-col gap-1 border border-line rounded-md bg-bg2/40 px-3 py-2 hover:border-line2 transition-colors"
            title="Dismiss"
          >
            {toolFailures.map((f, i) => (
              <span key={i} className="font-body text-[12px] text-textdim italic leading-relaxed">
                ({f})
              </span>
            ))}
          </button>
        )}

        {/* The action panel — the primary text-adventure interaction. Numbered
            choice options (scripted on the opening beat, AI-generated after
            each narrator beat) over the always-available fixed actions. */}
        {showActionPanel && (
          <div className="mr-auto w-full max-w-[85%] max-lg:max-w-full flex flex-col gap-1.5 pl-1 pt-1">
            {!isOpening && actionSuggestionsEnabled && actionSuggestionsLoading && (
              <span className="font-ui text-[10px] tracking-wider text-textdim animate-pulse px-1 py-1">
                WEIGHING YOUR OPTIONS ···
              </span>
            )}
            {!isOpening && actionSuggestionsEnabled && !actionSuggestionsLoading &&
              panelOptions.length === 0 && actionSuggestionsTurn !== null && (
              <span className="font-ui text-[10px] tracking-wider text-textdim px-1 py-1">
                NO OPTIONS CAME THROUGH — ↻ REROLL TO TRY AGAIN
              </span>
            )}
            {!actionSuggestionsLoading && panelOptions.map((s, i) => (
              <button
                key={`${i}-${s}`}
                type="button"
                disabled={inputLocked || !apiKeySet}
                onClick={() => sendTurn(s)}
                title={!isOpening ? actionOptionRules[i] : undefined}
                className="group text-left font-body text-sm text-text2 border border-line rounded-md bg-bg2/40 px-3.5 py-2 hover:border-gold hover:text-text hover:bg-gold/5 transition-colors disabled:opacity-40"
              >
                <span className="text-golddeep group-hover:text-gold mr-2 font-ui text-[12px]">{i + 1}.</span>{s}
              </button>
            ))}

            {/* Fixed actions — always available, part of the same panel */}
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
              <QuickActionButton
                label="Continue"
                disabled={inputLocked || !apiKeySet}
                onClick={() => sendTurn('I wait and let the scene unfold.')}
              />
              <QuickActionButton
                label="Look Around"
                disabled={inputLocked || !apiKeySet}
                onClick={() => sendTurn('I look around carefully.')}
              />
              <QuickActionButton
                label="Talk to Party"
                disabled={inputLocked || !apiKeySet}
                onClick={() => sendTurn('I turn to talk to my party.')}
              />
              <QuickActionButton
                label="Rest"
                disabled={inputLocked || !apiKeySet}
                onClick={() => sendTurn('I take a moment to rest.')}
              />
              <div className="relative flex">
                <QuickActionButton
                  label="Use an Item"
                  disabled={inputLocked || !apiKeySet || inventory.length === 0}
                  onClick={() => setItemPickerOpen((o) => !o)}
                />
                {itemPickerOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setItemPickerOpen(false)} />
                    <div className="absolute bottom-full left-0 mb-2 w-64 max-h-72 overflow-y-auto bg-bg2 border border-line2 rounded-md z-20 p-1.5 space-y-1">
                      {inventory.length === 0 ? (
                        <p className="text-[11px] text-textdim font-body px-2 py-1.5">No items.</p>
                      ) : (
                        inventory.map((stack) => stack.item ? (
                          <ItemCard
                            key={stack.itemId}
                            item={stack.item}
                            selected={false}
                            count={stack.count}
                            onClick={() => {
                              setItemPickerOpen(false)
                              sendTurn(`I use the ${stack.item!.name}.`)
                            }}
                          />
                        ) : null)
                      )}
                    </div>
                  </>
                )}
              </div>
              {!isOpening && actionSuggestionsEnabled && (
                <button
                  type="button"
                  title="Reroll the generated options"
                  disabled={inputLocked || !apiKeySet || actionSuggestionsLoading}
                  onClick={() => void rerollSuggestions()}
                  className="font-ui text-[10px] tracking-wider text-textdim border border-line rounded-sm px-2 py-1 hover:text-gold hover:border-gold/50 transition-colors disabled:opacity-40"
                >
                  ↻ REROLL
                </button>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="mr-auto max-w-[85%] max-lg:max-w-full border border-danger-border bg-danger-bg rounded-md px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-danger">
                <circle cx="12" cy="12" r="10" /><path d="M12 8v4" /><path d="M12 16h.01" />
              </svg>
              <span className="font-ui text-[9px] tracking-wider uppercase text-danger">Generation Error</span>
            </div>
            <p className="font-body text-sm text-text2 leading-relaxed whitespace-pre-wrap">{error}</p>
            {!planningMode && !busy && messages.length > 0 && (
              <button
                type="button"
                className="mt-2 font-ui text-[10px] tracking-wider text-gold border border-gold/40 px-3 py-1 rounded-sm hover:bg-gold/10 transition-colors"
                onClick={() => retryLastTurn()}
              >
                RETRY
              </button>
            )}
          </div>
        )}
        </div>
        {!atBottom && visibleMessages.length > 0 && (
          <button
            type="button"
            aria-label="Scroll to latest"
            className="absolute bottom-3 right-4 z-10 w-8 h-8 rounded-full border border-line2 bg-bg2 text-gold flex items-center justify-center shadow-lg hover:bg-bg3 transition-colors"
            onClick={scrollToBottom}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12l7 7 7-7" /></svg>
          </button>
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

      {/* Regenerate-with-note panel — steers a single re-roll, not persisted. */}
      {regenNoteOpen && (
        <div className="border-t border-line2 px-3 pt-2.5 pb-1 bg-bg1 flex items-center gap-2">
          <span className="font-ui text-[9px] tracking-wider text-gold uppercase shrink-0">Steer re-roll</span>
          <input
            autoFocus
            className="flex-1 border border-line bg-bg0 px-2.5 py-1.5 text-sm font-body text-text outline-none focus:border-line2 transition-colors"
            placeholder="e.g. shorter and tenser; keep Tifa quiet"
            value={regenNote}
            onChange={(e) => setRegenNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); submitRegenNote() }
              else if (e.key === 'Escape') { setRegenNoteOpen(false); setRegenNote('') }
            }}
          />
          <button
            type="button"
            className="shrink-0 font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-3 py-1.5 hover:bg-gold transition-colors"
            onClick={submitRegenNote}
          >
            REGENERATE
          </button>
          <button
            type="button"
            className="shrink-0 font-ui text-[10px] tracking-wider text-textdim border border-line px-3 py-1.5 hover:text-text hover:border-line2 transition-colors"
            onClick={() => { setRegenNoteOpen(false); setRegenNote('') }}
          >
            CANCEL
          </button>
        </div>
      )}

      {/* Input — the freeform escape hatch under the action panel */}
      <div className="border-t border-line2 p-3 bg-bg1">
        {!planningMode && (
          <span className="block font-ui text-[10px] tracking-wider text-textdim mb-1.5">
            OR DO SOMETHING ELSE:
          </span>
        )}
        {/* Pending image preview — attached to the next message */}
        {pendingImage && (
          <div className="flex items-center gap-2 mb-2">
            <img src={pendingImage} alt="Attached" className="h-14 w-14 object-cover rounded-md border border-line2" />
            <span className="font-ui text-[10px] text-textdim tracking-wider">IMAGE ATTACHED</span>
            <button
              type="button"
              className="font-ui text-[10px] text-textdim border border-line px-2 py-1 hover:text-text hover:border-line2 transition-colors"
              onClick={() => setPendingImage(null)}
            >
              REMOVE
            </button>
          </div>
        )}
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
                    label="Regenerate with Note…"
                    disabled={!showInputRegenerate || planningMode}
                    onClick={() => { setToolsOpen(false); setRegenNote(''); setRegenNoteOpen(true) }}
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
                    label="Search Messages…"
                    disabled={visibleMessages.length === 0}
                    onClick={() => { setToolsOpen(false); setSearchOpen(true) }}
                  />
                  <ToolMenuItem
                    label="Export Transcript"
                    disabled={visibleMessages.length === 0}
                    onClick={() => { setToolsOpen(false); handleExportTranscript() }}
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

          {/* Attach image (described to the Narrator/Editor by the vision agent) */}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            title="Attach an image"
            aria-label="Attach an image"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleImageFile(f)
              e.target.value = ''  // allow re-picking the same file
            }}
          />
          <button
            type="button"
            title="Attach an image"
            aria-label="Attach an image"
            disabled={!apiKeySet || inputLocked}
            className={`shrink-0 border px-2.5 py-2 transition-colors disabled:opacity-40 ${
              pendingImage ? 'border-gold text-gold' : 'border-line text-textsec hover:text-text hover:border-line2'
            }`}
            onClick={() => imageInputRef.current?.click()}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="m21 15-5-5L5 21" />
            </svg>
          </button>

          <textarea
            ref={inputRef}
            className="flex-1 border border-line bg-bg0 px-3 py-2 text-sm font-body text-text outline-none focus:border-line2 transition-colors resize-none max-h-[160px] overflow-y-auto"
            rows={1}
            placeholder={!apiKeySet ? 'Set API key in Settings...' : planningMode ? 'Describe what to build or change…' : 'Type your own action…'}
            value={input}
            disabled={!apiKeySet || inputLocked}
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
              disabled={!apiKeySet || (!input.trim() && !pendingImage) || inputLocked}
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

// ── Quick action button ──────────────────────────────────────────────

function QuickActionButton({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="font-ui text-[9px] uppercase tracking-wider border border-line2 text-textsec px-2.5 py-1 max-lg:py-2 max-lg:px-3 hover:text-text hover:border-gold transition-colors disabled:opacity-40 disabled:hover:text-textsec disabled:hover:border-line2"
    >
      {label}
    </button>
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

// ── Message search bar ──────────────────────────────────────────────

function SearchBar({
  query, onQuery, count, index, onPrev, onNext, onClose,
}: {
  query: string
  onQuery: (v: string) => void
  count: number
  index: number
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  return (
    <div className="shrink-0 border-b border-line2 bg-bg2 px-3 py-2 flex items-center gap-2">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-textdim shrink-0">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
      </svg>
      <input
        autoFocus
        className="flex-1 bg-transparent text-sm font-body text-text outline-none placeholder:text-textdim"
        placeholder="Search messages…"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); e.shiftKey ? onPrev() : onNext() }
          else if (e.key === 'Escape') onClose()
        }}
      />
      <span className="font-ui text-[9px] text-textdim tracking-wider shrink-0 tabular-nums">
        {query.trim() ? `${count > 0 ? index + 1 : 0}/${count}` : ''}
      </span>
      <button type="button" className="text-textdim hover:text-text disabled:opacity-30" disabled={count === 0} onClick={onPrev} aria-label="Previous match">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m18 15-6-6-6 6" /></svg>
      </button>
      <button type="button" className="text-textdim hover:text-text disabled:opacity-30" disabled={count === 0} onClick={onNext} aria-label="Next match">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      <button type="button" className="font-ui text-[10px] text-textdim hover:text-text tracking-wider shrink-0" onClick={onClose} aria-label="Close search">
        ✕
      </button>
    </div>
  )
}

// ── Portrait Component ──────────────────────────────────────────────

// Shared chat portrait size — PC bubble and party dialogue blocks match.
const CHAT_PORTRAIT_SIZE = 'w-16 h-20'

function Portrait({
  src,
  name,
  borderColor,
  className = 'w-12 h-16',
}: {
  src?: string
  name: string
  borderColor: string
  className?: string
}) {
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div
      className={`rounded-sm border bg-bg2 flex items-center justify-center flex-shrink-0 overflow-hidden ${className} ${borderColor}`}
    >
      {src ? (
        <img
          src={src.startsWith('/') || src.startsWith('http') ? src : `/portraits/${src}`}
          alt={name}
          loading="lazy"
          decoding="async"
          className="w-full h-full object-cover object-top"
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

// Equality for React.memo: shallow-compare everything except the callback
// props — they're fresh closures every parent render, but everything they
// capture that affects output (variant counts, busy, ids) arrives via the
// other, compared props. This is what stops streaming chunks / unrelated store
// updates from re-rendering (and re-parsing) the whole message history.
function bubblePropsEqual(prev: Record<string, unknown>, next: Record<string, unknown>): boolean {
  for (const k of Object.keys(next)) {
    const a = prev[k]
    const b = next[k]
    if (typeof a === 'function' && typeof b === 'function') continue
    if (a !== b) return false
  }
  return true
}

const MessageBubble = memo(function MessageBubble({
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
  memberResolver,
  chipEntities,
  catalogMap,
  resolveCharName,
  sceneHeader,
  editTargetId,
  onEditOpened,
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
  partyMemberMap: Map<string, { id: string; basicInfo: { name: string }; portraitCrop?: string | null }>
  memberResolver: Map<string, MemberLite>
  chipEntities: ChipEntity[]
  catalogMap: Map<string, ItemCatalogEntry>
  resolveCharName: (id: string) => string
  sceneHeader?: { location?: string | null; timeOfDay?: string | null }
  editTargetId?: number | null
  onEditOpened?: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(message.content)
  const editMessage = useChatStore((s) => s.editMessage)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // TTS replay: only offered on persisted narrator messages when the server
  // has the engine installed and TTS is enabled in Settings.
  const ttsReady = useTtsStore((s) => !!s.status?.installed) && useSettingsStore((s) => s.ttsEnabled)
  const speakingThis = useTtsStore((s) => s.playing?.messageId === message.id)
  const speakMessage = useTtsStore((s) => s.speakMessage)
  const stopSpeaking = useTtsStore((s) => s.stop)

  // Editor/Planner prose is rendered plainly; only narration gets JRPG segments.
  // Parsed once per (content, resolver) — not on every render of the list.
  const isPlanner = message.mode === 'planner'
  const segments = useMemo<Segment[]>(
    () =>
      isPlanner
        ? [{ type: 'narration', text: message.content }]
        : parseSegments(message.content, memberResolver),
    [isPlanner, message.content, memberResolver],
  )

  useEffect(() => {
    setEditText(message.content)
  }, [message.content])

  // Open the editor when a keyboard shortcut targets this message.
  useEffect(() => {
    if (editTargetId === message.id && message.id > 0 && !editing) {
      setEditing(true)
      onEditOpened?.()
    }
  }, [editTargetId, message.id, editing, onEditOpened])

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
      <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
        {/* Player line — styled like a party dialogue block, with a blue accent.
            The px-4 py-3 matches the narrator message so the portrait lines up
            with the party dialogue blocks rendered inside it. */}
        <div className="flex items-stretch gap-3 px-4 py-3">
          {/* Portrait */}
          <Portrait
            src={pcPortrait}
            name={pcName}
            borderColor="border-blue"
            className={CHAT_PORTRAIT_SIZE}
          />

          <div className="flex-1 min-w-0 flex flex-col">
            {/* Name plate */}
            <span className="font-disp text-[14px] text-blue pt-[2px] mb-1">
              {pcName} <span className="font-ui text-[9px] text-blue/60 tracking-wider">YOU</span>
            </span>

            {/* Message content */}
            <div className="flex-1 border-l-2 border-blue/60 bg-blue/5 rounded-r-md px-4 py-3">
              {/* Player-attached image (described to the narrator by the vision agent) */}
              {message.imageUrl && (
                <img
                  src={message.imageUrl}
                  alt={message.imageDescription || 'Attached image'}
                  title={message.imageDescription || undefined}
                  className="max-h-64 max-w-full rounded-md border border-line2 mb-2"
                />
              )}
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
            {message.id > 0 && (
              <button
                type="button"
                className="font-ui text-[9px] text-textdim hover:text-text"
                onClick={() => setEditing(true)}
              >
                EDIT
              </button>
            )}
            <CopyButton text={message.content} />
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
    const pmPortrait = partyMember.portraitCrop || ''

    return (
      <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
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
            <div className="px-4 py-3">
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
          onEdit={message.id > 0 ? () => setEditing(true) : undefined}
          copyText={message.content}
        />
      </div>
    )
  }

  // ── Narrator / Planner message (default for assistant) ──
  return (
    <div className="max-w-[85%] max-lg:max-w-full mr-auto group">
      {isPlanner && (
        <div className="flex items-center gap-1.5 px-4 pt-1">
          <span className="font-ui text-[9px] tracking-wider text-gold">⚙ EDITOR</span>
        </div>
      )}
      {sceneHeader && (sceneHeader.location || sceneHeader.timeOfDay) && (
        <SceneHeader location={sceneHeader.location} timeOfDay={sceneHeader.timeOfDay} />
      )}
      <div className="px-4 py-3">
        {editing ? (
          <EditArea
            ref={textareaRef}
            value={editText}
            onChange={setEditText}
            onSave={handleSaveEdit}
            onCancel={() => { setEditText(message.content); setEditing(false) }}
          />
        ) : (
          <SegmentedNarration
            segments={segments}
            chipEntities={chipEntities}
            dropCap={isFirstNarrator}
            messageId={message.id}
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
        onEdit={message.id > 0 ? () => setEditing(true) : undefined}
        copyText={message.content}
        onSpeak={
          ttsReady && !isPlanner && message.id > 0
            ? () => (speakingThis ? stopSpeaking() : void speakMessage(message))
            : undefined
        }
        speaking={speakingThis}
      />
    </div>
  )
}, bubblePropsEqual)

// ── Persistent in-chat toasts (Chronicler notices + player item actions) ────

function EventToast({ event }: { event: ChatEvent }) {
  const isChronicler = event.kind === 'chronicler'

  // Dice chip — a server-rolled skill check; success glows gold, failure danger.
  if (event.kind === 'dice') {
    const failed = /Failure$/i.test(event.text)
    return (
      <div className="mr-auto max-w-[85%] max-lg:max-w-full flex items-start gap-2 px-3 py-1.5">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={`mt-[1px] flex-shrink-0 ${failed ? 'text-danger' : 'text-gold'}`}>
          <path d="M12 2 3 7v10l9 5 9-5V7l-9-5z" />
          <path d="M12 22V12" /><path d="M3 7l9 5 9-5" />
        </svg>
        <span className={`font-ui text-[10px] leading-relaxed tracking-wide ${failed ? 'text-danger/90' : 'text-gold/90'}`}>
          {event.text}
        </span>
      </div>
    )
  }

  return (
    <div className="mr-auto max-w-[85%] max-lg:max-w-full flex items-start gap-2 px-3 py-1.5">
      {isChronicler ? (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-gold/70 mt-[2px] flex-shrink-0">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-textsec mt-[2px] flex-shrink-0">
          <path d="M20 7h-9M14 17H5M17 3v8M7 13v8" /><circle cx="17" cy="14" r="3" /><circle cx="7" cy="10" r="3" />
        </svg>
      )}
      <span className="font-ui text-[10px] text-textdim leading-relaxed">
        {isChronicler && <span className="text-gold/70 tracking-wider">CHRONICLER · </span>}
        {event.text}
      </span>
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
  const inventory = useItemsStore((s) => s.inventory)

  if (invDeltas.length === 0 && equipChanges.length === 0) return null

  // Equipment-change ids are item INSTANCE ids — resolve via the instance list,
  // falling back to the catalog (for inventory deltas, which carry catalog ids).
  const itemName = (id: string | null) => {
    if (!id) return 'nothing'
    const inst = inventory.find((s) => s.instanceId === id)
    return inst?.item?.name ?? catalogMap.get(id)?.name ?? 'an item'
  }

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
  onEdit,
  copyText,
  onSpeak,
  speaking,
}: {
  editing: boolean
  isUser: boolean
  variantCount: number
  activeVariant: number
  onSwipe?: (dir: 'left' | 'right') => void
  onSwipeNew?: () => void
  isLastAssistant?: boolean
  onDelete?: () => void
  onEdit?: () => void
  copyText?: string
  onSpeak?: () => void
  speaking?: boolean
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
      <div className="flex items-center gap-2 ml-auto">
        {onSpeak && (
          <button
            type="button"
            className={`font-ui text-[9px] ${speaking ? 'text-gold' : 'text-textdim hover:text-text'}`}
            title={speaking ? 'Stop speaking' : 'Read this message aloud'}
            onClick={onSpeak}
          >
            {speaking ? '■ STOP' : '♪ SPEAK'}
          </button>
        )}
        {onEdit && (
          <button
            type="button"
            className="font-ui text-[9px] text-textdim hover:text-text"
            onClick={onEdit}
          >
            EDIT
          </button>
        )}
        {copyText && <CopyButton text={copyText} />}
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

// Copy a message's text to the clipboard, with a brief "COPIED" confirmation.
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="font-ui text-[9px] text-textdim hover:text-text"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        } catch { /* clipboard unavailable */ }
      }}
    >
      {copied ? 'COPIED' : 'COPY'}
    </button>
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

// For each visible message, decide whether to show a cinematic scene header
// above it — i.e. when a narrator message establishes a location/time that
// differs from the one currently in effect (a scene change). Returns an array
// parallel to `visibleMessages`.
function computeSceneHeaders(
  visibleMessages: ChatMessage[],
): ({ location?: string | null; timeOfDay?: string | null } | undefined)[] {
  let lastLoc: string | null = null
  let lastTod: string | null = null
  return visibleMessages.map((m) => {
    const isNarrator = m.role === 'assistant' && (m.mode ?? 'narrator') !== 'planner'
    if (!isNarrator) return undefined
    const loc = m.location ?? null
    const tod = m.timeOfDay ?? null
    const changed = (loc && loc !== lastLoc) || (tod && tod !== lastTod)
    if (loc) lastLoc = loc
    if (tod) lastTod = tod
    if (!changed) return undefined
    return { location: lastLoc, timeOfDay: lastTod }
  })
}

// A live "Ns" elapsed counter. Counts from `startedAt` if given, else from the
// moment it mounts (used for the Chronicler, which has no shared start time).
function Elapsed({ startedAt }: { startedAt: number | null }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const start = startedAt ?? Date.now()
    const tick = () => setSecs(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [startedAt])
  return <>{secs > 0 ? ` ${secs}s` : ''}</>
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

// Sole subscriber to the per-chunk streaming state (streamingContent, tool
// status, thinking timer). SSE chunks arrive many times per second; keeping
// those subscriptions out of ChatScene means each chunk re-renders only this
// node instead of the entire message history.
function StreamingWindow({
  planningMode,
  memberResolver,
  chipEntities,
  listRef,
  atBottom,
}: {
  planningMode: boolean
  memberResolver: Map<string, MemberLite>
  chipEntities: ChipEntity[]
  listRef: React.RefObject<HTMLDivElement | null>
  atBottom: boolean
}) {
  const isLoading = useChatStore((s) => s.isLoading)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const thinkingStartedAt = useChatStore((s) => s.thinkingStartedAt)
  const toolStatus = useChatStore((s) => s.toolStatus)
  const isSummarizing = useChatStore((s) => s.isSummarizing)

  // Follow the stream while the user is pinned to the bottom (rAF-batched so
  // we never force a sync reflow per chunk).
  useEffect(() => {
    if (!atBottom || !streamingContent || !listRef.current) return
    const el = listRef.current
    const raf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
    return () => cancelAnimationFrame(raf)
  }, [streamingContent, atBottom, listRef])

  const segments = useMemo<Segment[]>(
    () =>
      planningMode
        ? [{ type: 'narration', text: streamingContent }]
        : parseSegments(streamingContent, memberResolver),
    [planningMode, streamingContent, memberResolver],
  )

  if (!isLoading) return null

  // Streaming response — routed through the segmenter so dialogue boxes,
  // dividers, etc. form live as text streams.
  if (streamingContent) {
    return (
      <div className="max-w-[85%] max-lg:max-w-full mr-auto px-4 py-3">
        <SegmentedNarration segments={segments} chipEntities={chipEntities} />
      </div>
    )
  }

  // Generating indicator — narrator/planner avatar with animated dots.
  return (
    <div className="flex items-start gap-3 mr-auto px-1 py-3">
      <div className="w-10 h-10 rounded-sm border border-gold bg-bg2 flex items-center justify-center flex-shrink-0">
        <span className="font-disp text-[16px] text-gold pt-[2px]">{planningMode ? 'P' : 'N'}</span>
      </div>
      <div className="pt-2">
        {toolStatus ? (
          <span className="font-ui text-[10px] text-gold/80 tracking-wider">
            {toolStatus.toUpperCase()}<Elapsed startedAt={thinkingStartedAt} /><span className="animate-pulse"> ···</span>
          </span>
        ) : planningMode ? (
          <span className="font-ui text-[10px] text-textdim tracking-wider">
            THE EDITOR IS WORKING<Elapsed startedAt={thinkingStartedAt} /><span className="animate-pulse"> ···</span>
          </span>
        ) : (
          <ThinkingIndicator startedAt={thinkingStartedAt} isSummarizing={isSummarizing} />
        )}
      </div>
    </div>
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
    // Bold first so it consumes ** pairs; remaining single * pairs are italics.
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em class="italic">$1</em>')
    .replace(/\n/g, '<br/>')
}

export type ChipEntity = { name: string; kind: 'item' | 'member'; id: string }

// The compiled name-matcher is cached per entity ARRAY IDENTITY — chipEntities
// is useMemo'd in ChatScene, so the (expensive) escape+compile happens once per
// catalog/party change instead of once per segment per message per render.
const _chipMatcherCache = new WeakMap<ChipEntity[], { byName: Map<string, ChipEntity>; re: RegExp | null }>()

function _chipMatcher(entities: ChipEntity[]) {
  let m = _chipMatcherCache.get(entities)
  if (m) return m
  const byName = new Map(entities.filter((e) => e.name.trim()).map((e) => [e.name.toLowerCase(), e]))
  let re: RegExp | null = null
  if (byName.size > 0) {
    // Longer names first so multi-word names win over substrings.
    const names = [...byName.values()].map((e) => e.name).sort((a, b) => b.length - a.length)
    const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    re = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')
  }
  m = { byName, re }
  _chipMatcherCache.set(entities, m)
  return m
}

// Highlight important item and character names inline. Non-interactive — just a
// subtle gold emphasis so they stand out in the narration (no click-to-inspect).
function applyEntityChips(html: string, entities: ChipEntity[]): string {
  const { byName, re } = _chipMatcher(entities)
  if (!re) return html
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

// ── Segmented narration: JRPG dialogue blocks, inscriptions, dividers ──────

const TIME_ICONS: Record<string, string> = {
  morning: '🌅', day: '☀️', afternoon: '🌤️', evening: '🌇', night: '🌙',
}

// A small cinematic header shown above a narrator message when the scene changes.
function SceneHeader({ location, timeOfDay }: { location?: string | null; timeOfDay?: string | null }) {
  const icon = timeOfDay ? TIME_ICONS[timeOfDay.toLowerCase()] : ''
  const parts = [location, timeOfDay].filter(Boolean) as string[]
  return (
    <div className="flex items-center gap-2 px-4 pt-2 pb-1">
      <div className="h-px flex-1 bg-gradient-to-r from-transparent to-line2" />
      <span className="font-disp text-[11px] tracking-[0.18em] text-gold uppercase pt-[2px] whitespace-nowrap">
        {icon && <span className="mr-1">{icon}</span>}
        {parts.join(' · ')}
      </span>
      <div className="h-px flex-1 bg-gradient-to-l from-transparent to-line2" />
    </div>
  )
}

// Renders an ordered list of parsed segments. The drop-cap (when requested) is
// applied to the first narration segment only. When `messageId` is given, the
// segment currently being read aloud gets a soft gold wash.
function SegmentedNarration({
  segments,
  chipEntities,
  dropCap = false,
  messageId,
}: {
  segments: Segment[]
  chipEntities: ChipEntity[]
  dropCap?: boolean
  messageId?: number
}) {
  const firstNarrationIdx = dropCap ? segments.findIndex((s) => s.type === 'narration') : -1
  const speakingIdx = useTtsStore((s) =>
    messageId !== undefined && s.playing?.messageId === messageId ? s.playing.segmentIndex : null,
  )

  return (
    <div className="space-y-3">
      {segments.map((seg, i) => {
        const speaking = i === speakingIdx
        const speakingWash = speaking ? ' bg-gold/5 rounded-sm' : ''
        if (seg.type === 'divider') {
          return (
            <div key={i} className="flex items-center gap-3 py-1">
              <div className="flex-1 border-t border-line" />
              <span className="font-disp text-[12px] text-golddeep">❖</span>
              <div className="flex-1 border-t border-line" />
            </div>
          )
        }
        if (seg.type === 'blockquote') {
          return (
            <NarrationHtml
              key={i}
              className={`chat-prose font-body text-text2 italic border-l-2 border-gold/50 bg-bg2/60 rounded-r-md px-4 py-2 whitespace-pre-wrap${speaking ? ' border-gold' : ''}`}
              html={applyEntityChips(formatNarration(seg.text), chipEntities)}
            />
          )
        }
        if (seg.type === 'dialogue') {
          return <DialogueBlock key={i} member={seg.member} text={seg.text} chipEntities={chipEntities} speaking={speaking} />
        }
        // narration
        const useDropCap = i === firstNarrationIdx
        return (
          <NarrationHtml
            key={i}
            className={`chat-prose font-body text-text2 whitespace-pre-wrap ${useDropCap ? 'first-narrator-dropcap' : ''}${speakingWash}`}
            html={applyEntityChips(
              useDropCap ? formatNarrationWithDropCap(seg.text) : formatNarration(seg.text),
              chipEntities,
            )}
          />
        )
      })}
    </div>
  )
}

// JRPG dialogue block — rectangular portrait + gold name plate header over a
// full-width tinted dialogue box. Only rendered for in-party members.
function DialogueBlock({
  member,
  text,
  chipEntities,
  speaking = false,
}: {
  member: MemberLite
  text: string
  chipEntities: ChipEntity[]
  speaking?: boolean
}) {
  return (
    <div className="flex items-stretch gap-3">
      <Portrait src={member.portrait} name={member.name} borderColor="border-line2" className={CHAT_PORTRAIT_SIZE} />
      <div className="flex-1 min-w-0 flex flex-col">
        <span className="font-disp text-[14px] text-gold pt-[2px] mb-1">{member.name.split(' ')[0]}</span>
        <div className={`flex-1 border-l-2 rounded-r-md px-4 py-3 ${speaking ? 'border-gold bg-gold/10' : 'border-gold/60 bg-gold/5'}`}>
          <NarrationHtml
            className="chat-prose font-body text-text whitespace-pre-wrap"
            html={applyEntityChips(formatNarration(text), chipEntities)}
          />
        </div>
      </div>
    </div>
  )
}
