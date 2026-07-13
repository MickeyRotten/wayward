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

export type ItemType = 'Equipment' | 'Tool' | 'Consumable' | 'Key Item' | 'Artifact' | 'Currency' | 'Other'
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
  // Items are lorebook entries and share the same entry rules.
  keywords: string[]
  enabled: boolean
  permanent: boolean
}

// One owned physical copy of an item. Equipment is non-stacking (count 1, one
// row per copy); stackables keep a count. `equippedBy`/`slot` are derived from
// the character equipment dicts server-side (null when stowed in the pack).
export interface InventoryStack {
  instanceId: string
  itemId: string
  count: number
  equippedBy?: string | null
  equippedByName?: string | null
  slot?: string | null
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
  /** What pushes the character forward — goal, want, or need. */
  drive?: string
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
  // Character-file portrait URLs (full → Inspector, crop → chat/avatars).
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean  // TTS voice-cloning sample present in the character folder
}

export interface PartyMember {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  fieldSkill: FieldSkill
  lastSpokeTurn: number
  inParty: boolean
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean
}

// A character-library card (identity file), independent of any adventure.
export interface CharacterCard {
  id: string
  type: 'persona' | 'character'
  basicInfo: BasicInfo
  fieldSkill: FieldSkill
  hasFull: boolean
  hasCrop: boolean
  hasVoice?: boolean
  fullUrl?: string | null
  cropUrl?: string | null
  voiceUrl?: string | null
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
  maxPartySize: number
  maxToolRounds: number
  useTools: boolean
  worldbuildingMode: WorldbuildingMode
  worldbuildingModelId: string
  actionSuggestionsModelId: string
  summaryThreshold: number
  summaryModelId: string
  // Vision agent (describes player-attached chat images). Blank model id →
  // the built-in default (google/gemma-3-4b-it). It can run on its own
  // OpenRouter key; visionApiKeySet mirrors apiKeySet (the key itself is
  // write-only).
  visionModelId: string
  visionUseSameKey: boolean
  visionInstructions: string  // effective text (server fills the default when unset)
  // Text-to-speech (optional server-side Chatterbox install).
  ttsEnabled: boolean
  ttsAutoplay: boolean
}

// Server-side TTS engine availability (GET /tts/status).
export interface TtsStatus {
  installed: boolean
  enabled: boolean
  loaded: boolean
  device?: string | null
  error?: string | null
}

export type WorldbuildingMode = 'disabled' | 'confirmation' | 'auto'

export interface WorldbuildProposal {
  id: string
  turnNumber: number
  kind: 'lore' | 'task' | 'member'
  operation: 'create' | 'update'
  targetId: string | null
  payload: Record<string, unknown>
  summary: string
  status: 'pending' | 'accepted' | 'rejected' | 'failed'
  note: string | null
}

export interface ActionSuggestionsResponse {
  suggestions: string[]
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

// A single tool action the Editor took during a planning turn (e.g. "Editing
// lore" → "Updated the entry 'Murkwood'."). Streamed live and stored on the message.
export interface EditorAction {
  name: string
  result: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  turnNumber: number
  variant: number
  speaker: string
  mode?: 'narrator' | 'planner'
  location?: string | null
  timeOfDay?: string | null
  weather?: string | null
  day?: number | null
  spotlightReason?: string | null
  appliedInventoryDeltas?: InventoryDelta[] | null
  appliedEquipmentChanges?: EquipmentChange[] | null
  editorActions?: EditorAction[] | null  // Editor turns: tool actions taken that turn
  imageUrl?: string | null          // player-attached image (user messages)
  imageDescription?: string | null  // the vision agent's description of it
  createdAt: string
}

// A persistent in-chat toast rendered inline in the story log. 'chronicler'
// toasts are tethered to their turn (removed when it's deleted/regenerated);
// 'item' toasts (player equip/drop/add) are untethered and never turn-removed.
export interface ChatEvent {
  id: number
  turnNumber: number
  kind: 'chronicler' | 'item' | 'dice'
  text: string
  tethered: boolean
  createdAt: string
}

export interface Campaign {
  id: string
  name: string
  createdAt: string
}

export interface Adventure {
  id: string
  name: string
  createdAt: string
  lastPlayedAt: string
  day: number
  location: string
  pcName: string
  pcPortrait: string
  partyPortraits: string[]
}

export interface PlannerDelete {
  kind: 'lore' | 'task' | 'member'
  targetId: string
  label: string
}

export interface SpotlightSignal {
  memberId: string
  directlyAddressed: boolean
  fieldSkillRelevant: boolean
  turnsSinceLastSpoke: number
}

export type TaskStatus = 'active' | 'completed' | 'failed'

export interface Task {
  id: string
  text: string
  status: TaskStatus
  notes: string
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

export interface ScenarioFields {
  setting: string
  historyBrief: string
  species: string
  geography: string
  techAndMagic: string
  other: string
}

export interface OpenRouterModel {
  id: string
  name: string
  contextLength: number
  supportsTools: boolean
  supportsImages: boolean
}
