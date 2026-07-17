// Shared narration-rendering primitives: inline markup formatting, entity
// chips, the JRPG segment renderer (dialogue blocks, inscriptions, dividers),
// scene headers, and the chat portrait. Used by MessageBubble, StreamingWindow,
// and the ChatScene first-message block.

import { useTtsStore } from '../../state/ttsStore'
import type { Segment, MemberLite } from '../../lib/narration'

// ── Portrait Component ──────────────────────────────────────────────

// Shared chat portrait size — PC bubble and party dialogue blocks match.
export const CHAT_PORTRAIT_SIZE = 'w-16 h-20'

export function Portrait({
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

// ── Inline markup + entity chips ────────────────────────────────────

export function formatNarration(text: string): string {
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
export function applyEntityChips(html: string, entities: ChipEntity[]): string {
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
export function NarrationHtml({ className, html }: { className: string; html: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />
}

export function formatNarrationWithDropCap(text: string): string {
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
export function SceneHeader({ location, timeOfDay }: { location?: string | null; timeOfDay?: string | null }) {
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
export function SegmentedNarration({
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
