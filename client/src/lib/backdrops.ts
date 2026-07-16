import { api } from './api'

/** Fallback backdrop when nothing matches the scene (per design). */
export const DEFAULT_BACKDROP = 'forest_day.png'

export interface Backdrop {
  file: string
  url: string
}

// The available set is server art — fetch once per app load, invalidated when
// the Config backdrop manager uploads/deletes.
let cached: Promise<Backdrop[]> | null = null
export function fetchBackdrops(): Promise<Backdrop[]> {
  if (!cached) {
    cached = api.get<Backdrop[]>('/backdrops').catch(() => {
      cached = null // allow a retry on the next mount
      return []
    })
  }
  return cached
}

/** Drop the cached list so the next fetch re-reads the server (after upload/delete). */
export function invalidateBackdrops(): void {
  cached = null
}

// Narrator time-of-day values → the day/night vocabulary used in backdrop
// filenames (forest_day.png, city_night.png, …).
const TIME_TOKENS: Record<string, string> = {
  morning: 'day',
  day: 'day',
  afternoon: 'day',
  evening: 'night',
  night: 'night',
}

function tokenize(s: string): string[] {
  return s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)
}

/**
 * Deterministically pick the backdrop that best fits the current scene: each
 * filename is a token set ("city_day" → city + day) scored against the words
 * of the narrator-declared location plus the time of day. Highest score wins;
 * no match falls back to forest_day.png. This is the foundation for the
 * narrator-driven pick — adding more images to server/backdrops makes new
 * scenes match automatically, with no narrator or model changes.
 */
export function pickBackdrop(
  available: Backdrop[],
  location: string,
  timeOfDay: string | null,
): Backdrop | null {
  if (available.length === 0) return null

  const haystack = new Set(tokenize(location))
  const time = (timeOfDay ?? '').toLowerCase().trim()
  if (time) {
    haystack.add(time)
    const mapped = TIME_TOKENS[time]
    if (mapped) haystack.add(mapped)
  }

  let best: Backdrop | null = null
  let bestScore = 0
  for (const b of available) {
    const stem = b.file.replace(/\.[^.]+$/, '')
    const score = tokenize(stem).filter((t) => haystack.has(t)).length
    if (score > bestScore) {
      best = b
      bestScore = score
    }
  }
  return best ?? available.find((b) => b.file === DEFAULT_BACKDROP) ?? available[0]
}
