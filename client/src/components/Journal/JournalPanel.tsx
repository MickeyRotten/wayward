import { useMemo } from 'react'
import { useChatStore } from '../../state/chatStore'
import { useJournalStore } from '../../state/journalStore'
import type { ChatMessage } from '@shared/types/models'

// One timeline row: a scene change or a persistent chat event, anchored to the
// message it belongs to (click scrolls the chat there).
interface JournalEntry {
  key: string
  msgId: number | null
  turn: number
  kind: 'scene' | 'chronicler' | 'item'
  text: string
}

interface DayGroup {
  day: number
  entries: JournalEntry[]
}

/** Latest-variant assistant messages of the narrator thread, ascending. */
function narratorTimeline(messages: ChatMessage[]): ChatMessage[] {
  const latest = new Map<number, ChatMessage>()
  for (const m of messages) {
    if (m.role !== 'assistant' || (m.mode ?? 'narrator') === 'planner') continue
    const cur = latest.get(m.turnNumber)
    if (!cur || m.variant >= cur.variant) latest.set(m.turnNumber, m)
  }
  return [...latest.values()].sort((a, b) => a.turnNumber - b.turnNumber)
}

export function JournalPanel() {
  const messages = useChatStore((s) => s.messages)
  const events = useChatStore((s) => s.events)
  const summary = useJournalStore((s) => s.summary)

  // Group scene changes + events by in-game day. Day/location/time are
  // narrator-declared and sparse, so "latest wins" carries them forward —
  // the same rule the chat banner uses (lib/location.ts).
  const days = useMemo<DayGroup[]>(() => {
    const timeline = narratorTimeline(messages)
    const eventsByTurn = new Map<number, typeof events>()
    for (const ev of events) {
      const list = eventsByTurn.get(ev.turnNumber) ?? []
      list.push(ev)
      eventsByTurn.set(ev.turnNumber, list)
    }

    const groups: DayGroup[] = []
    let curDay = 1
    let lastLoc: string | null = null
    let lastTod: string | null = null
    const groupFor = (day: number): DayGroup => {
      const last = groups[groups.length - 1]
      if (last && last.day === day) return last
      const g: DayGroup = { day, entries: [] }
      groups.push(g)
      return g
    }

    for (const m of timeline) {
      if (m.day && m.day > 0) curDay = m.day
      const g = groupFor(curDay)
      const loc = m.location ?? null
      const tod = m.timeOfDay ?? null
      const sceneChanged = (loc && loc !== lastLoc) || (tod && tod !== lastTod)
      if (loc) lastLoc = loc
      if (tod) lastTod = tod
      if (sceneChanged) {
        g.entries.push({
          key: `scene-${m.id}`,
          msgId: m.id,
          turn: m.turnNumber,
          kind: 'scene',
          text: [lastLoc, lastTod].filter(Boolean).join(' · '),
        })
      }
      for (const ev of eventsByTurn.get(m.turnNumber) ?? []) {
        g.entries.push({
          key: `ev-${ev.id}`,
          msgId: m.id,
          turn: m.turnNumber,
          kind: ev.kind === 'chronicler' ? 'chronicler' : 'item',
          text: ev.text,
        })
      }
    }
    return groups.filter((g) => g.entries.length > 0)
  }, [messages, events])

  const jumpTo = (msgId: number | null) => {
    if (msgId == null) return
    document.getElementById(`msg-${msgId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const hasAnything = summary.trim() || days.length > 0

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">JOURNAL</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-4">
        {/* The Story So Far — the auto-maintained summary as a recap card */}
        <div className="px-2">
          <span className="font-ui text-[9px] text-textsec tracking-wider">THE STORY SO FAR</span>
          {summary.trim() ? (
            <div className="mt-1.5 border-l-2 border-gold/50 bg-bg2/60 rounded-r-md px-3.5 py-2.5">
              <p className="font-body text-[13px] text-text2 leading-relaxed italic whitespace-pre-wrap">
                {summary}
              </p>
            </div>
          ) : (
            <p className="mt-1.5 font-body text-[12px] text-textdim px-1 py-1">
              Your story is still young — a recap appears here once enough has
              happened for the chronicle to be compressed.
            </p>
          )}
        </div>

        {/* Day-by-day timeline */}
        {days.map((g) => (
          <div key={g.day} className="px-2">
            <div className="flex items-center gap-2 pb-1">
              <span className="font-disp text-[13px] text-gold pt-[2px]">Day {g.day}</span>
              <div className="flex-1 border-t border-line" />
            </div>
            <div className="space-y-0.5">
              {g.entries.map((e) => (
                <button
                  key={e.key}
                  type="button"
                  onClick={() => jumpTo(e.msgId)}
                  title="Show in the story"
                  className="w-full text-left flex items-start gap-2 px-1.5 py-1 rounded-sm hover:bg-bg2 transition-colors"
                >
                  {e.kind === 'scene' ? (
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-gold/80 mt-[3px] flex-shrink-0">
                      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" />
                    </svg>
                  ) : e.kind === 'chronicler' ? (
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-gold/60 mt-[3px] flex-shrink-0">
                      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
                    </svg>
                  ) : (
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-textsec mt-[3px] flex-shrink-0">
                      <path d="M20 7h-9M14 17H5M17 3v8M7 13v8" /><circle cx="17" cy="14" r="3" /><circle cx="7" cy="10" r="3" />
                    </svg>
                  )}
                  <span className={`font-body text-[12px] leading-relaxed ${e.kind === 'scene' ? 'text-text2' : 'text-textdim'}`}>
                    {e.text}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}

        {!hasAnything && (
          <p className="text-[12px] text-textdim font-body px-4 py-3 text-center">
            Nothing recorded yet — play a few turns and the journal fills itself in.
          </p>
        )}
      </div>
    </div>
  )
}
