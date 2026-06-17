from sqlalchemy import select

from server.db.database import async_session
from server.db.models import NarratorConfig, PartyMember, PlayerCharacter, Scenario, StorySummary

DEFAULT_ATTRIBUTES = {"STR": 10, "CON": 10, "DEX": 10, "INT": 10, "WIS": 10, "CHA": 10}

EMPTY_EQUIPMENT = {
    "head": "", "neck": "", "torsoOver": "", "torsoUnder": "",
    "leftHand": "", "rightHand": "", "waist": "",
    "legsOver": "", "legsUnder": "", "feet": "",
    "accessory1": "", "accessory2": "",
}


async def seed_defaults():
    async with async_session() as session:
        existing = (await session.execute(select(PlayerCharacter))).scalars().first()
        if existing:
            return

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
            attributes={"STR": 8, "CON": 10, "DEX": 12, "INT": 14, "WIS": 13, "CHA": 16},
            equipment={**EMPTY_EQUIPMENT, "rightHand": "Worn lute", "torsoOver": "Traveler's cloak"},
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
            attributes={"STR": 18, "CON": 14, "DEX": 15, "INT": 10, "WIS": 11, "CHA": 13},
            equipment={**EMPTY_EQUIPMENT, "leftHand": "Premium leather gloves", "rightHand": "Premium leather gloves", "feet": "Steel-toed boots"},
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
            attributes={"STR": 7, "CON": 9, "DEX": 10, "INT": 18, "WIS": 17, "CHA": 15},
            equipment={**EMPTY_EQUIPMENT, "torsoOver": "Celestial gown", "rightHand": "Star wand"},
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

        session.add_all([pc, tifa, rosalina, narrator, scenario, summary])
        await session.commit()
