// The chat scene — orchestrates the banner, backdrop + weather, the message
// list, the action panel, the composer, and the chat modals. The heavy pieces
// live in sibling Scene/ modules: MessageBubble (memo'd bubbles), the
// StreamingWindow (sole subscriber to per-chunk streaming state), Narration
// (segment renderer + entity chips), SceneBanner, ActionPanel, Composer,
// EventToast, SearchBar, PromptLogModal, and the pure chatDerived helpers.

import { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useWorldbuildStore } from '../../state/worldbuildStore'
import { useSettingsStore } from '../../state/settingsStore'
import { usePartyStore } from '../../state/partyStore'
import { useItemsStore } from '../../state/itemsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { useActionSuggestionsStore } from '../../state/actionSuggestionsStore'
import { useJournalStore } from '../../state/journalStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'
import { deriveSceneBanner } from '../../lib/location'
import { fetchBackdrops, pickBackdrop, type Backdrop } from '../../lib/backdrops'
import { weatherKind } from '../../lib/weather'
import { WeatherEffects } from './WeatherEffects'
import { useAppearanceStore } from '../../state/appearanceStore'
import { buildMemberResolver } from '../../lib/narration'
import {
  NarrationHtml,
  applyEntityChips,
  formatNarrationWithDropCap,
  type ChipEntity,
} from './Narration'
import { MessageBubble } from './MessageBubble'
import { StreamingWindow } from './StreamingWindow'
import { SceneBanner } from './SceneBanner'
import { ActionPanel } from './ActionPanel'
import { Composer } from './Composer'
import { EventToast } from './EventToast'
import { SearchBar } from './SearchBar'
import { PromptLogModal, type PromptLogMessage } from './PromptLogModal'
import { Elapsed } from './Indicators'
import { buildVisibleMessages, getVariantCounts, computeSceneHeaders } from './chatDerived'

export type { ChipEntity } from './Narration'

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
  const firstMessageAlternates = useNarratorStore((s) => s.firstMessageAlternates)
  const anchoredOpening = useChatStore((s) => s.anchoredOpening)
  const openingIndex = useChatStore((s) => s.openingIndex)
  const setOpeningIndex = useChatStore((s) => s.setOpeningIndex)
  const planningMode = useChatStore((s) => s.planningMode)
  const setPlanningMode = useChatStore((s) => s.setPlanningMode)
  const pendingDeletes = useChatStore((s) => s.pendingDeletes)
  const applyPendingDeletes = useChatStore((s) => s.applyPendingDeletes)
  const dismissPendingDeletes = useChatStore((s) => s.dismissPendingDeletes)
  const recapSummary = useJournalStore((s) => s.summary)
  const recapDismissed = useJournalStore((s) => s.bannerDismissed)
  const dismissRecap = useJournalStore((s) => s.dismissBanner)

  const playerCharacter = usePartyStore((s) => s.playerCharacter)
  const partyMembers = usePartyStore((s) => s.partyMembers)
  const catalog = useItemsStore((s) => s.catalog)
  const actionSuggestionsEnabled = useNarratorStore((s) => s.actionSuggestionsEnabled)
  const actionOptionRules = useNarratorStore((s) => s.actionOptionRules)
  const firstMessageOptions = useNarratorStore((s) => s.firstMessageOptions)
  const actionSuggestions = useActionSuggestionsStore((s) => s.suggestions)
  const actionSuggestionsLoading = useActionSuggestionsStore((s) => s.loading)
  const actionSuggestionsTurn = useActionSuggestionsStore((s) => s.lastTurn)
  const runSuggestionsForTurn = useActionSuggestionsStore((s) => s.runForTurn)
  const rerollSuggestions = useActionSuggestionsStore((s) => s.regenerate)

  const [promptLog, setPromptLog] = useState<PromptLogMessage[] | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)
  const [regenNoteOpen, setRegenNoteOpen] = useState(false)
  const [regenNote, setRegenNote] = useState('')
  const [editTargetId, setEditTargetId] = useState<number | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [matchIdx, setMatchIdx] = useState(0)
  const [atBottom, setAtBottom] = useState(true)
  const listRef = useRef<HTMLDivElement>(null)

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

  // R13 alternate openings: the pool the player can swipe at turn 0 (primary
  // first, then alternates), and the greeting actually shown. Once the
  // adventure has anchored a greeting, that one wins and the arrows retire.
  const greetings = useMemo(
    () => [firstMessage, ...firstMessageAlternates].filter((g) => g.trim()),
    [firstMessage, firstMessageAlternates],
  )
  // Clamp the transient selection so a stale index (e.g. after an adventure
  // switch to a campaign with fewer greetings) can't fall out of range.
  const openIdx = greetings.length ? ((openingIndex % greetings.length) + greetings.length) % greetings.length : 0
  const displayedOpening = anchoredOpening ?? (greetings[openIdx] ?? firstMessage)

  // Find first narrator message index for drop-cap. When a configured First
  // Message is shown, IT carries the drop-cap, so real messages never do.
  const hasFirstMessage = !planningMode && !!displayedOpening.trim()

  // The unified text-adventure action panel: numbered choice options (scripted
  // on the opening beat, AI-generated afterwards) + the fixed actions. Shown
  // whenever the player could act — idle after a narrator beat, or on a fresh
  // adventure showing only the First Message.
  const isOpening = !visibleMessages.some((m) => m.role === 'user')
  // Swipe arrows to cycle greetings — only pre-anchor, with more than one.
  const showOpeningSwipe = isOpening && !anchoredOpening && greetings.length > 1
  const panelOptions = isOpening
    ? (hasFirstMessage ? firstMessageOptions : [])
    : (actionSuggestionsEnabled ? actionSuggestions : [])
  const showActionPanel =
    !planningMode && !inputLocked && (showWhatDoYouDo || visibleMessages.length === 0)
  // The in-chat panel holds only the numbered options + reroll now (the fixed
  // actions moved under the composer). Show it when there are options, or when
  // the suggester is mid-adventure and enabled (loading / empty-hint / reroll).
  const showOptionsPanel =
    showActionPanel && (panelOptions.length > 0 || (!isOpening && actionSuggestionsEnabled))

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
      <SceneBanner
        banner={banner}
        planningMode={planningMode}
        inputLocked={inputLocked}
        onToggleMode={() => setPlanningMode(!planningMode)}
      />

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

        {/* Configured opening narration (drop-capped, not editable in chat).
            Pre-anchor, swipe arrows cycle the alternate greetings (R13). */}
        {hasFirstMessage && (
          <div className="max-w-[85%] max-lg:max-w-full mr-auto">
            <div className="px-4 py-3">
              <NarrationHtml
                className="chat-prose font-body text-text2 whitespace-pre-wrap first-narrator-dropcap"
                html={applyEntityChips(formatNarrationWithDropCap(displayedOpening), chipEntities)}
              />
            </div>
            {showOpeningSwipe && (
              <div className="px-4 pb-1 flex items-center gap-3 text-gold">
                <button
                  type="button"
                  aria-label="Previous opening"
                  className="font-ui text-[13px] leading-none px-1.5 py-0.5 border border-line hover:border-gold/50 hover:text-gold2 transition-colors"
                  onClick={() => setOpeningIndex((openIdx - 1 + greetings.length) % greetings.length)}
                >
                  ‹
                </button>
                <span className="font-ui text-[10px] tracking-wider text-textsec tabular-nums">
                  OPENING {openIdx + 1} / {greetings.length}
                </span>
                <button
                  type="button"
                  aria-label="Next opening"
                  className="font-ui text-[13px] leading-none px-1.5 py-0.5 border border-line hover:border-gold/50 hover:text-gold2 transition-colors"
                  onClick={() => setOpeningIndex((openIdx + 1) % greetings.length)}
                >
                  ›
                </button>
              </div>
            )}
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
        {showOptionsPanel && (
          <ActionPanel
            options={panelOptions}
            optionRules={actionOptionRules}
            isOpening={isOpening}
            suggestionsEnabled={actionSuggestionsEnabled}
            loading={actionSuggestionsLoading}
            attempted={actionSuggestionsTurn !== null}
            disabled={inputLocked || !apiKeySet}
            onPick={(s) => sendTurn(s)}
            onReroll={() => void rerollSuggestions()}
          />
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

      {/* Input — the freeform escape hatch under the action panel, with the
          always-available fixed actions sitting above the box. */}
      <Composer
        showInputRegenerate={!!showInputRegenerate}
        hasVisibleMessages={visibleMessages.length > 0}
        onSnapToBottom={() => setAtBottom(true)}
        onOpenRegenNote={() => { setRegenNote(''); setRegenNoteOpen(true) }}
        onClearChat={() => setConfirmAction({ message: 'Clear the entire chat history? This cannot be undone.', action: clearHistory })}
        onOpenSearch={() => setSearchOpen(true)}
        onExportTranscript={handleExportTranscript}
        onShowLog={handleShowLog}
      />

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
