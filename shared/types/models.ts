export interface AttributeBlock {
  STR: number
  CON: number
  DEX: number
  INT: number
  WIS: number
  CHA: number
}

export interface Equipment {
  head: string
  neck: string
  torsoOver: string
  torsoUnder: string
  leftHand: string
  rightHand: string
  waist: string
  legsOver: string
  legsUnder: string
  feet: string
  accessory1: string
  accessory2: string
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
  attributes: AttributeBlock
  equipment: Equipment
}

export interface PartyMember {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  attributes: AttributeBlock
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
