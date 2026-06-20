from sqlalchemy import select

from server.db.database import async_session
from server.db.models import (
    InventoryStack,
    ItemCatalogEntry,
    NarratorConfig,
    PartyMember,
    PlayerCharacter,
    Scenario,
    StorySummary,
)

EMPTY_EQUIPMENT = {
    "head": None, "neck": None, "torsoOver": None, "torsoUnder": None,
    "leftHand": None, "rightHand": None, "waist": None,
    "legsOver": None, "legsUnder": None, "feet": None,
    "accessory1": None, "accessory2": None,
}

# ---------------------------------------------------------------------------
# Stable IDs for seed catalog items — referenced by equipment dicts below.
# Using deterministic UUIDs so seed data is reproducible across re-creates.
# ---------------------------------------------------------------------------
ITEM_IDS = {
    # Equipment — currently worn by seed characters
    "worn_lute":              "a0000001-0001-4000-8000-000000000001",
    "travelers_cloak":        "a0000001-0001-4000-8000-000000000002",
    "premium_leather_gloves": "a0000001-0001-4000-8000-000000000003",
    "steel_toed_boots":       "a0000001-0001-4000-8000-000000000004",
    "celestial_gown":         "a0000001-0001-4000-8000-000000000005",
    "star_wand":              "a0000001-0001-4000-8000-000000000006",
    # Equipment — extra for variety
    "iron_helm":              "a0000001-0001-4000-8000-000000000007",
    "leather_belt":           "a0000001-0001-4000-8000-000000000008",
    "silver_pendant":         "a0000001-0001-4000-8000-000000000009",
    "wool_leggings":          "a0000001-0001-4000-8000-00000000000a",
    "travel_boots":           "a0000001-0001-4000-8000-00000000000b",
    "linen_tunic":            "a0000001-0001-4000-8000-00000000000c",
    # Consumables
    "tide_salt_draught":      "a0000001-0001-4000-8000-000000000010",
    "starlight_vial":         "a0000001-0001-4000-8000-000000000011",
    "dried_rations":          "a0000001-0001-4000-8000-000000000012",
    # Tools
    "moonstone_lantern":      "a0000001-0001-4000-8000-000000000020",
    "healers_pouch":          "a0000001-0001-4000-8000-000000000021",
    "rope_and_grapple":       "a0000001-0001-4000-8000-000000000022",
    # Key Items
    "observatory_key":        "a0000001-0001-4000-8000-000000000030",
    "ancient_sigil_fragment":  "a0000001-0001-4000-8000-000000000031",
}

# ---------------------------------------------------------------------------
# Seed catalog entries
# ---------------------------------------------------------------------------
SEED_CATALOG = [
    # --- Equipment: currently worn ---
    {
        "id": ITEM_IDS["worn_lute"],
        "name": "Worn Lute",
        "type": "Equipment",
        "slot": "Hands",
        "rarity": "c",
        "desc": "A well-traveled lute with faded lacquer and strings that still sing true. Seraphine never lets it out of reach.",
    },
    {
        "id": ITEM_IDS["travelers_cloak"],
        "name": "Traveler's Cloak",
        "type": "Equipment",
        "slot": "Torso",
        "rarity": "c",
        "desc": "A sturdy, road-worn cloak in muted grey-green. Keeps rain off and questions at bay.",
    },
    {
        "id": ITEM_IDS["premium_leather_gloves"],
        "name": "Premium Leather Gloves",
        "type": "Equipment",
        "slot": "Hands",
        "rarity": "u",
        "desc": "Reinforced knuckles and supple leather — built for someone who solves problems with her fists.",
    },
    {
        "id": ITEM_IDS["steel_toed_boots"],
        "name": "Steel-Toed Boots",
        "type": "Equipment",
        "slot": "Feet",
        "rarity": "u",
        "desc": "Heavy boots with steel-capped toes. Practical for kicking down doors and anything else that gets in the way.",
    },
    {
        "id": ITEM_IDS["celestial_gown"],
        "name": "Celestial Gown",
        "type": "Equipment",
        "slot": "Torso",
        "rarity": "r",
        "desc": "A flowing gown that shimmers faintly with starlight. It seems to weigh almost nothing.",
    },
    {
        "id": ITEM_IDS["star_wand"],
        "name": "Star Wand",
        "type": "Equipment",
        "slot": "Hands",
        "rarity": "r",
        "desc": "A slender wand tipped with a tiny, softly glowing star. Channels Rosalina's cosmic will.",
    },
    # --- Equipment: extras ---
    {
        "id": ITEM_IDS["iron_helm"],
        "name": "Iron Helm",
        "type": "Equipment",
        "slot": "Head",
        "rarity": "c",
        "desc": "A simple open-faced helm, dented but serviceable. Keeps the worst off your skull.",
    },
    {
        "id": ITEM_IDS["leather_belt"],
        "name": "Leather Belt",
        "type": "Equipment",
        "slot": "Waist",
        "rarity": "c",
        "desc": "A wide leather belt with iron buckle. Has loops for pouches and scabbards.",
    },
    {
        "id": ITEM_IDS["silver_pendant"],
        "name": "Silver Pendant",
        "type": "Equipment",
        "slot": "Neck",
        "rarity": "u",
        "desc": "A small silver pendant on a fine chain. The engraving has worn smooth with time.",
    },
    {
        "id": ITEM_IDS["wool_leggings"],
        "name": "Wool Leggings",
        "type": "Equipment",
        "slot": "Legs",
        "rarity": "c",
        "desc": "Thick-knit wool leggings. Not glamorous, but warm on cold nights in the wild.",
    },
    {
        "id": ITEM_IDS["travel_boots"],
        "name": "Travel Boots",
        "type": "Equipment",
        "slot": "Feet",
        "rarity": "c",
        "desc": "Comfortable leather boots with worn soles. Made for long roads, not battlefields.",
    },
    {
        "id": ITEM_IDS["linen_tunic"],
        "name": "Linen Tunic",
        "type": "Equipment",
        "slot": "Torso",
        "rarity": "c",
        "desc": "A plain undyed linen tunic. Light, breathable, and utterly unremarkable.",
    },
    # --- Consumables ---
    {
        "id": ITEM_IDS["tide_salt_draught"],
        "name": "Tide-Salt Draught",
        "type": "Consumable",
        "max_stack": 5,
        "uses": 1,
        "rarity": "u",
        "desc": "A briny, faintly luminescent potion brewed from tidal salts. Restores vigor and clears the mind for a short while.",
    },
    {
        "id": ITEM_IDS["starlight_vial"],
        "name": "Starlight Vial",
        "type": "Consumable",
        "max_stack": 3,
        "uses": 1,
        "rarity": "r",
        "desc": "A tiny glass vial filled with captured starlight. When broken, it bathes the area in gentle radiance and wards off minor dark enchantments.",
    },
    {
        "id": ITEM_IDS["dried_rations"],
        "name": "Dried Rations",
        "type": "Consumable",
        "max_stack": 10,
        "uses": 1,
        "rarity": "c",
        "desc": "Hardtack, dried meat, and a few crumbled herbs wrapped in waxed cloth. Keeps you going.",
    },
    # --- Tools ---
    {
        "id": ITEM_IDS["moonstone_lantern"],
        "name": "Moonstone Lantern",
        "type": "Tool",
        "uses": 8,
        "rarity": "u",
        "desc": "A small brass lantern fitted with a moonstone shard. Gives off a cool, steady glow without flame or fuel — but the stone dims with use.",
    },
    {
        "id": ITEM_IDS["healers_pouch"],
        "name": "Healer's Pouch",
        "type": "Tool",
        "uses": 5,
        "rarity": "u",
        "desc": "A leather pouch of salves, clean linen strips, and a bone needle with thread. Enough to patch up the worst of a bad day.",
    },
    {
        "id": ITEM_IDS["rope_and_grapple"],
        "name": "Rope & Grapple",
        "type": "Tool",
        "rarity": "c",
        "desc": "Thirty feet of hempen rope with a three-pronged iron grapple. Gets you up, down, or across things the easy way.",
    },
    # --- Key Items ---
    {
        "id": ITEM_IDS["observatory_key"],
        "name": "Observatory Key",
        "type": "Key Item",
        "rarity": "r",
        "desc": "An ornate brass key with celestial engravings. Presumably opens something astronomical.",
    },
    {
        "id": ITEM_IDS["ancient_sigil_fragment"],
        "name": "Ancient Sigil Fragment",
        "type": "Key Item",
        "rarity": "e",
        "desc": "A shard of dark stone inscribed with a fragment of an ancient ward-sigil. Faintly warm to the touch.",
    },
]


async def seed_defaults():
    async with async_session() as session:
        existing = (await session.execute(select(PlayerCharacter))).scalars().first()
        if existing:
            return

        # --- Seed item catalog ---
        for item_data in SEED_CATALOG:
            session.add(ItemCatalogEntry(**item_data))

        # --- Seed characters with equipment referencing catalog IDs ---
        pc = PlayerCharacter(
            basic_info={
                "name": "Seraphine",
                "gender": "Female",
                "species": "Human",
                "age": 24,
                "heightCm": 168,
                "weightKg": 58,
                "description": "A wandering bard with silver-streaked hair and quiet, watchful eyes. She carries herself with the calm of someone who has seen more than she lets on.",
            },
            equipment={
                **EMPTY_EQUIPMENT,
                "rightHand": ITEM_IDS["worn_lute"],
                "torsoOver": ITEM_IDS["travelers_cloak"],
            },
        )

        tifa = PartyMember(
            basic_info={
                "name": "Tifa",
                "gender": "Female",
                "species": "Human",
                "age": 25,
                "heightCm": 167,
                "weightKg": 61,
                "description": "A martial artist with dark hair and wine-red eyes. Warm and steady with her companions, devastating to anything she can reach with her fists.",
                "portrait": "tifa.png",
            },
            equipment={
                **EMPTY_EQUIPMENT,
                "leftHand": ITEM_IDS["premium_leather_gloves"],
                "rightHand": ITEM_IDS["premium_leather_gloves"],
                "feet": ITEM_IDS["steel_toed_boots"],
            },
            field_skill={
                "name": "Wrecking Fist",
                "description": "Punches as hard as a wrecking ball — able to break stone and put a big dent in metal with her bare fist. Still just a punch — things too big, too tough, or not physical at all are out of her reach.",
            },
        )

        rosalina = PartyMember(
            basic_info={
                "name": "Rosalina",
                "gender": "Female",
                "species": "Celestial",
                "age": 0,
                "heightCm": 180,
                "weightKg": 55,
                "description": "Tall and ethereal, with platinum hair that catches light like starshine. She speaks softly and sees far, carrying the quiet weight of someone who has watched over galaxies.",
            },
            equipment={
                **EMPTY_EQUIPMENT,
                "torsoOver": ITEM_IDS["celestial_gown"],
                "rightHand": ITEM_IDS["star_wand"],
            },
            field_skill={
                "name": "Luma Swarm",
                "description": "Commands a small swarm of Lumas — star sprites the size of a fist. They scout, fetch, distract, and watch passages. Fast and clever, but fragile and not fighters.",
            },
        )

        narrator = NarratorConfig(
            instructions=(
                "You are the Narrator of an ongoing adventure. Describe the world vividly "
                "in second person, addressing the player character directly. Keep prose concise "
                "— two to four paragraphs per beat. Advance the scene with each response: "
                "describe what happens, what the player sees or feels, and leave a natural "
                "opening for their next action. Never speak for the player character or decide "
                "their actions. When voicing a party member, use a dialogue tag with their name "
                "and keep it to one or two sentences in character. "
                "Characters are wearing only what they have equipped — if an equipment slot is "
                "empty, they have nothing in that slot. Do not invent clothing or gear that is "
                "not listed in their equipment."
            ),
        )

        scenario = Scenario(
            description=(
                "The party stands at the edge of a moonlit clearing deep in the Whispering Woods. "
                "Ancient stone pillars, half-swallowed by moss and vine, ring a shallow depression "
                "in the earth where faint silver light pools like water. The air hums with something "
                "old. Behind them, the trail back to the village is already swallowed by mist."
            ),
        )

        summary = StorySummary(content="", summary_up_to_turn=0)

        # --- Seed starter inventory ---
        inv_draught = InventoryStack(
            item_id=ITEM_IDS["tide_salt_draught"],
            count=2,
        )
        inv_lantern = InventoryStack(
            item_id=ITEM_IDS["moonstone_lantern"],
            count=1,
        )
        inv_rations = InventoryStack(
            item_id=ITEM_IDS["dried_rations"],
            count=5,
        )

        session.add_all([
            pc, tifa, rosalina, narrator, scenario, summary,
            inv_draught, inv_lantern, inv_rations,
        ])
        await session.commit()
