export interface Equipment {
  head: string | null
  neck: string | null
  torsoOver: string | null
  torsoUnder: string | null
  leftHand: string | null
  rightHand: string | null
  waist: string | null
  legsOver: string | null
  legsUnder: string | null
  feet: string | null
  accessory1: string | null
  accessory2: string | null
}

export type ItemType = 'Equipment' | 'Tool' | 'Consumable' | 'Key Item' | 'Artifact' | 'Other'
export type Rarity = 'c' | 'u' | 'r' | 'e' | 'l'

export interface ItemCatalogEntry {
  id: string
  kind: 'item'
  name: string
  type: ItemType
  slot?: string
  maxStack?: number
  uses?: number
  rarity: Rarity
  desc: string
}

export interface InventoryStack {
  itemId: string
  count: number
}

export interface BasicInfo {
  name: string
  gender: string
  species: string
  age: number
  heightCm: number
  weightKg: number
  description: string
  portrait?: string
  likes?: string
  dislikes?: string
  personality?: string
}

export interface FieldSkill {
  name: string
  description: string
}

export interface PlayerCharacter {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
}

export interface PartyMember {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  fieldSkill: FieldSkill
  lastSpokeTurn: number
  inParty: boolean
}

export interface NarratorConfig {
  instructions: string
}

export interface OpenRouterSettings {
  modelId: string
  temperature: number
  topP: number
  minP: number
  topK: number
  frequencyPenalty: number
  presencePenalty: number
  repetitionPenalty: number
  maxTokensResponse: number
  maxContextTokens: number
  maxCarrySlots: number
  maxPartySize: number
  maxToolRounds: number
  useTools: boolean
  worldbuildingMode: WorldbuildingMode
  worldbuildingModelId: string
}

export type WorldbuildingMode = 'disabled' | 'confirmation' | 'auto'

export interface WorldbuildProposal {
  id: string
  turnNumber: number
  kind: 'lore' | 'quest' | 'quest_objective' | 'member'
  operation: 'create' | 'update'
  targetId: string | null
  payload: Record<string, unknown>
  summary: string
  status: 'pending' | 'accepted' | 'rejected' | 'failed'
  note: string | null
}

export interface OpenRouterSettingsUpdate extends OpenRouterSettings {
  apiKey?: string
}

export interface InventoryDelta {
  itemId: string
  delta: number
  source: 'player_action' | 'narrator_grant'
}

export interface EquipmentChange {
  characterId: string
  slot: string
  previousItemId: string | null
  newItemId: string | null
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  turnNumber: number
  variant: number
  speaker: string
  location?: string | null
  timeOfDay?: string | null
  weather?: string | null
  spotlightReason?: string | null
  appliedInventoryDeltas?: InventoryDelta[] | null
  appliedEquipmentChanges?: EquipmentChange[] | null
  createdAt: string
}

export interface SpotlightSignal {
  memberId: string
  directlyAddressed: boolean
  fieldSkillRelevant: boolean
  turnsSinceLastSpoke: number
}

export interface QuestObjective {
  id: string
  text: string
  done: boolean
}

export interface Quest {
  id: string
  title: string
  status: 'active' | 'completed' | 'failed'
  desc: string
  objectives: QuestObjective[]
  notes: string
  relatedLore: string[]
}

export type LoreCategory = 'world' | 'characters' | 'items' | 'monsters' | 'spells'

export interface LorebookEntry {
  id: string
  title: string
  content: string
  keywords: string[]
  enabled: boolean
  permanent: boolean
  locked?: boolean
  cat: LoreCategory
}

export interface LorebookConfig {
  injectionOrder: Record<LoreCategory, number>
  injectionPosition: Record<LoreCategory, 'top' | 'bottom' | 'before_input'>
}

export interface OpenRouterModel {
  id: string
  name: string
  contextLength: number
  supportsTools: boolean
}
