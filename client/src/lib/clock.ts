/**
 * The phase vocabulary, mirrored from `server/ai/clock.py`.
 *
 * Time reaches the client as a *phase word* and nothing else — the server owns
 * the calendar and the minute, so nothing here can narrate a clock face and
 * then be contradicted. Three separate places used to carry their own
 * five-value time map (the backdrop matcher, the scene header's emoji, the
 * banner's icon) and each would have needed the same four new words; they read
 * this instead.
 */

/** The eight phases, in day order. Anything else is treated as freeform. */
export const PHASES = [
  'late night', 'dawn', 'morning', 'midday',
  'afternoon', 'evening', 'dusk', 'night',
] as const

export type Phase = (typeof PHASES)[number]

/** Day or night, for anything that only has two of something (backdrop art). */
const DAYLIGHT: Record<string, 'day' | 'night'> = {
  'late night': 'night',
  dawn: 'day',
  morning: 'day',
  midday: 'day',
  day: 'day',
  afternoon: 'day',
  evening: 'night',
  dusk: 'night',
  night: 'night',
}

/** A phase word (or any legacy freeform value) → 'day' | 'night' | null. */
export function daylightToken(timeOfDay: string | null | undefined): 'day' | 'night' | null {
  const key = (timeOfDay ?? '').trim().toLowerCase()
  return DAYLIGHT[key] ?? null
}

/**
 * The icon family a phase belongs to. The banner draws four shapes, so the
 * eight phases fold onto them: the two low-sun phases share the sunset shape
 * and the two dark ones share the moon.
 */
export type SunShape = 'sunrise' | 'high' | 'sunset' | 'moon'

const SHAPES: Record<string, SunShape> = {
  dawn: 'sunrise',
  morning: 'sunrise',
  midday: 'high',
  day: 'high',
  afternoon: 'high',
  evening: 'sunset',
  dusk: 'sunset',
  night: 'moon',
  'late night': 'moon',
}

export function sunShape(timeOfDay: string | null | undefined): SunShape | null {
  return SHAPES[(timeOfDay ?? '').trim().toLowerCase()] ?? null
}

const EMOJI: Record<SunShape, string> = {
  sunrise: '🌅', high: '☀️', sunset: '🌇', moon: '🌙',
}

export function phaseEmoji(timeOfDay: string | null | undefined): string {
  const shape = sunShape(timeOfDay)
  return shape ? EMOJI[shape] : ''
}
