from pydantic import BaseModel


class BasicInfoSchema(BaseModel):
    name: str = ""
    gender: str = ""
    species: str = ""
    age: int = 0
    heightCm: int = 0
    weightKg: int = 0
    description: str = ""
    portrait: str = ""
    likes: str = ""
    dislikes: str = ""
    personality: str = ""


class EquipmentSchema(BaseModel):
    head: str | None = None
    neck: str | None = None
    torsoOver: str | None = None
    torsoUnder: str | None = None
    leftHand: str | None = None
    rightHand: str | None = None
    waist: str | None = None
    legsOver: str | None = None
    legsUnder: str | None = None
    feet: str | None = None
    accessory1: str | None = None
    accessory2: str | None = None


class FieldSkillSchema(BaseModel):
    name: str = ""
    description: str = ""


# --- Player Character ---

class PlayerCharacterUpdate(BaseModel):
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema


class PlayerCharacterResponse(BaseModel):
    id: str
    schemaVersion: int
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    # Character-file portrait URLs (full → Inspector, crop → chat/avatars); null
    # when that image doesn't exist yet.
    portraitFull: str | None = None
    portraitCrop: str | None = None


# --- Party Member ---

class PartyMemberCreate(BaseModel):
    basicInfo: BasicInfoSchema = BasicInfoSchema()
    equipment: EquipmentSchema = EquipmentSchema()
    fieldSkill: FieldSkillSchema = FieldSkillSchema()


class PartyMemberUpdate(BaseModel):
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    fieldSkill: FieldSkillSchema


class PartyMemberResponse(BaseModel):
    id: str
    schemaVersion: int
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    fieldSkill: FieldSkillSchema
    lastSpokeTurn: int
    inParty: bool = True
    portraitFull: str | None = None
    portraitCrop: str | None = None


class PartyMembershipUpdate(BaseModel):
    inParty: bool


# --- Narrator ---

class NarratorUpdate(BaseModel):
    instructions: str | None = None
    actionInstruction: str | None = None
    spotlightRule: str | None = None
    firstMessage: str | None = None
    postHistoryInstructions: str | None = None
    plannerInstructions: str | None = None
    actionSuggestionsEnabled: bool | None = None
    actionSuggestionsInstructions: str | None = None
    diceEnabled: bool | None = None


class NarratorResponse(BaseModel):
    hasVoice: bool = False  # narrator TTS voice sample present for this campaign
    diceEnabled: bool = True  # server-rolled d20 skill_check tool offered
    instructions: str
    actionInstruction: str
    spotlightRule: str
    firstMessage: str
    postHistoryInstructions: str
    plannerInstructions: str
    actionSuggestionsEnabled: bool
    actionSuggestionsInstructions: str


# --- Scenario ---

class ScenarioUpdate(BaseModel):
    setting: str | None = None
    historyBrief: str | None = None
    species: str | None = None
    geography: str | None = None
    techAndMagic: str | None = None
    other: str | None = None


class ScenarioResponse(BaseModel):
    setting: str = ""
    historyBrief: str = ""
    species: str = ""
    geography: str = ""
    techAndMagic: str = ""
    other: str = ""


# --- OpenRouter Settings ---

class OpenRouterSettingsUpdate(BaseModel):
    apiKey: str | None = None
    modelId: str = ""
    temperature: float = 0.7
    topP: float = 1.0
    minP: float = 0.0
    topK: int = 0
    frequencyPenalty: float = 0.0
    presencePenalty: float = 0.0
    repetitionPenalty: float = 1.0
    maxTokensResponse: int = 1000
    maxContextTokens: int = 128000
    maxPartySize: int = 3
    maxToolRounds: int = 6
    useTools: bool = True
    worldbuildingMode: str = "confirmation"
    worldbuildingModelId: str = ""
    actionSuggestionsModelId: str = ""
    summaryThreshold: float = 0.7
    summaryModelId: str = ""
    visionModelId: str = ""
    visionUseSameKey: bool = True
    visionApiKey: str | None = None  # write-only, like apiKey
    visionInstructions: str = ""     # blank => built-in default
    ttsEnabled: bool = False
    ttsAutoplay: bool = True


class OpenRouterSettingsResponse(BaseModel):
    modelId: str
    temperature: float
    topP: float
    minP: float
    topK: int
    frequencyPenalty: float
    presencePenalty: float
    repetitionPenalty: float
    maxTokensResponse: int
    maxContextTokens: int
    maxPartySize: int
    maxToolRounds: int
    useTools: bool
    worldbuildingMode: str
    worldbuildingModelId: str
    actionSuggestionsModelId: str
    summaryThreshold: float
    summaryModelId: str
    visionModelId: str
    visionUseSameKey: bool
    visionApiKeySet: bool
    visionInstructions: str  # effective text (default filled in when unset)
    ttsEnabled: bool
    ttsAutoplay: bool
    apiKeySet: bool


# --- TTS ---

class TtsSpeakRequest(BaseModel):
    text: str
    voice: str = "narrator"  # 'narrator' or a character id


class TtsSpeakResponse(BaseModel):
    url: str
    cached: bool


class TtsStatusResponse(BaseModel):
    installed: bool
    enabled: bool
    loaded: bool
    device: str | None = None
    error: str | None = None


# --- Chat ---

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    turnNumber: int
    variant: int
    speaker: str = "narrator"
    mode: str = "narrator"
    location: str | None = None
    timeOfDay: str | None = None
    weather: str | None = None
    day: int | None = None
    spotlightReason: str | None = None
    appliedInventoryDeltas: list[dict] | None = None
    appliedEquipmentChanges: list[dict] | None = None
    imageUrl: str | None = None          # player-attached image (served from the adventure folder)
    imageDescription: str | None = None  # the vision agent's description of it
    createdAt: str


class ChatEventResponse(BaseModel):
    id: int
    turnNumber: int
    kind: str            # 'chronicler' | 'item'
    text: str
    tethered: bool
    createdAt: str


class ChatTurnRequest(BaseModel):
    message: str
    mode: str = "narrator"  # 'narrator' | 'planner'
    # Optional player-attached image as a data URL (image/jpeg|png|webp). The
    # vision agent describes it for the narrator/editor; the file is saved in
    # the adventure's chat_images/ folder for display in the chat log.
    image: str | None = None


# --- Planner (Planning mode) ---

class PlannerDelete(BaseModel):
    kind: str          # lore | quest | quest_objective | member
    targetId: str
    label: str = ""


class PlannerDeletesApply(BaseModel):
    deletes: list[PlannerDelete] = []


# --- World-building (Chronicler) ---

class WorldbuildRunRequest(BaseModel):
    turn: int | None = None


class WorldbuildProposalSchema(BaseModel):
    id: str
    turnNumber: int
    kind: str
    operation: str
    targetId: str | None = None
    payload: dict
    summary: str
    status: str
    note: str | None = None


class ChatMessageUpdate(BaseModel):
    content: str


# --- Action Suggestions ---

class ActionSuggestionsRunRequest(BaseModel):
    turn: int | None = None


class ActionSuggestionsResponse(BaseModel):
    suggestions: list[str]


# --- Item Catalog ---

class ItemCatalogEntrySchema(BaseModel):
    id: str
    kind: str = "item"
    name: str
    type: str
    slot: str | None = None
    maxStack: int = 1
    uses: int | None = None
    rarity: str = "c"
    desc: str = ""
    # Shared lorebook-entry rules (items are lorebook entries).
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False


class ItemCatalogCreate(BaseModel):
    name: str
    type: str
    slot: str | None = None
    maxStack: int = 1
    uses: int | None = None
    rarity: str = "c"
    desc: str = ""
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False


class ItemCatalogUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    slot: str | None = None
    maxStack: int | None = None
    uses: int | None = None
    rarity: str | None = None
    desc: str | None = None
    keywords: list[str] | None = None
    enabled: bool | None = None
    permanent: bool | None = None


# --- Inventory ---

class InventoryStackSchema(BaseModel):
    itemId: str
    count: int
    instanceId: str | None = None
    equippedBy: str | None = None
    equippedByName: str | None = None
    slot: str | None = None


class InventoryAddRequest(BaseModel):
    itemId: str
    count: int = 1


class InventoryRemoveRequest(BaseModel):
    itemId: str
    count: int = 1


# --- Task (flat successor to Quests) ---

class TaskSchema(BaseModel):
    id: str
    text: str
    status: str = "active"  # active | completed | failed
    notes: str = ""


class TaskCreate(BaseModel):
    text: str
    status: str = "active"
    notes: str = ""


class TaskUpdate(BaseModel):
    text: str | None = None
    status: str | None = None
    notes: str | None = None


# --- Lorebook ---

class LorebookEntrySchema(BaseModel):
    id: str
    title: str
    content: str
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    locked: bool = False
    cat: str = "world"


class LorebookEntryCreate(BaseModel):
    title: str
    content: str = ""
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    cat: str = "world"


class LorebookEntryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    keywords: list[str] | None = None
    enabled: bool | None = None
    permanent: bool | None = None
    cat: str | None = None


class LorebookConfigSchema(BaseModel):
    injectionOrder: dict[str, int] = {
        "world": 0, "characters": 10, "items": 20,
        "monsters": 30, "spells": 40,
    }
    injectionPosition: dict[str, str] = {
        "world": "top", "characters": "top", "items": "top",
        "monsters": "top", "spells": "top",
    }


class LorebookConfigUpdate(BaseModel):
    injectionOrder: dict[str, int] | None = None
    injectionPosition: dict[str, str] | None = None
