// Pure derivations over the chat message list, extracted from ChatScene.
// Everything here must stay referentially pure — the results are useMemo'd in
// ChatScene and passed to the memo'd MessageBubble.

import type { ChatMessage } from '@shared/types/models'

export function buildVisibleMessages(
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

export function getVariantCounts(messages: ChatMessage[]): Record<number, number> {
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
export function computeSceneHeaders(
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
