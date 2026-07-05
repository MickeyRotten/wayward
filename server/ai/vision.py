"""The Vision agent — describes player-attached chat images.

The narrator/editor models are often text-only (or expensive to run
multimodal), so images never go to them directly. Instead this small one-shot
agent looks at the attached image with a cheap vision-capable model (default
Gemma 3 4B) and produces a compact description; that description rides along
with the player's message into the narrator/editor prompt (see
prompt_builder.augment_user_content) and is stored on the ChatMessage so
swipes/regenerates reuse it without re-running vision.

Key selection: by default the main OpenRouter key is used; Config can switch
the vision agent to its own key (e.g. a free-tier key), stored like the main
key — write-only, never returned to the client.
"""

import logging

from server.ai.openrouter import chat_completion_text
from server.db.models import OpenRouterSettings

log = logging.getLogger("wayward.vision")

VISION_DEFAULT_MODEL = "google/gemma-3-4b-it"

# Editable in Config → Agents & Tools → Vision (blank => this default).
VISION_DEFAULT_INSTRUCTIONS = (
    "You describe images attached by a player in a roleplaying game chat. "
    "Describe what the image shows in 2-5 sentences: subjects, appearance, "
    "notable details, mood, and any readable text. Be concrete and factual — "
    "no speculation about what it means for the story, no preamble; just the "
    "description."
)


def vision_key(settings: OpenRouterSettings) -> str:
    """The OpenRouter key the vision agent should use (own key when configured)."""
    if not getattr(settings, "vision_use_same_key", True):
        own = getattr(settings, "vision_api_key", "") or ""
        if own:
            return own
    return settings.api_key


async def describe_image(settings: OpenRouterSettings, image_data_url: str, player_text: str = "") -> str | None:
    """Describe an attached image; returns None when the vision call fails
    (the turn still proceeds — the prompt then notes an undescribed image)."""
    model = getattr(settings, "vision_model_id", "") or VISION_DEFAULT_MODEL
    user_parts: list[dict] = []
    if player_text.strip():
        user_parts.append({
            "type": "text",
            "text": f"The player attached this image alongside the message: {player_text.strip()[:500]}",
        })
    user_parts.append({"type": "image_url", "image_url": {"url": image_data_url}})
    instructions = (getattr(settings, "vision_instructions", "") or "").strip() or VISION_DEFAULT_INSTRUCTIONS
    try:
        text = await chat_completion_text(
            api_key=vision_key(settings),
            model_id=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_parts},
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        log.info("Vision (%s) described attached image: %s", model, text)
        return text or None
    except Exception:
        log.exception("Vision agent failed to describe the attached image")
        return None
