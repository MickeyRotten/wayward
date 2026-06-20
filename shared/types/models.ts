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
}

export interface Scenario {
  description: string
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
}

export interface OpenRouterSettingsUpdate extends OpenRouterSettings {
  apiKey?: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  turnNumber: number
  variant: number
  createdAt: string
}

export interface SpotlightSignal {
  memberId: string
  directlyAddressed: boolean
  fieldSkillRelevant: boolean
  turnsSinceLastSpoke: number
}

export interface OpenRouterModel {
  id: string
  name: string
  contextLength: number
}
