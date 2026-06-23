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


# --- Narrator ---

class NarratorUpdate(BaseModel):
    instructions: str


class NarratorResponse(BaseModel):
    instructions: str


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
    maxCarrySlots: int = 12


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
    maxCarrySlots: int
    apiKeySet: bool


# --- Chat ---

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    turnNumber: int
    variant: int
    speaker: str = "narrator"
    location: str | None = None
    spotlightReason: str | None = None
    appliedInventoryDeltas: list[dict] | None = None
    appliedEquipmentChanges: list[dict] | None = None
    createdAt: str


class ChatTurnRequest(BaseModel):
    message: str


class ChatMessageUpdate(BaseModel):
    content: str


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


class ItemCatalogCreate(BaseModel):
    name: str
    type: str
    slot: str | None = None
    maxStack: int = 1
    uses: int | None = None
    rarity: str = "c"
    desc: str = ""


class ItemCatalogUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    slot: str | None = None
    maxStack: int | None = None
    uses: int | None = None
    rarity: str | None = None
    desc: str | None = None


# --- Inventory ---

class InventoryStackSchema(BaseModel):
    itemId: str
    count: int


class InventoryAddRequest(BaseModel):
    itemId: str
    count: int = 1


class InventoryRemoveRequest(BaseModel):
    itemId: str
    count: int = 1


# --- Quest ---

class QuestObjectiveSchema(BaseModel):
    id: str
    text: str
    done: bool


class QuestSchema(BaseModel):
    id: str
    title: str
    status: str = "active"
    desc: str = ""
    objectives: list[QuestObjectiveSchema] = []
    notes: str = ""
    relatedLore: list[str] = []


class QuestCreate(BaseModel):
    title: str
    status: str = "active"
    desc: str = ""
    notes: str = ""
    relatedLore: list[str] = []


class QuestUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    desc: str | None = None
    notes: str | None = None
    relatedLore: list[str] | None = None


class QuestObjectiveCreate(BaseModel):
    text: str
    done: bool = False


class QuestObjectiveUpdate(BaseModel):
    text: str | None = None
    done: bool | None = None


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
