import type { SpeciesFields } from '@shared/types/models'

export type SpeciesFieldKey = keyof SpeciesFields

/** The 8 structured Species fields, in display/compose order (see "Species
 *  & Creature Templates"). Mirrors scenarioFields.ts's SCENARIO_FIELD_DEFS
 *  for the Scenario tab — same pattern, per-entry instead of a singleton. */
export const SPECIES_FIELD_DEFS: { key: SpeciesFieldKey; label: string; placeholder: string }[] = [
  { key: 'overview', label: 'Overview', placeholder: 'What are they, at a glance? Where are they typically found?' },
  { key: 'physicalAppearance', label: 'Physical Appearance', placeholder: 'Build, distinguishing features, size range, variation...' },
  { key: 'biologyReproduction', label: 'Biology & Reproduction', placeholder: 'Physiology, lifespan, diet, how they grow or reproduce...' },
  { key: 'cultureBehavior', label: 'Culture & Behavior', placeholder: 'Society and customs, or pack/territorial/instinctual behavior...' },
  { key: 'dangerCombat', label: 'Danger & Combat Notes', placeholder: 'Threat level, tactics, notable abilities or weaknesses...' },
  { key: 'typicalGear', label: 'Typical Gear', placeholder: 'What they carry, use, build, or lair in...' },
  { key: 'archetypesVariants', label: 'Archetypes & Variants', placeholder: 'Common roles/builds/subtypes seen within the species...' },
  { key: 'nameExamples', label: 'Name Examples', placeholder: 'Naming conventions and sample names...' },
]
