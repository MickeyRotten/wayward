import type { ScenarioFields } from '@shared/types/models'

export type ScenarioFieldKey = keyof ScenarioFields

/** The 6 structured Scenario fields, in display order (see "The Scenario"). */
export const SCENARIO_FIELD_DEFS: { key: ScenarioFieldKey; label: string }[] = [
  { key: 'setting', label: 'Setting' },
  { key: 'historyBrief', label: 'History (Brief)' },
  { key: 'species', label: 'Species' },
  { key: 'geography', label: 'Geography' },
  { key: 'techAndMagic', label: 'Technology & Magic' },
  { key: 'other', label: 'Other' },
]

/** Selection id for the First Message pseudo-field shown on the Scenario tab.
 *  It lives on the NarratorConfig, not the Scenario — kept clearly separate.
 *  This is opening index 0 (the primary); alternates use `opening:<index>`. */
export const FIRST_MESSAGE_ID = 'firstMessage'
const OPENING_PREFIX = 'opening:'

/** Selection id for opening message at `index` (0 = primary First Message). */
export function openingSelId(index: number): string {
  return index === 0 ? FIRST_MESSAGE_ID : `${OPENING_PREFIX}${index}`
}

/** The opening index encoded in a selection id, or null if it isn't one. */
export function openingIndexOf(id: string): number | null {
  if (id === FIRST_MESSAGE_ID) return 0
  if (id.startsWith(OPENING_PREFIX)) {
    const n = Number.parseInt(id.slice(OPENING_PREFIX.length), 10)
    return Number.isFinite(n) && n > 0 ? n : null
  }
  return null
}

export interface OpeningEntry { message: string; options: string[] }

/** The full ordered list of openings: the primary First Message first, then
 *  each alternate. Index aligns with `openingSelId`. */
export function buildOpenings(
  firstMessage: string,
  firstMessageOptions: string[],
  alternates: OpeningEntry[],
): OpeningEntry[] {
  return [{ message: firstMessage, options: firstMessageOptions }, ...alternates]
}
