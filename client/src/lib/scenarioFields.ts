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
 *  It lives on the NarratorConfig, not the Scenario — kept clearly separate. */
export const FIRST_MESSAGE_ID = 'firstMessage'
