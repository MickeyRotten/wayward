"""The /api router — an aggregator over the domain routers.

The old 3,600-line monolith was split into domain modules (see below); this
file just stitches their routers together under the /api prefix, in the same
relative order the routes were originally registered. main.py keeps importing
`router` from here unchanged. Shared helpers live in server/api/common.py.
"""

from fastapi import APIRouter

from server.api import (
    backdrops,
    campaigns,
    characters,
    chat,
    items,
    lore,
    narrator,
    objectives,
    planner,
    settings,
    tasks,
    tts,
    wishlist,
    worldbuild,
)

router = APIRouter(prefix="/api")

for _module in (
    campaigns,   # adventures, campaigns, backups, adventure export/import/reset
    characters,  # PC, party members, character library (portraits/voices)
    backdrops,   # chat backdrop art
    lore,        # scenario + lorebook
    narrator,    # narrator config, journal, narrator voice
    settings,    # LLM provider settings + models proxy
    tts,         # text-to-speech
    items,       # item catalog, inventory, equip/unequip
    tasks,       # the flat to-do list
    objectives,  # overarching, direction-setting goals
    wishlist,    # player wants the narrator keeps in mind
    chat,        # messages/events, turn/swipe/regenerate/continue, streaming
    worldbuild,  # Chronicler proposals + action suggestions
    planner,     # the Editor's queued-delete apply
):
    router.include_router(_module.router)
