import type { PartyMember } from '@shared/types/models'

// A party member, reduced to what the dialogue block needs to render.
export interface MemberLite {
  id: string
  name: string
  portrait?: string
}

// Ordered block segments parsed out of a narrator prose blob. Dialogue blocks
// are produced ONLY for in-party members who are attributed a line — everything
// else (narration, NPC "Name:" lines) stays narration, so the feature degrades
// gracefully when the narrator doesn't follow the convention.
export type Segment =
  | { type: 'narration'; text: string }
  | { type: 'dialogue'; member: MemberLite; text: string }
  | { type: 'blockquote'; text: string }
  | { type: 'divider' }

/**
 * Build a name → member resolver from the IN-PARTY members only (mirrors who
 * actually participates in narration). Keyed by both the full name and the
 * first name, lowercased, so "Tifa" and "Tifa Lockhart" both resolve.
 */
export function buildMemberResolver(partyMembers: PartyMember[]): Map<string, MemberLite> {
  const map = new Map<string, MemberLite>()
  for (const pm of partyMembers) {
    if (!pm.inParty) continue
    const name = (pm.basicInfo?.name || '').trim()
    if (!name) continue
    const lite: MemberLite = { id: pm.id, name, portrait: pm.basicInfo?.portrait }
    const full = name.toLowerCase()
    const first = name.split(/\s+/)[0].toLowerCase()
    if (!map.has(full)) map.set(full, lite)
    // Only register the first name if it's unambiguous (don't clobber).
    if (first !== full && !map.has(first)) map.set(first, lite)
  }
  return map
}

const DIVIDER_RE = /^\s*(?:\*\s*\*\s*\*|\*{3,}|-{3,})\s*$/
const QUOTE_RE = /^\s*>\s?/
// A dialogue line: "Name: ..." / "Name — ..." at the start of the line. The name
// is captured loosely and validated against the resolver afterward.
const DIALOGUE_RE = /^\s*([A-Za-z][A-Za-z0-9 '’\-]{0,30}?)\s*[:—]\s+(.+)$/

// Opening → closing quote pairs, for splitting the spoken span off a dialogue
// line so trailing narration ("…" she said, almost warmly) doesn't end up in
// the dialogue box.
const QUOTE_PAIRS: Record<string, string> = { '"': '"', '“': '”', '«': '»', "'": "'", '‘': '’' }

/**
 * If a dialogue line's text starts with a quote, return just the quoted span as
 * the spoken line and everything after the closing quote as trailing narration.
 * Lines without a leading quote are returned whole (no reliable split point).
 */
function splitSpokenLine(text: string): { spoken: string; trailing: string } {
  const open = text[0]
  const close = QUOTE_PAIRS[open]
  if (!close) return { spoken: text, trailing: '' }
  const end = text.indexOf(close, 1)
  if (end === -1) return { spoken: text, trailing: '' } // unterminated → keep whole
  return { spoken: text.slice(0, end + 1), trailing: text.slice(end + 1).trim() }
}

/**
 * Split a narration string into ordered block segments. Works line-by-line so it
 * is robust to single- vs double-newline paragraph separation. `resolver` decides
 * which "Name:" lines become party-member dialogue blocks.
 */
export function parseSegments(content: string, resolver: Map<string, MemberLite>): Segment[] {
  const segments: Segment[] = []
  let narration: string[] = []
  let quote: string[] = []

  const flushNarration = () => {
    const text = narration.join('\n').trim()
    if (text) segments.push({ type: 'narration', text })
    narration = []
  }
  const flushQuote = () => {
    const text = quote.join('\n').trim()
    if (text) segments.push({ type: 'blockquote', text })
    quote = []
  }

  for (const line of content.split('\n')) {
    const t = line.trim()

    if (!t) {
      // Blank line — paragraph break: close out any open blocks.
      flushQuote()
      flushNarration()
      continue
    }
    if (DIVIDER_RE.test(t)) {
      flushQuote()
      flushNarration()
      segments.push({ type: 'divider' })
      continue
    }
    if (QUOTE_RE.test(line)) {
      flushNarration()
      quote.push(line.replace(QUOTE_RE, ''))
      continue
    }
    const m = line.match(DIALOGUE_RE)
    if (m) {
      const member = resolver.get(m[1].trim().toLowerCase())
      if (member) {
        flushQuote()
        flushNarration()
        const { spoken, trailing } = splitSpokenLine(m[2].trim())
        segments.push({ type: 'dialogue', member, text: spoken })
        // Narration that trailed the quote on the same line becomes its own beat.
        if (trailing) narration.push(trailing)
        continue
      }
    }
    // Ordinary narration line.
    flushQuote()
    narration.push(line)
  }

  flushQuote()
  flushNarration()
  return segments
}
