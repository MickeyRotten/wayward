"""The chat: message/event history, the player turn (narrator, both agentic and
legacy text-block paths), swipe/regenerate/continue, the shared SSE streaming
drivers, the prompt log, and background history summarisation."""

import asyncio
import json
import logging
import pathlib as _pathlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.action_suggester import normalize_suggestions_count
from server.ai.clock import advance_clock, phase_of
from server.ai.item_detection import (
    apply_inventory_deltas,
    detect_item_use,
    reverse_inventory_deltas,
)
from server.ai.narrator_actions import (
    coerce_scene,
    execute_actions,
    parse_action_block,
    reverse_equipment_changes,
)
from server.ai.narrator_agent import run_narrator_agent
from server.ai.openrouter import chat_completion_stream, fetch_models, provider_endpoint, stream_with_retry
from server.ai.prompt_builder import (
    CONTEXT_TURNS,
    augment_user_content,
    build_prompt,
    estimate_prompt_tokens,
)
from server.ai.spotlight import (
    SpotlightSignal,
    _name_mentioned,
    compute_spotlight_signals,
    detect_speakers,
    format_spotlight_block,
)
from server.ai.summarizer import (
    generate_summary,
    pick_messages_to_summarize,
    should_summarize,
)
from server.ai.turn_block import build_turn_block_guidance, parse_turn_block
from server.ai.vision import describe_image
from server.ai.worldbuilder import reverse_chronicler_effects
from server.api.common import (
    _MEDIA_CACHE,
    _chat_images_dir,
    _delete_chat_images,
    _image_url,
    _list_inventory_dicts,
    _store_chat_image,
)
from server.api.planner import _planner_turn
from server.api.schemas import (
    ChatEventResponse,
    ChatMessageResponse,
    ChatMessageUpdate,
    ChatTurnRequest,
)
from server.db import events as event_ops
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.database import get_session, new_session
from server.db.models import (
    CampaignRules,
    ChatMessage,
    ItemInstance,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    Objective,
    OpenRouterSettings,
    StorySummary,
    Task,
    Wish,
)

router = APIRouter()

log = logging.getLogger("wayward.chat")


@router.get("/chat/images/{filename}")
async def get_chat_image(filename: str, session: AsyncSession = Depends(get_session)):
    directory = await _chat_images_dir(session, create=False)
    if directory is None:
        raise HTTPException(404, "No active adventure")
    path = directory / Path(filename).name  # basename only — no traversal
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, headers=_MEDIA_CACHE)


# ── Chat Messages ─────────────────────────────────────────────────

def _msg_response(m: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=m.id,
        role=m.role,
        content=m.content,
        turnNumber=m.turn_number,
        variant=m.variant,
        speaker=m.speaker or ("narrator" if m.role == "assistant" else "player"),
        mode=m.mode or "narrator",
        location=m.location,
        timeOfDay=m.time_of_day,
        weather=m.weather,
        day=m.day,
        spotlightReason=m.spotlight_reason,
        appliedInventoryDeltas=m.applied_inventory_deltas,
        appliedEquipmentChanges=m.applied_equipment_changes,
        editorActions=getattr(m, "editor_actions", None),
        imageUrl=_image_url(m),
        imageDescription=getattr(m, "image_description", None),
        promptTokens=getattr(m, "prompt_tokens", None),
        completionTokens=getattr(m, "completion_tokens", None),
        cost=getattr(m, "gen_cost", None),
        createdAt=m.created_at.isoformat() if m.created_at else "",
    )


@router.get("/chat/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChatMessage).order_by(ChatMessage.id)
    )
    return [_msg_response(m) for m in result.scalars().all()]


@router.get("/chat/events", response_model=list[ChatEventResponse])
async def get_chat_events(session: AsyncSession = Depends(get_session)):
    """Persistent in-chat toasts (Chronicler notices + player item actions),
    rendered inline in the story log alongside the messages."""
    return [
        ChatEventResponse(
            id=e.id,
            turnNumber=e.turn_number,
            kind=e.kind,
            text=e.text,
            tethered=bool(e.tethered),
            createdAt=e.created_at.isoformat() if e.created_at else "",
        )
        for e in await event_ops.list_events(session)
    ]


@router.get("/chat/opening")
async def get_chat_opening(session: AsyncSession = Depends(get_session)):
    """The opening greeting anchored to this adventure (R13 alternate openings).
    Null until the player takes their first turn — before that the client cycles
    the campaign's greetings locally; after, this is the fixed opening shown."""
    s = (await session.execute(select(StorySummary))).scalars().first()
    return {"message": getattr(s, "opening_message", None) if s else None}


@router.put("/chat/messages/{msg_id}", response_model=ChatMessageResponse)
async def edit_message(
    msg_id: int,
    data: ChatMessageUpdate,
    session: AsyncSession = Depends(get_session),
):
    msg = await session.get(ChatMessage, msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.content = data.content
    await session.commit()
    await session.refresh(msg)
    return ChatMessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        turnNumber=msg.turn_number,
        variant=msg.variant,
        speaker=msg.speaker or ("narrator" if msg.role == "assistant" else "player"),
        mode=msg.mode or "narrator",
        day=msg.day,
        spotlightReason=msg.spotlight_reason,
        appliedInventoryDeltas=msg.applied_inventory_deltas,
        appliedEquipmentChanges=msg.applied_equipment_changes,
        createdAt=msg.created_at.isoformat() if msg.created_at else "",
    )


@router.delete("/chat/messages/{msg_id}/and-after", status_code=204)
async def delete_message_and_after(
    msg_id: int,
    session: AsyncSession = Depends(get_session),
):
    msg = await session.get(ChatMessage, msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")

    # Reverse the effects of the most-recent message in the deleted range only
    # (the live state reflects the latest assistant message's combined deltas).
    # Per Task 6.2: don't walk back older messages — just the most recent one.
    latest_with_effects = (
        await session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.id >= msg.id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.id.desc())
        )
    ).scalars().first()
    if latest_with_effects:
        await _reverse_message_effects(latest_with_effects, session)

    # Chronicler facts are tied to their message: drop lore/quests the Chronicler
    # created on this turn and every turn after it (the ones being deleted).
    await reverse_chronicler_effects(session, msg.turn_number)
    # ...and their in-chat toasts. Untethered player-action toasts are kept.
    await event_ops.delete_tethered(session, msg.turn_number)

    # Remove attached image files of the deleted messages from the adventure folder.
    doomed = (
        await session.execute(select(ChatMessage).where(ChatMessage.id >= msg.id))
    ).scalars().all()
    await _delete_chat_images(session, [m.image_path for m in doomed if getattr(m, "image_path", None)])

    await session.execute(
        delete(ChatMessage).where(ChatMessage.id >= msg.id)
    )
    # If the narrator thread is now empty we're back at the opening — release the
    # anchor so the greeting swipe arrows return (R13 alternate openings).
    remaining = (await session.execute(
        select(func.count()).select_from(ChatMessage)
        .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
    )).scalar_one()
    if not remaining:
        summary = (await session.execute(select(StorySummary))).scalars().first()
        if summary:
            summary.opening_message = None
    await session.commit()


@router.post("/chat/save-partial")
async def save_partial(
    data: ChatMessageUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Save a partial response when the user stops generation."""
    all_msgs = (
        await session.execute(select(ChatMessage).order_by(ChatMessage.id.desc()))
    ).scalars().first()

    if not all_msgs:
        return {"ok": True}

    last_turn = all_msgs.turn_number
    existing_assistant = (
        await session.execute(
            select(ChatMessage).where(
                ChatMessage.turn_number == last_turn,
                ChatMessage.role == "assistant",
            )
        )
    ).scalars().all()

    variant = len(existing_assistant)
    partial_msg = ChatMessage(
        role="assistant",
        content=data.content,
        turn_number=last_turn,
        variant=variant,
        speaker="narrator",
    )
    session.add(partial_msg)
    await session.commit()
    return {"ok": True}


@router.delete("/chat/messages", status_code=204)
async def clear_chat(session: AsyncSession = Depends(get_session)):
    # Wipe attached image files along with the messages that referenced them.
    with_images = (
        await session.execute(select(ChatMessage).where(ChatMessage.image_path.is_not(None)))
    ).scalars().all()
    await _delete_chat_images(session, [m.image_path for m in with_images])
    await session.execute(delete(ChatMessage))
    await event_ops.clear_events(session)  # wipe all toasts with the chat
    for b in await party_ops.all_bindings(session):
        b.last_spoke_turn = 0
    # Back at the opening — release the anchored greeting (R13 alternate openings).
    summary = (await session.execute(select(StorySummary))).scalars().first()
    if summary:
        summary.opening_message = None
    await session.commit()


# ── Prompt Log ────────────────────────────────────────────────────

_PROMPT_LOG_PATH = _pathlib.Path(__file__).resolve().parent.parent.parent / ".prompt_log.json"


async def _save_prompt_log(messages: list[dict]):
    # Serialization + disk write of the full prompt (can be ~MB) — keep it off
    # the event loop so it never stalls the SSE stream.
    payload = json.dumps(messages, ensure_ascii=False)
    await asyncio.to_thread(_PROMPT_LOG_PATH.write_text, payload, encoding="utf-8")


@router.get("/chat/prompt-log")
async def get_prompt_log():
    if not _PROMPT_LOG_PATH.exists():
        raise HTTPException(404, "No prompt log available")
    return json.loads(_PROMPT_LOG_PATH.read_text(encoding="utf-8"))


# ── Chat Turn ─────────────────────────────────────────────────────

async def _reverse_message_effects(msg: ChatMessage, session: AsyncSession) -> None:
    """Reverse the inventory deltas and equipment changes applied by a message.

    Used before re-generating a turn (swipe/regenerate) or when truncating
    (delete-and-after) so the world state doesn't accumulate stale effects.
    Reverses equipment first, then inventory: the inventory deltas already
    account for any item returned to the bag by a narrator unequip, so reversing
    them removes that returned item — keep both in sync by reversing both.
    """
    if msg.applied_equipment_changes:
        await reverse_equipment_changes(msg.applied_equipment_changes, session)
    if msg.applied_inventory_deltas:
        await reverse_inventory_deltas(msg.applied_inventory_deltas, session)


async def _detect_player_deltas(
    player_message: str, session: AsyncSession
) -> list[dict]:
    """Run deterministic item-use detection on a player message.

    Detection only — the deltas are *not* applied here. They are applied inside
    the streaming save transaction once the narrator message is successfully
    persisted, so a failed/cancelled generation never leaves the inventory
    decremented with no message to reverse it from (which would otherwise
    double-decrement on retry). Live inventory is not part of the prompt, so
    deferring application costs nothing in narration grounding.

    Returns the player-action inventory deltas (so they can be applied and merged
    into the narrator message's combined delta record).
    """
    inventory = await _list_inventory_dicts(session)
    return detect_item_use(player_message, inventory)


# Newest messages loaded per turn. The prompt is token-trimmed far below this
# and older history lives in the StorySummary, so nothing above the window can
# ever reach the model — loading it would be pure waste on long adventures.
# The newest-message window a turn reads. 500 was chosen as "definitely enough"
# and is roughly ten times what any model context can actually hold — every turn
# paid for a 500-row read and a 500-element list build to then trim most of it
# away in build_prompt. 160 messages is ~80 turns, comfortably past the largest
# prompt budget, and swipe/regenerate still resolve older turns through their own
# targeted queries.
_HISTORY_WINDOW = 160


@dataclass
class GameContext:
    """Everything one narration turn reads, loaded once.

    Previously a twelve-element tuple unpacked identically in four places and
    threaded onward as six separate keyword arguments; the state tier needs
    three more facts and a fifteen-tuple is not a thing anyone should have to
    read."""
    settings: OpenRouterSettings
    narrator: NarratorConfig
    pc: object
    party: list            # active (in-party) members — the scene
    benched: list          # in the world, not travelling — named in the roll call
    messages: list[ChatMessage]
    summary: StorySummary
    catalog: list[LorebookEntry]
    tasks: list[Task]
    objectives: list[Objective]
    wishes: list[Wish]
    lore_entries: list[LorebookEntry]
    lore_config: LorebookConfig
    scene: dict            # latest-wins location/day/minutes/weather
    inventory_lines: list[str]


def _derive_scene(messages: list[ChatMessage]) -> dict:
    """Carry the scene forward from the newest message that declared each field.

    Latest-wins per field, walking backwards — the same rule the chat banner
    uses client-side, so the narrator and the player never disagree about where
    they are."""
    scene: dict = {}
    for m in reversed(messages):
        for key, attr in (("location", "location"), ("timeOfDay", "time_of_day"),
                          ("weather", "weather"), ("day", "day"), ("minutes", "scene_minutes")):
            if key not in scene:
                v = getattr(m, attr, None)
                if v is not None and (not isinstance(v, str) or v.strip()):
                    scene[key] = v
        if len(scene) == 5:
            break
    scene.setdefault("day", 1)
    scene.setdefault("minutes", 8 * 60)  # a new adventure opens mid-morning
    return scene


async def _inventory_lines(session: AsyncSession, catalog: list[LorebookEntry]) -> list[str]:
    """The pack as compact ``Label xN — description`` lines.

    Stated in the state tier rather than the standing context because the output
    protocol's rules point straight at it ("use the label already in INVENTORY"),
    and up top the rule and the list it names sat a whole history window apart."""
    by_id = {c.id: c for c in catalog}
    equipped = await inv_ops.equipped_map(session)
    instances = list((await session.execute(select(ItemInstance))).scalars().all())
    counts: dict[str, int] = {}
    for inst in instances:
        if inst.id in equipped:
            continue  # worn gear is on the sheets; stating it twice invites a re-statement
        counts[inst.item_id] = counts.get(inst.item_id, 0) + max(1, int(inst.count or 1))
    lines: list[str] = []
    for item_id, n in counts.items():
        entry = by_id.get(item_id)
        if not entry:
            continue
        label = entry.title + (f" x{n}" if n > 1 else "")
        desc = (entry.content or "").strip().split("\n")[0][:120]
        lines.append(f"{label} — {desc}" if desc else label)
    return sorted(lines)


async def _load_game_context(session: AsyncSession) -> GameContext:
    """Load all game state needed for a chat turn."""
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings:
        raise HTTPException(400, "LLM provider not configured")
    _base_url, api_key, main_model = provider_endpoint(settings)
    if not api_key:
        raise HTTPException(400, "API key not configured for the selected provider")
    if not main_model:
        raise HTTPException(400, "No model selected")

    narrator = (await session.execute(select(NarratorConfig))).scalars().first() or NarratorConfig(instructions="")
    pc = await party_ops.load_pc(session)
    if not pc:
        raise HTTPException(400, "No player character created")

    everyone = await party_ops.load_party(session)
    party = [m for m in everyone if m.in_party]
    benched = [m for m in everyone if not m.in_party]

    # Narration only ever sees the 'narrator' thread — Editor-mode messages live
    # in their own thread and never enter narration context. Bounded to the
    # newest window (ascending after reversal); the newest turn is always inside
    # it, so max()/variant lookups on recent turns behave exactly as before.
    recent = (await session.execute(
        select(ChatMessage)
        .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
        .order_by(ChatMessage.id.desc())
        .limit(_HISTORY_WINDOW)
    )).scalars().all()
    all_messages = list(reversed(recent))
    summary = (await session.execute(select(StorySummary))).scalars().first()
    if not summary:
        summary = StorySummary(content="", summary_up_to_turn=0)
        session.add(summary)
    catalog = list((await session.execute(select(LorebookEntry).where(LorebookEntry.cat == "items"))).scalars().all())
    tasks = list((await session.execute(select(Task).order_by(Task.sort_order))).scalars().all())
    objectives = list((await session.execute(select(Objective).order_by(Objective.sort_order))).scalars().all())
    wishes = list((await session.execute(
        select(Wish).order_by(Wish.priority.desc(), Wish.sort_order)
    )).scalars().all())
    lore_entries = list((await session.execute(select(LorebookEntry))).scalars().all())
    lore_config = (await session.execute(select(LorebookConfig))).scalars().first()
    if not lore_config:
        lore_config = LorebookConfig()
        session.add(lore_config)
        await session.commit()

    return GameContext(
        settings=settings, narrator=narrator, pc=pc, party=party, benched=benched,
        messages=all_messages, summary=summary, catalog=catalog, tasks=tasks,
        objectives=objectives, wishes=wishes, lore_entries=lore_entries,
        lore_config=lore_config, scene=_derive_scene(all_messages),
        inventory_lines=await _inventory_lines(session, catalog),
    )


async def _resolve_narration_mode(settings: OpenRouterSettings) -> str:
    """Resolve the narrator's state-mutation path from ``tool_mode``:

    - ``'native'`` — the agentic tool loop (needs a tool-capable model);
    - ``'text'``   — the hardened ``<<<ACTIONS>>>`` text protocol (reliable on
      weaker/older narrative models that call tools poorly);
    - ``'off'``    — no state mutation; pure prose.

    ``'auto'`` picks native when the selected model advertises tool support, else
    text. On a model-list fetch failure we assume native and let the call surface
    any error rather than silently downgrading. (An unset/legacy value derives
    from the old ``use_tools`` boolean.)"""
    mode = (getattr(settings, "tool_mode", "") or "").strip().lower()
    if mode not in ("auto", "native", "text", "off"):
        mode = "auto" if getattr(settings, "use_tools", True) else "text"
    if mode != "auto":
        return mode
    base_url, api_key, main_model = provider_endpoint(settings)
    # Non-OpenRouter providers (NIM/custom) report every model as tool-capable
    # in fetch_models, so this resolves to native there — trust the picker.
    try:
        models = await fetch_models(api_key, base_url=base_url)
        m = next((x for x in models if x["id"] == main_model), None)
        if m is not None:
            return "native" if m.get("supportsTools") else "text"
    except Exception:
        log.info("_resolve_narration_mode: model list fetch failed; assuming native")
    return "native"


async def _maybe_summarize_and_build(
    ctx: "GameContext",
    history: list[ChatMessage],
    player_message: str,
    current_turn: int,
    session: AsyncSession,
    narration_mode: str = "native",
):
    """Build the turn's prompt and measure it against the summary threshold.
    Returns (prompt_messages, needs_summary, spotlight_signals).

    Summarisation itself no longer happens here — when the prompt is over the
    threshold, ``needs_summary`` tells the stream driver to schedule a
    background compression AFTER the narration is delivered
    (_summarize_in_background), so the player never waits on the summariser."""
    narrator, pc, party_list, summary = ctx.narrator, ctx.pc, ctx.party, ctx.summary

    # Filter history to only unsummarized turns
    filtered = [m for m in history if m.turn_number > summary.summary_up_to_turn]

    # Compute spotlight. The scan window is CONTEXT_TURNS — the SAME window lore
    # matching uses — so "mentioned" means one thing across every gate.
    spotlight_block = None
    spotlight_signals = []
    if party_list:
        recent_assistant = [m.content for m in filtered if m.role == "assistant"][-CONTEXT_TURNS:]
        recent_context = " ".join(recent_assistant)
        spotlight_signals = compute_spotlight_signals(
            player_message=player_message,
            recent_context=recent_context,
            party_members=party_list,
            current_turn=current_turn,
        )
        spotlight_block = format_spotlight_block(
            spotlight_signals, getattr(narrator, "spotlight_rule", "") or None
        )

    # If the player addressed a benched member by name, hint the narrator to
    # acknowledge their absence rather than silently ignoring it. (The roll call
    # in the state tier already names them as not present; this is the case
    # where the player asked directly and deserves an answer.)
    absent = [
        pm.basic_info["name"] for pm in ctx.benched
        if pm.basic_info.get("name") and _name_mentioned(pm.basic_info["name"], player_message)
    ]
    if absent:
        note = (
            "NOTE — ABSENT PARTY MEMBER: The player named "
            + ", ".join(absent)
            + (", who is" if len(absent) == 1 else ", who are")
            + " not currently travelling with the party. Acknowledge that they "
            "aren't here rather than voicing them as if present."
        )
        spotlight_block = f"{spotlight_block}\n\n{note}" if spotlight_block else note

    # World Rules — party/currency/attributes/tone. One small query per turn;
    # None-safe if the row is absent.
    _rules = (await session.execute(select(CampaignRules))).scalars().first()
    rules_dict = {
        "party_size": _rules.party_size,
        "partySize": _rules.party_size,
        "currency_name": _rules.currency_name,
        "currency_abbrev": _rules.currency_abbrev,
        "currency_symbol": _rules.currency_symbol,
        "attributes": getattr(_rules, "attributes", None),
        "tone": _rules.tone,
    } if _rules else None

    # Build the turn's prompt (build_prompt trims oldest history to the budget,
    # so this always fits) and measure it against the summary threshold.
    test_prompt = build_prompt(
        narrator_config=narrator,
        player_character=pc,
        party_members=party_list,
        benched_members=ctx.benched,
        chat_history=filtered,
        player_message=player_message,
        spotlight_block=spotlight_block,
        story_summary=summary.content or None,
        item_catalog=ctx.catalog,
        tasks=ctx.tasks,
        objectives=ctx.objectives,
        wishes=ctx.wishes,
        lore_entries=ctx.lore_entries,
        lore_config=ctx.lore_config,
        max_context_tokens=ctx.settings.max_context_tokens,
        max_response_tokens=ctx.settings.max_tokens_response,
        include_action_protocol=(narration_mode == "text"),
        first_message_override=getattr(summary, "opening_message", None),
        campaign_rules=rules_dict,
        scene=ctx.scene,
        inventory_lines=ctx.inventory_lines,
    )

    preamble_tokens = estimate_prompt_tokens(test_prompt)
    # Over-threshold no longer summarises IN the turn (that stalled the player
    # behind a whole extra LLM call on exactly the slowest turns). The prompt
    # above already fits — build_prompt trims oldest history to the budget — so
    # we just flag it and the stream driver compresses in the background AFTER
    # the narration is delivered (see _summarize_in_background).
    needs_summary = should_summarize(
        preamble_tokens, 0, ctx.settings.max_context_tokens, ctx.settings.max_tokens_response,
        threshold=getattr(ctx.settings, "summary_threshold", None) or 0.7,
    )

    return test_prompt, needs_summary, spotlight_signals


_bg_summary_lock = asyncio.Lock()


def _schedule_background_summary() -> None:
    """Fire-and-forget the post-turn history compression."""
    asyncio.create_task(_summarize_in_background())


async def _summarize_in_background() -> None:
    """Compress the oldest unsummarised turns into the running Story So Far,
    OUTSIDE the player's turn (the summariser LLM call used to run before
    narration started, stalling long adventures). Runs after the narration is
    saved; own session; re-checks the threshold itself; errors only logged.
    The lock keeps concurrent turns from double-summarising the same span."""
    if _bg_summary_lock.locked():
        return  # a pass is already running; the next turn re-checks anyway
    async with _bg_summary_lock:
        try:
            async with new_session() as session:
                settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
                if not settings:
                    return
                base_url, api_key, main_model = provider_endpoint(settings)
                if not api_key or not main_model:
                    return
                summary = (await session.execute(select(StorySummary))).scalars().first()
                if not summary:
                    summary = StorySummary(content="", summary_up_to_turn=0)
                    session.add(summary)
                recent = (await session.execute(
                    select(ChatMessage)
                    .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
                    .order_by(ChatMessage.id.desc())
                    .limit(_HISTORY_WINDOW)
                )).scalars().all()
                filtered = [m for m in reversed(recent) if m.turn_number > summary.summary_up_to_turn]

                # No threshold re-check here: the in-turn scheduler already
                # measured the FULL prompt over the threshold. Re-measuring with
                # a different (history-only) metric could decline forever while
                # trimming silently drops unsummarised turns.
                to_summarize, _to_keep, new_boundary = pick_messages_to_summarize(filtered)
                if not to_summarize:
                    return
                new_summary = await generate_summary(
                    api_key=api_key,
                    model_id=(getattr(settings, "summary_model_id", "") or main_model),
                    messages_to_summarize=to_summarize,
                    existing_summary=summary.content,
                    base_url=base_url,
                )
                summary.content = new_summary
                summary.summary_up_to_turn = new_boundary
                await session.commit()
                log.info("BACKGROUND SUMMARY compressed history up to turn %s", new_boundary)
        except Exception:
            log.exception("Background summarisation failed (will retry on a later turn)")


@router.post("/chat/turn")
async def chat_turn(
    data: ChatTurnRequest,
    session: AsyncSession = Depends(get_session),
):
    if data.mode == "planner":
        return await _planner_turn(data, session)

    ctx = await _load_game_context(session)
    settings, narrator, pc, party = ctx.settings, ctx.narrator, ctx.pc, ctx.party
    all_messages, summary = ctx.messages, ctx.summary

    max_turn = max((m.turn_number for m in all_messages), default=0)
    current_turn = max_turn + 1

    # Anchor the opening: on the very first narrator turn, lock in whichever
    # greeting the player had selected (R13 alternate openings). Falls back to
    # the campaign's primary first_message when none was sent. From here on the
    # anchored text drives both the chat display and the prompt.
    if max_turn == 0 and getattr(summary, "opening_message", None) is None:
        summary.opening_message = (data.opening or "").strip() or (narrator.first_message or "")
        session.add(summary)

    # Player-attached image: save it with the adventure, have the vision agent
    # describe it (the narrator itself may be text-only), and record both on the
    # user message so swipes/regenerates reuse the description.
    image_path: str | None = None
    image_desc: str | None = None
    if data.image:
        image_path = await _store_chat_image(session, data.image)
        image_desc = await describe_image(settings, data.image, data.message)

    user_msg = ChatMessage(
        role="user", content=data.message, turn_number=current_turn, speaker=pc.id,
        image_path=image_path, image_description=image_desc,
    )
    session.add(user_msg)

    # What the narrator sees: the message text plus the image description.
    prompt_message = augment_user_content(data.message, image_desc) if image_path else data.message

    mode = await _resolve_narration_mode(settings)
    agentic = mode == "native"

    # Text-protocol path only: deterministic item-use detection on the player's
    # message (decrement deferred to the save transaction). Native mode uses the
    # consume_item tool; 'off' mutates nothing — so both skip detection.
    player_deltas = await _detect_player_deltas(data.message, session) if mode == "text" else []
    await session.commit()

    messages, needs_summary, spotlight_signals = await _maybe_summarize_and_build(
        ctx,
        history=all_messages,
        player_message=prompt_message,
        current_turn=current_turn,
        session=session,
        narration_mode=mode,
    )

    variant_count = sum(
        1 for m in all_messages if m.turn_number == current_turn and m.role == "assistant"
    )

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=current_turn,
            variant=variant_count,
            spotlight_signals=spotlight_signals,
            schedule_summary=needs_summary,
            user_message_id=user_msg.id,
            inline_option_count=_inline_option_count(narrator),
            turn_guidance=_turn_block_guidance(narrator, mode != "off"),
            prev_scene=ctx.scene,
            allow_clock=mode != "off",
        )

    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=current_turn,
        variant=variant_count,
        schedule_summary=needs_summary,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
        user_message_id=user_msg.id,
        inline_option_count=_inline_option_count(narrator),
        turn_guidance=_turn_block_guidance(narrator, mode != "off"),
        prev_scene=ctx.scene,
        allow_clock=mode != "off",
    )


# ── Swipe (new variant for a specific turn) ─────────────────────

@router.post("/chat/messages/{turn}/swipe")
async def swipe(turn: int, session: AsyncSession = Depends(get_session)):
    """Generate a new variant for a specific turn. Appends to existing variants."""
    ctx = await _load_game_context(session)
    settings, narrator, pc, party = ctx.settings, ctx.narrator, ctx.pc, ctx.party
    all_messages, summary = ctx.messages, ctx.summary

    # Find the user message for this turn — targeted query (not the bounded
    # window) so swiping a turn older than the window still resolves.
    user_msg = (await session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.turn_number == turn,
            ChatMessage.role == "user",
            func.coalesce(ChatMessage.mode, "narrator") != "planner",
        )
        .order_by(ChatMessage.id)
    )).scalars().first()
    if not user_msg:
        raise HTTPException(400, f"No user message found for turn {turn}")

    # Build history up to (but not including) this turn
    history = [m for m in all_messages if m.turn_number < turn]

    # Reverse the effects of the currently-live variant for this turn (the most
    # recent assistant variant carries the combined deltas reflected in state),
    # then re-run detection on the same player message and apply fresh. This
    # keeps inventory idempotent across repeated swipes.
    turn_variants = list((await session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.turn_number == turn,
            ChatMessage.role == "assistant",
            func.coalesce(ChatMessage.mode, "narrator") != "planner",
        )
    )).scalars().all())
    if turn_variants:
        latest_variant = max(turn_variants, key=lambda m: m.variant)
        await _reverse_message_effects(latest_variant, session)
    # The prior variant's Chronicler lore/quests belong to the discarded telling
    # of this turn — drop them; the re-run's Chronicler pass will record fresh.
    await reverse_chronicler_effects(session, turn, exact=True)
    await session.commit()
    mode = await _resolve_narration_mode(settings)
    agentic = mode == "native"
    # Re-detect against the now-restored inventory (text-protocol path only);
    # native mode re-derives item use through the consume_item tool during the loop.
    player_deltas = await _detect_player_deltas(user_msg.content, session) if mode == "text" else []

    messages, needs_summary, spotlight_signals = await _maybe_summarize_and_build(
        ctx,
        history=history,
        player_message=(
            augment_user_content(user_msg.content, getattr(user_msg, "image_description", None))
            if getattr(user_msg, "image_path", None) else user_msg.content
        ),
        current_turn=turn,
        session=session,
        narration_mode=mode,
    )

    # Count existing variants for this turn to determine next variant number
    variant_count = len(turn_variants)

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=turn,
            variant=variant_count,
            spotlight_signals=spotlight_signals,
            schedule_summary=needs_summary,
            inline_option_count=_inline_option_count(narrator),
            turn_guidance=_turn_block_guidance(narrator, mode != "off"),
            # The clock advances from where the turn STARTED, not from the
            # variant being replaced — re-telling a beat must not age the world
            # twice.
            prev_scene=_derive_scene([m for m in all_messages if m.turn_number < turn]),
            allow_clock=mode != "off",
        )

    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=turn,
        variant=variant_count,
        schedule_summary=needs_summary,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
        inline_option_count=_inline_option_count(narrator),
        turn_guidance=_turn_block_guidance(narrator, mode != "off"),
        prev_scene=_derive_scene([m for m in all_messages if m.turn_number < turn]),
        allow_clock=mode != "off",
    )


# ── Regenerate ────────────────────────────────────────────────────

@router.post("/chat/regenerate")
async def regenerate(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    guidance = (data.get("guidance") or "").strip() if isinstance(data, dict) else ""
    ctx = await _load_game_context(session)
    settings, narrator, pc, party = ctx.settings, ctx.narrator, ctx.pc, ctx.party
    all_messages, summary = ctx.messages, ctx.summary

    if not all_messages:
        raise HTTPException(400, "No messages to regenerate")

    last_turn = max(m.turn_number for m in all_messages)
    last_user_msg = next(
        (m for m in reversed(all_messages) if m.turn_number == last_turn and m.role == "user"),
        None,
    )
    if not last_user_msg:
        raise HTTPException(400, "No user message found for last turn")

    # Reverse the effects of the live (latest) variant before wiping. Only the
    # latest variant's deltas are reflected in current state; earlier variants
    # were each reversed when superseded by a swipe.
    turn_variants = [
        m for m in all_messages if m.turn_number == last_turn and m.role == "assistant"
    ]
    if turn_variants:
        latest_variant = max(turn_variants, key=lambda m: m.variant)
        await _reverse_message_effects(latest_variant, session)

    # Drop the discarded telling's Chronicler lore/quests for this turn; the
    # re-run's Chronicler pass records fresh ones tied to the new message.
    await reverse_chronicler_effects(session, last_turn, exact=True)

    # REGENERATE wipes all existing assistant variants for this turn
    await session.execute(
        delete(ChatMessage).where(
            ChatMessage.turn_number == last_turn,
            ChatMessage.role == "assistant",
        )
    )

    await session.commit()
    mode = await _resolve_narration_mode(settings)
    agentic = mode == "native"
    # Re-run detection on the same player message against the restored inventory
    # (text-protocol path only; native mode uses the consume_item tool).
    player_deltas = await _detect_player_deltas(last_user_msg.content, session) if mode == "text" else []

    history = [m for m in all_messages if m.turn_number < last_turn]

    messages, needs_summary, spotlight_signals = await _maybe_summarize_and_build(
        ctx,
        history=history,
        player_message=(
            augment_user_content(last_user_msg.content, getattr(last_user_msg, "image_description", None))
            if getattr(last_user_msg, "image_path", None) else last_user_msg.content
        ),
        current_turn=last_turn,
        session=session,
        narration_mode=mode,
    )

    # Optional steering note for THIS regeneration only — injected right before
    # the player's message and never persisted to history.
    if guidance:
        note = {
            "role": "system",
            "content": (
                "RETELLING DIRECTION (applies only to this regeneration of the "
                "last turn; not world canon): " + guidance
            ),
        }
        insert_at = next(
            (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
            len(messages),
        )
        messages.insert(insert_at, note)

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=last_turn,
            variant=0,
            spotlight_signals=spotlight_signals,
            schedule_summary=needs_summary,
            inline_option_count=_inline_option_count(narrator),
            turn_guidance=_turn_block_guidance(narrator, mode != "off"),
            prev_scene=_derive_scene([m for m in all_messages if m.turn_number < last_turn]),
            allow_clock=mode != "off",
        )

    # Start fresh at variant 0 since we wiped all previous variants
    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=last_turn,
        variant=0,
        schedule_summary=needs_summary,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
        inline_option_count=_inline_option_count(narrator),
        turn_guidance=_turn_block_guidance(narrator, mode != "off"),
        prev_scene=_derive_scene([m for m in all_messages if m.turn_number < last_turn]),
        allow_clock=mode != "off",
    )


# ── Continue (extend the latest narration in place) ───────────────

_CONTINUE_NUDGE = (
    "CONTINUE: Pick up the narration exactly where the previous passage stops — "
    "same scene, same tense, mid-flow. Do NOT repeat or rephrase anything already "
    "written, do not summarise, and do not open with a greeting or a scene reset. "
    "Just write what comes next. Do not append a <<<TURN>>> block."
)

# Characters that end a complete sentence/beat — used to pick the separator when
# splicing the continuation onto the existing prose (a clipped beat continues
# mid-sentence with a space; a complete one starts a new paragraph).
_SENTENCE_END = tuple('.!?"”\'’*…_>)')


@router.post("/chat/continue")
async def continue_narration(session: AsyncSession = Depends(get_session)):
    """A true Continue: EXTEND the latest narration message in place (no new
    turn, no new player message) — also the rescue when a beat was clipped by
    max_tokens_response. Prose-only: no tools, no action protocol, no inline
    options; the appended text carries no reversible effects, so swipe/
    regenerate/delete semantics for the turn are unchanged."""
    ctx = await _load_game_context(session)
    settings, narrator, pc, party = ctx.settings, ctx.narrator, ctx.pc, ctx.party
    all_messages, summary = ctx.messages, ctx.summary

    if not all_messages:
        raise HTTPException(400, "Nothing to continue yet")
    last_turn = max(m.turn_number for m in all_messages)
    variants = [m for m in all_messages if m.turn_number == last_turn and m.role == "assistant"]
    if not variants:
        raise HTTPException(400, "No narration to continue")
    target = max(variants, key=lambda m: m.variant)
    last_user = next(
        (m for m in reversed(all_messages) if m.turn_number == last_turn and m.role == "user"),
        None,
    )

    history = [m for m in all_messages if m.turn_number < last_turn]
    messages, _needs_summary, _signals = await _maybe_summarize_and_build(
        ctx,
        history=history,
        player_message=(last_user.content if last_user else "(continue the scene)"),
        current_turn=last_turn,
        session=session,
        narration_mode="native",  # skips the action protocol — continuation is prose-only
    )
    # The passage being extended goes last, then the continue instruction.
    messages.append({"role": "assistant", "content": target.content})
    messages.append({"role": "system", "content": _CONTINUE_NUDGE})

    # Release the request session's transaction before streaming — the save at
    # the end of the stream writes on its own session, and an open transaction
    # here would hold the adventure DB lock against it (the turn route commits
    # before streaming for the same reason).
    await session.commit()

    return _stream_continue_response(messages=messages, settings=settings, target_id=target.id)


def _stream_continue_response(messages: list[dict], settings: OpenRouterSettings, target_id: int):
    context_tokens = estimate_prompt_tokens(messages)
    max_context = settings.max_context_tokens
    base_url, api_key, model_id = provider_endpoint(settings)
    log.info("LLM CONTINUE REQUEST | model=%s | ~%s prompt tokens", model_id, context_tokens)

    async def stream():
        await _save_prompt_log(messages)
        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        def _make_stream(reasoning=None):
            return chat_completion_stream(
                api_key=api_key,
                model_id=model_id,
                base_url=base_url,
                messages=messages,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens_response,
                top_p=settings.top_p,
                min_p=settings.min_p,
                top_k=settings.top_k,
                frequency_penalty=settings.frequency_penalty,
                presence_penalty=settings.presence_penalty,
                repetition_penalty=settings.repetition_penalty,
                reasoning_effort=(reasoning if reasoning is not None
                                  else (getattr(settings, "reasoning_effort", "") or None)),
                yield_events=True,
            )

        addition = ""
        usage: dict | None = None
        reasoning_seen = False
        try:
            async for out in _drive_prose_stream(
                _make_stream, getattr(settings, "auto_retry_count", 0) or 0, log_ctx=" continue",
            ):
                k = out["kind"]
                if k == "chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': out['text']})}\n\n"
                elif k == "reasoning":
                    yield f"data: {json.dumps({'type': 'reasoning', 'content': out['text']})}\n\n"
                elif k == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif k == "retry":
                    yield f"data: {json.dumps({'type': 'retry', 'attempt': out['attempt'], 'of': out['of']})}\n\n"
                elif k == "done":
                    addition = out["text"]
                    usage = out["usage"]
                    reasoning_seen = out["reasoning_seen"]
        except Exception as e:
            log.exception("Continue stream failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        if not addition.strip() and reasoning_seen:
            yield f"data: {json.dumps({'type': 'error', 'content': _REASONING_ATE_BUDGET})}\n\n"
            return

        # Defensive: strip a stray turn block if the model appended one. A
        # continuation extends the beat in place — it changes no state — so the
        # block is discarded rather than applied.
        addition, _ = parse_turn_block(addition.strip())
        saved_message: dict | None = None
        if addition:
            try:
                async with new_session() as save_session:
                    msg = await save_session.get(ChatMessage, target_id)
                    if msg is not None:
                        existing = (msg.content or "").rstrip()
                        sep = "\n\n" if existing.endswith(_SENTENCE_END) else " "
                        msg.content = f"{existing}{sep}{addition}" if existing else addition
                        # Fold the continuation's spend into the message's accounting.
                        if usage:
                            if usage.get("completion_tokens") is not None:
                                msg.completion_tokens = (msg.completion_tokens or 0) + int(usage["completion_tokens"])
                            if usage.get("cost") is not None:
                                msg.gen_cost = (msg.gen_cost or 0.0) + float(usage["cost"])
                        await save_session.commit()
                        await save_session.refresh(msg)
                        saved_message = _msg_response(msg).model_dump()
            except Exception:
                log.exception("Failed to save continuation")

        done_payload: dict = {'type': 'done', 'maxContextTokens': max_context,
                              'contextTokens': context_tokens + len(addition) // 4}
        if saved_message is not None:
            done_payload['message'] = saved_message
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Summary endpoint ──────────────────────────────────────────────

@router.get("/chat/summary")
async def get_summary(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(StorySummary))).scalars().first()
    if not s or not s.content:
        return {"content": "", "summaryUpToTurn": 0}
    return {"content": s.content, "summaryUpToTurn": s.summary_up_to_turn}


# ── Shared streaming helper ───────────────────────────────────────

def _inline_option_count(narrator) -> int | None:
    """The number of options to request when suggestions ride the main narration
    call (action_suggestions_mode == 'inline'), else None."""
    if not getattr(narrator, "action_suggestions_enabled", False):
        return None
    if (getattr(narrator, "action_suggestions_mode", "separate") or "separate") != "inline":
        return None
    return normalize_suggestions_count(getattr(narrator, "action_suggestions_count", None))


def _with_turn_guidance(messages: list[dict], guidance: str) -> list[dict]:
    """Insert the output protocol immediately BEFORE the player's action.

    The shape of the reply should be the last thing the model reads before it is
    asked to produce one — but the *ask* still has to come last, or a model reads
    the protocol as the thing it is answering."""
    if not guidance:
        return messages
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out.insert(i, {"role": "system", "content": guidance})
            return out
    out.append({"role": "system", "content": guidance})
    return out


def _turn_block_guidance(narrator, mutates_state: bool) -> str:
    """The trailing-block protocol for this turn, or "" when it carries nothing.

    Scene and clock ride the block only when the turn is allowed to change state
    at all (``tool_mode`` is not "off"), because a named field is an invitation:
    a model shown ``"duration"`` will produce one whether or not anything reads
    it."""
    return build_turn_block_guidance(
        _inline_option_count(narrator),
        include_scene=mutates_state,
        include_clock=mutates_state,
    )


def _apply_turn_block(block: dict, prev_scene: dict, allow_clock: bool = True) -> dict:
    """Fold a parsed turn block into storable scene fields.

    The narrator names a place and how long the beat took; the SERVER decides
    what day it is and what time. ``day`` is not in the block's contract at all,
    which is the point — it was a value nothing validated, free to freeze, jump
    or run backwards."""
    scene = coerce_scene(block)
    if not allow_clock:
        return scene
    day, minutes, _rested = advance_clock(
        prev_scene.get("day") or 1,
        prev_scene.get("minutes") if prev_scene.get("minutes") is not None else 8 * 60,
        block.get("duration"),
    )
    scene["day"] = day
    scene["minutes"] = minutes
    # The phase word is the only form time takes outside clock.py, and it
    # OVERRIDES anything the model wrote: the server owns the clock, so a
    # narrator-supplied "timeOfDay" is not a second opinion. It is what the
    # backdrop matcher and the scene banner read.
    scene["timeOfDay"] = phase_of(minutes)
    return scene


# Reasoning models can burn the whole response budget on thinking; surface a
# useful explanation instead of a silent empty beat. Only shown after the
# automatic reasoning-off recovery ALSO produced nothing.
_REASONING_ATE_BUDGET = (
    "The model spent its entire response budget on reasoning and wrote no "
    "narration — even after retrying with reasoning disabled. Raise Max Response "
    "Tokens (Config → AI & Model), or switch to a different model."
)


async def _drive_prose_stream(make_stream, retries: int, log_ctx: str):
    """Drive a prose (non-agentic) narration/continuation stream with one
    reasoning-off recovery: if a reasoning model spends its whole response budget
    thinking and writes nothing, retry ONCE with reasoning disabled so the budget
    goes to prose. These paths have no mid-stream DB mutations, so a full
    re-stream is always safe.

    ``make_stream(reasoning_effort)`` returns a fresh
    ``chat_completion_stream(yield_events=True)``. Yields passthrough dicts
    (``{"kind": "chunk"|"reasoning"|"discard"|"retry", ...}``) and one terminal
    ``{"kind": "done", "text": str, "usage": dict|None, "reasoning_seen": bool}``.
    """
    any_reasoning = False  # across both attempts — drives the final error guard
    for attempt in range(2):
        reasoning_off = attempt == 1
        text = ""
        usage: dict | None = None
        round_reasoning = False  # this attempt only — drives the recovery trigger
        async for ev in stream_with_retry(
            (lambda ro=reasoning_off: make_stream("off" if ro else None)),
            retries,
            log_ctx=log_ctx + (" reasoning-off recovery" if reasoning_off else ""),
        ):
            t = ev["type"]
            if t == "chunk":
                text += ev["text"]
                yield {"kind": "chunk", "text": ev["text"]}
            elif t == "reasoning":
                round_reasoning = True
                any_reasoning = True
                yield {"kind": "reasoning", "text": ev["text"]}
            elif t == "usage":
                usage = {k: v for k, v in ev.items() if k != "type"}
            elif t == "discard":
                text = ""
                yield {"kind": "discard"}
            elif t == "retry":
                yield {"kind": "retry", "attempt": ev["attempt"], "of": ev["of"]}
        if attempt == 0 and not text.strip() and round_reasoning:
            yield {"kind": "retry", "attempt": 1, "of": 1}
            continue  # recover: re-stream with reasoning disabled
        yield {"kind": "done", "text": text, "usage": usage, "reasoning_seen": any_reasoning}
        return


def _stream_llm_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list,
    current_turn: int,
    variant: int,
    schedule_summary: bool = False,
    spotlight_signals: list[SpotlightSignal] | None = None,
    player_deltas: list[dict] | None = None,
    user_message_id: int | None = None,
    inline_option_count: int | None = None,
    turn_guidance: str = "",
    prev_scene: dict | None = None,
    allow_clock: bool = True,
):
    player_deltas = player_deltas or []
    prev_scene = prev_scene or {}
    messages = _with_turn_guidance(messages, turn_guidance)

    context_tokens = estimate_prompt_tokens(messages)
    base_url, api_key, model_id = provider_endpoint(settings)
    temperature = settings.temperature
    top_p = settings.top_p
    min_p = settings.min_p
    top_k = settings.top_k
    frequency_penalty = settings.frequency_penalty
    presence_penalty = settings.presence_penalty
    repetition_penalty = settings.repetition_penalty
    max_tokens = settings.max_tokens_response
    max_context = settings.max_context_tokens

    # Terminal log: model + sampling settings at INFO; the full assembled prompt
    # (potentially hundreds of KB) only when DEBUG logging is on.
    log.info(
        "LLM REQUEST turn=%s variant=%s | model=%s | temp=%s top_p=%s min_p=%s top_k=%s "
        "freq=%s pres=%s rep=%s | max_tokens=%s max_context=%s | ~%s prompt tokens | %d messages",
        current_turn, variant, model_id, temperature, top_p, min_p, top_k,
        frequency_penalty, presence_penalty, repetition_penalty,
        max_tokens, max_context, context_tokens, len(messages),
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "LLM PROMPT (%d messages):\n%s",
            len(messages),
            "\n".join(f"  ── [{m['role']}] ──\n{m['content']}" for m in messages),
        )

    async def stream():
        await _save_prompt_log(messages)
        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        def _make_stream(reasoning=None):
            return chat_completion_stream(
                api_key=api_key,
                model_id=model_id,
                base_url=base_url,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                min_p=min_p,
                top_k=top_k,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                repetition_penalty=repetition_penalty,
                reasoning_effort=(reasoning if reasoning is not None
                                  else (getattr(settings, "reasoning_effort", "") or None)),
                yield_events=True,  # reasoning deltas + usage ride along
            )

        # Auto-retry on error/safety block (configurable), plus one reasoning-off
        # recovery when a reasoning model burns the whole budget thinking. The
        # legacy path has no mid-stream DB mutations, so a full re-stream is always
        # safe; a partial attempt emits `discard` (client clears it) before a retry.
        full_text = ""
        usage: dict | None = None
        reasoning_seen = False
        try:
            async for out in _drive_prose_stream(
                _make_stream, getattr(settings, "auto_retry_count", 0) or 0,
                log_ctx=f" legacy turn={current_turn}",
            ):
                k = out["kind"]
                if k == "chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': out['text']})}\n\n"
                elif k == "reasoning":
                    # Reasoning models (often tool-less, so they land on THIS
                    # path): surface the thinking phase live.
                    yield f"data: {json.dumps({'type': 'reasoning', 'content': out['text']})}\n\n"
                elif k == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif k == "retry":
                    yield f"data: {json.dumps({'type': 'retry', 'attempt': out['attempt'], 'of': out['of']})}\n\n"
                elif k == "done":
                    full_text = out["text"]
                    usage = out["usage"]
                    reasoning_seen = out["reasoning_seen"]
        except Exception as e:
            log.exception("OpenRouter stream failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        if not full_text.strip() and reasoning_seen:
            yield f"data: {json.dumps({'type': 'error', 'content': _REASONING_ATE_BUDGET})}\n\n"
            return

        # Terminal log: size at INFO, full raw output only at DEBUG.
        log.info("LLM RESPONSE turn=%s variant=%s (%d chars) | usage=%s", current_turn, variant, len(full_text), usage)
        log.debug("LLM RESPONSE text:\n%s", full_text)

        # Parse and strip the action block before saving
        clean_text, actions = parse_action_block(full_text)
        if actions:
            log.info("LLM ACTIONS parsed: %s", json.dumps(actions, ensure_ascii=False))
        inline_suggestions: list[str] = []
        block: dict = {}
        if turn_guidance:
            clean_text, block = parse_turn_block(clean_text)
            inline_suggestions = block.get("options") or []
            log.info("LLM TURN BLOCK turn=%s %s", current_turn,
                     json.dumps(block, ensure_ascii=False))
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []
        saved_message: dict | None = None

        try:
            async with new_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(full_text, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            await party_ops.set_last_spoke(save_session, pm.id, current_turn)

                # Determine spotlight reason for the first speaking party member
                spot_reason: str | None = None
                if speaker_ids and spotlight_signals:
                    signal_map = {s.member_id: s for s in spotlight_signals}
                    for sid in speaker_ids:
                        sig = signal_map.get(sid)
                        if sig:
                            if sig.directly_addressed:
                                spot_reason = "Directly addressed"
                            elif sig.field_skill_relevant:
                                spot_reason = "Field skill · relevant"
                            elif sig.turns_since_last_spoke >= 5:
                                spot_reason = "Hasn't spoken in a while"
                            break

                # Narrator-declared scene state. The trailing turn block wins
                # over the legacy action block: it is what the model wrote
                # alongside the beat, and it is the only one carrying a duration
                # the server can turn into a calendar.
                scene: dict = coerce_scene(actions, prev_scene.get("day")) if actions else {}
                if turn_guidance:
                    scene.update(_apply_turn_block(block, prev_scene, allow_clock))
                location = scene.get("location")
                time_of_day = scene.get("timeOfDay")
                weather = scene.get("weather")
                day = scene.get("day")

                # Execute narrator actions if present
                if actions:
                    inv_deltas, equip_changes = await execute_actions(
                        actions, save_session
                    )

                # Apply the player's item-use deltas now (deferred from detection
                # time) so they only ever hit the DB when the narrator message is
                # actually persisted — a failed/cancelled generation leaves the
                # inventory untouched. Merge them with the narrator-granted deltas
                # and store both on the narrator message so swipe/regenerate/delete
                # can reverse the full combined effect of this turn.
                if player_deltas:
                    await apply_inventory_deltas(player_deltas, save_session)
                combined_inv_deltas = [*player_deltas, *inv_deltas]

                assistant_msg = ChatMessage(
                    role="assistant", content=clean_text,
                    turn_number=current_turn, variant=variant,
                    speaker="narrator",
                    location=location,
                    time_of_day=time_of_day,
                    weather=weather,
                    day=day,
                    scene_minutes=scene.get("minutes"),
                    spotlight_reason=spot_reason,
                    applied_inventory_deltas=combined_inv_deltas if combined_inv_deltas else None,
                    applied_equipment_changes=equip_changes if equip_changes else None,
                    prompt_tokens=(usage or {}).get("prompt_tokens"),
                    completion_tokens=(usage or {}).get("completion_tokens"),
                    gen_cost=(usage or {}).get("cost"),
                )
                save_session.add(assistant_msg)
                await save_session.commit()
                await save_session.refresh(assistant_msg)
                saved_message = _msg_response(assistant_msg).model_dump()
        except Exception as e:
            log.exception("Failed to save response to DB")

        # Prefer the provider's real accounting over the chars/4 estimate.
        response_tokens = len(clean_text) // 4
        real_total = ((usage or {}).get("prompt_tokens") or 0) + ((usage or {}).get("completion_tokens") or 0)
        combined_inv_deltas = [*player_deltas, *inv_deltas]
        done_payload: dict = {
            'type': 'done',
            'contextTokens': real_total or (context_tokens + response_tokens),
            'maxContextTokens': max_context,
        }
        # The persisted message rides on `done` so a plain send can append it
        # locally instead of refetching the entire history.
        if saved_message is not None:
            done_payload['message'] = saved_message
        if user_message_id is not None:
            done_payload['userMessageId'] = user_message_id
        if combined_inv_deltas:
            done_payload['appliedInventoryDeltas'] = combined_inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        if inline_suggestions:
            done_payload['suggestions'] = inline_suggestions
        yield f"data: {json.dumps(done_payload)}\n\n"

        # Post-turn: compress history in the background (never blocks the player).
        if schedule_summary and saved_message is not None:
            _schedule_background_summary()

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Agentic streaming driver ──────────────────────────────────────

def _stream_agent_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list,
    current_turn: int,
    variant: int,
    spotlight_signals: list[SpotlightSignal] | None = None,
    schedule_summary: bool = False,
    user_message_id: int | None = None,
    inline_option_count: int | None = None,
    turn_guidance: str = "",
    prev_scene: dict | None = None,
    allow_clock: bool = True,
):
    """Drive the agentic narrator loop and stream its final narration.

    Tool calls mutate the DB *during* the loop (inside run_narrator_agent), so
    here we only record the accumulated deltas/scene on the ChatMessage for
    reversal — we do not re-apply them."""
    prev_scene = prev_scene or {}
    # Scene state and the player's options both ride the trailing block, so
    # neither costs a tool round-trip.
    messages = _with_turn_guidance(messages, turn_guidance)
    context_tokens = estimate_prompt_tokens(messages)
    max_context = settings.max_context_tokens
    _base_url, _api_key, _log_model = provider_endpoint(settings)

    log.info(
        "LLM AGENT REQUEST turn=%s variant=%s | model=%s | temp=%s | max_tokens=%s "
        "max_context=%s max_tool_rounds=%s | ~%s prompt tokens",
        current_turn, variant, _log_model, settings.temperature,
        settings.max_tokens_response, max_context, settings.max_tool_rounds, context_tokens,
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "LLM AGENT PROMPT (%d messages):\n%s",
            len(messages),
            "\n".join(f"  ── [{m['role']}] ──\n{m.get('content', '')}" for m in messages),
        )

    async def stream():
        await _save_prompt_log(messages)
        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        final_content = ""
        scene: dict = {}
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []
        tool_failures: list[str] = []
        usage: dict | None = None
        reasoning_seen = False
        saved_message: dict | None = None

        try:
            async for ev in run_narrator_agent(
                settings=settings,
                base_messages=messages,
                current_turn=current_turn,
                variant=variant,
            ):
                etype = ev["type"]
                if etype == "content":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': ev['text']})}\n\n"
                elif etype == "reasoning":
                    # Reasoning models: the thinking phase, surfaced live.
                    yield f"data: {json.dumps({'type': 'reasoning', 'content': ev['text']})}\n\n"
                elif etype == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif etype == "retry":
                    yield f"data: {json.dumps({'type': 'retry', 'attempt': ev['attempt'], 'of': ev['of']})}\n\n"
                elif etype == "tool":
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev['name'], 'result': ev['result'], 'ok': ev.get('ok', True)})}\n\n"
                elif etype == "final":
                    final_content = ev["content"]
                    scene = ev["scene"]
                    inv_deltas = ev["inv_deltas"]
                    equip_changes = ev["equip_changes"]
                    tool_failures = ev.get("tool_failures", [])
                    usage = ev.get("usage")
                    reasoning_seen = bool(ev.get("reasoning_seen"))
        except Exception as e:
            log.exception("Agent loop failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        # A reasoning model can spend the whole response budget thinking and
        # deliver no prose — explain that instead of saving an empty beat.
        if not final_content.strip() and reasoning_seen:
            yield f"data: {json.dumps({'type': 'error', 'content': _REASONING_ATE_BUDGET})}\n\n"
            return

        log.info(
            "LLM AGENT RESPONSE turn=%s variant=%s (%d chars) | scene=%s | inv_deltas=%s | equip_changes=%s | usage=%s",
            current_turn, variant, len(final_content), scene, inv_deltas, equip_changes, usage,
        )

        # The trailing block: scene + options in one read, always stripped from
        # the prose even when its JSON is malformed.
        inline_suggestions: list[str] = []
        if turn_guidance:
            final_content, block = parse_turn_block(final_content)
            inline_suggestions = block.get("options") or []
            block_scene = _apply_turn_block(block, prev_scene, allow_clock)
            # A tool-written scene (the legacy handler, still reachable) loses to
            # the block: the block is what the model wrote alongside the beat.
            scene = {**scene, **block_scene}
            log.info("LLM TURN BLOCK turn=%s scene=%s options=%s", current_turn,
                     block_scene, json.dumps(inline_suggestions, ensure_ascii=False))

        try:
            async with new_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(final_content, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            await party_ops.set_last_spoke(save_session, pm.id, current_turn)

                spot_reason: str | None = None
                if speaker_ids and spotlight_signals:
                    signal_map = {s.member_id: s for s in spotlight_signals}
                    for sid in speaker_ids:
                        sig = signal_map.get(sid)
                        if sig:
                            if sig.directly_addressed:
                                spot_reason = "Directly addressed"
                            elif sig.field_skill_relevant:
                                spot_reason = "Field skill · relevant"
                            elif sig.turns_since_last_spoke >= 5:
                                spot_reason = "Hasn't spoken in a while"
                            break

                assistant_msg = ChatMessage(
                    role="assistant", content=final_content,
                    turn_number=current_turn, variant=variant,
                    speaker="narrator",
                    location=scene.get("location"),
                    time_of_day=scene.get("timeOfDay"),
                    weather=scene.get("weather"),
                    day=scene.get("day"),
                    scene_minutes=scene.get("minutes"),
                    spotlight_reason=spot_reason,
                    applied_inventory_deltas=inv_deltas if inv_deltas else None,
                    applied_equipment_changes=equip_changes if equip_changes else None,
                    prompt_tokens=(usage or {}).get("prompt_tokens"),
                    completion_tokens=(usage or {}).get("completion_tokens"),
                    gen_cost=(usage or {}).get("cost"),
                )
                save_session.add(assistant_msg)
                await save_session.commit()
                await save_session.refresh(assistant_msg)
                saved_message = _msg_response(assistant_msg).model_dump()
        except Exception:
            log.exception("Failed to save agent response to DB")

        # Prefer the provider's real accounting over the chars/4 estimate.
        response_tokens = len(final_content) // 4
        real_total = ((usage or {}).get("prompt_tokens") or 0) + ((usage or {}).get("completion_tokens") or 0)
        done_payload: dict = {
            'type': 'done',
            'contextTokens': real_total or (context_tokens + response_tokens),
            'maxContextTokens': max_context,
        }
        # The persisted message rides on `done` so a plain send can append it
        # locally instead of refetching the entire history.
        if saved_message is not None:
            done_payload['message'] = saved_message
        if user_message_id is not None:
            done_payload['userMessageId'] = user_message_id
        if inv_deltas:
            done_payload['appliedInventoryDeltas'] = inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        if tool_failures:
            done_payload['toolFailures'] = tool_failures
        if inline_suggestions:
            done_payload['suggestions'] = inline_suggestions
        yield f"data: {json.dumps(done_payload)}\n\n"

        # Post-turn: compress history in the background (never blocks the player).
        if schedule_summary and saved_message is not None:
            _schedule_background_summary()

    return StreamingResponse(stream(), media_type="text/event-stream")
