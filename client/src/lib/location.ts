import type { ChatMessage } from '@shared/types/models'

export const DEFAULT_LOCATION = 'The Void'

/**
 * Derive the current scene location from chat history. The Narrator declares
 * the location via a parsed action field, stored on the assistant message; the
 * current location is the most recently declared one. Falls back to a vague
 * default before the Narrator has established anywhere.
 */
export function deriveCurrentLocation(messages: ChatMessage[]): string {
  return deriveLatest(messages, 'location') ?? DEFAULT_LOCATION
}

/** Most recently declared value of a scene field, or null if never declared. */
function deriveLatest(messages: ChatMessage[], field: 'location' | 'timeOfDay' | 'weather'): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const v = messages[i][field]
    if (v && v.trim()) return v.trim()
  }
  return null
}

/** Most recently declared in-game day, or null if never declared. */
function deriveLatestDay(messages: ChatMessage[]): number | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const v = messages[i].day
    if (typeof v === 'number' && v > 0) return v
  }
  return null
}

export interface SceneBanner {
  location: string
  timeOfDay: string | null
  weather: string | null
  day: number | null
}

/** Current location (default "The Void"), time of day, weather, and day for the banner. */
export function deriveSceneBanner(messages: ChatMessage[]): SceneBanner {
  return {
    location: deriveLatest(messages, 'location') ?? DEFAULT_LOCATION,
    timeOfDay: deriveLatest(messages, 'timeOfDay'),
    weather: deriveLatest(messages, 'weather'),
    day: deriveLatestDay(messages),
  }
}
