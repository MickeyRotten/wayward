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
    head: str = ""
    neck: str = ""
    torsoOver: str = ""
    torsoUnder: str = ""
    leftHand: str = ""
    rightHand: str = ""
    waist: str = ""
    legsOver: str = ""
    legsUnder: str = ""
    feet: str = ""
    accessory1: str = ""
    accessory2: str = ""


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


# --- Scenario ---

class ScenarioUpdate(BaseModel):
    description: str


class ScenarioResponse(BaseModel):
    description: str


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
    apiKeySet: bool


# --- Chat ---

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    turnNumber: int
    variant: int
    createdAt: str


class ChatTurnRequest(BaseModel):
    message: str


class ChatMessageUpdate(BaseModel):
    content: str
