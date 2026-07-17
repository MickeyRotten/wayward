import { create } from 'zustand'
import { api } from '../lib/api'

/** A declared attribute/stat for this world (narrative unless a later dice hook
 *  opts in — it just lets a world name its stats). */
export interface WorldAttribute {
  name: string
  description: string
}

export interface CampaignRules {
  partySize: number
  currencyName: string
  currencyAbbrev: string
  currencySymbol: string
  attributes: WorldAttribute[]
  tone: string
}

interface CampaignRulesState extends CampaignRules {
  fetchRules: () => Promise<void>
  save: (update: Partial<CampaignRules>) => Promise<void>
  /** Optimistic local update (no network) — paired with a debounced save flush
   *  in Config, mirroring the settings/narrator stores (R19 auto-save). */
  patchLocal: (partial: Partial<CampaignRules>) => void
}

const DEFAULTS: CampaignRules = {
  partySize: 3,
  currencyName: 'Gold',
  currencyAbbrev: 'gp',
  currencySymbol: '',
  attributes: [],
  tone: '',
}

export const useCampaignRulesStore = create<CampaignRulesState>((set) => ({
  ...DEFAULTS,

  fetchRules: async () => {
    const r = await api.get<CampaignRules>('/campaign-rules')
    set(r)
  },

  save: async (update) => {
    const r = await api.put<CampaignRules>('/campaign-rules', update)
    set(r)
  },

  patchLocal: (partial) => set(partial),
}))
