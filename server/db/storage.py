"""Campaign/Adventure folder layout, indexing, creation, and legacy migration.

Layout (under server/data/):
    campaigns/<campaign_id>/campaign.json
    campaigns/<campaign_id>/campaign.db
    campaigns/<campaign_id>/portraits/
    campaigns/<campaign_id>/adventures/<adventure_id>/adventure.json
    campaigns/<campaign_id>/adventures/<adventure_id>/adventure.db
    campaigns/<campaign_id>/adventures/<adventure_id>/portraits/

JSON sidecars are the cheap index for listing/cards; the .db files hold the
relational data (attached at runtime — see database.py).
"""

import datetime
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from server.db import database as db

log = logging.getLogger("wayward.storage")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Paths ─────────────────────────────────────────────────────────

def campaign_dir(cid: str) -> Path:
    return db.CAMPAIGNS_DIR / cid


def campaign_db_path(cid: str) -> Path:
    return campaign_dir(cid) / "campaign.db"


def campaign_json_path(cid: str) -> Path:
    return campaign_dir(cid) / "campaign.json"


def adventure_dir(cid: str, aid: str) -> Path:
    return campaign_dir(cid) / "adventures" / aid


def adventure_db_path(cid: str, aid: str) -> Path:
    return adventure_dir(cid, aid) / "adventure.db"


def adventure_json_path(cid: str, aid: str) -> Path:
    return adventure_dir(cid, aid) / "adventure.json"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Indexing ──────────────────────────────────────────────────────

def list_campaigns() -> list[dict]:
    out: list[dict] = []
    if not db.CAMPAIGNS_DIR.exists():
        return out
    for child in db.CAMPAIGNS_DIR.iterdir():
        if child.is_dir():
            meta = _read_json(child / "campaign.json")
            if meta:
                out.append(meta)
    out.sort(key=lambda m: m.get("createdAt", ""))
    return out


def list_adventures(cid: str) -> list[dict]:
    out: list[dict] = []
    base = campaign_dir(cid) / "adventures"
    if not base.exists():
        return out
    for child in base.iterdir():
        if child.is_dir():
            meta = _read_json(child / "adventure.json")
            if meta:
                out.append(meta)
    out.sort(key=lambda m: m.get("createdAt", ""))
    return out


# ── Creation ──────────────────────────────────────────────────────

async def create_campaign(name: str) -> str:
    cid = _uuid()
    await db.create_campaign_db(campaign_db_path(cid))
    (campaign_dir(cid) / "portraits").mkdir(parents=True, exist_ok=True)
    _write_json(campaign_json_path(cid), {"id": cid, "name": name, "createdAt": _now()})
    return cid


async def create_adventure(cid: str, name: str) -> str:
    aid = _uuid()
    await db.create_adventure_db(adventure_db_path(cid, aid))
    (adventure_dir(cid, aid) / "portraits").mkdir(parents=True, exist_ok=True)
    _write_json(adventure_json_path(cid, aid), {
        "id": aid, "name": name, "createdAt": _now(), "lastPlayedAt": _now(),
        "day": 1, "location": "", "pcName": "", "pcPortrait": "", "partyPortraits": [],
    })
    return aid


async def refresh_active_adventure_meta() -> None:
    """Rewrite the active adventure's json sidecar from its live DB so the
    Save/Load cards (PC + party portraits, location, last played) stay current.
    Only the active adventure is attached, so only its sidecar is refreshed."""
    from sqlalchemy import select

    from server.db.models import AppState, ChatMessage, PartyMember, PlayerCharacter

    async with db.new_session() as s:
        st = (await s.execute(select(AppState))).scalars().first()
        if not st or not st.active_campaign_id or not st.active_adventure_id:
            return
        cid, aid = st.active_campaign_id, st.active_adventure_id
        pc = (await s.execute(select(PlayerCharacter))).scalars().first()
        members = (
            await s.execute(select(PartyMember).where(PartyMember.in_party == True))  # noqa: E712
        ).scalars().all()
        location = (
            await s.execute(
                select(ChatMessage.location)
                .where(ChatMessage.location.is_not(None))
                .order_by(ChatMessage.id.desc())
            )
        ).scalars().first()

    meta = _read_json(adventure_json_path(cid, aid)) or {}
    pc_info = pc.basic_info if pc else {}
    meta.update({
        "lastPlayedAt": _now(),
        "pcName": pc_info.get("name", "") or "",
        "pcPortrait": pc_info.get("portrait", "") or "",
        "partyPortraits": [
            m.basic_info.get("portrait", "") for m in members if m.basic_info.get("portrait")
        ],
        "location": location or meta.get("location", ""),
    })
    _write_json(adventure_json_path(cid, aid), meta)


def read_adventure_meta(cid: str, aid: str) -> dict | None:
    return _read_json(adventure_json_path(cid, aid))


def write_adventure_meta(cid: str, aid: str, meta: dict) -> None:
    _write_json(adventure_json_path(cid, aid), meta)


async def create_default_scope() -> tuple[str, str]:
    """Create the empty default Campaign + Adventure structure. Data (seed or
    legacy migration) is loaded by the caller after the DBs are attached."""
    cid = await create_campaign("Default Campaign")
    aid = await create_adventure(cid, "Adventure 1")
    log.info("Created default scope: campaign=%s adventure=%s", cid, aid)
    return cid, aid


# ── Legacy migration (single wayward.db → split scopes) ───────────

# JSON-typed columns per legacy table (raw SELECT returns them as text).
_JSON_COLS = {
    "player_characters": {"basic_info", "equipment"},
    "party_members": {"basic_info", "equipment", "field_skill"},
    "lorebook_entries": {"keywords"},
    "lorebook_config": {"injection_order", "injection_position"},
    "quests": {"related_lore"},
    "chat_messages": {"applied_inventory_deltas", "applied_equipment_changes"},
    "worldbuilding_proposals": {"payload"},
}
# DateTime columns (legacy stores them as text; the ORM type needs datetime).
_DT_COLS = {
    "chat_messages": {"created_at"},
    "worldbuilding_proposals": {"created_at"},
}


def _parse_dt(v):
    if isinstance(v, str):
        try:
            return datetime.datetime.fromisoformat(v)
        except ValueError:
            return None
    return v


async def _read_legacy_table(conn, table: str) -> list[dict]:
    try:
        rows = (await conn.execute(text(f"SELECT * FROM {table}"))).mappings().all()
    except Exception:
        return []
    json_cols = _JSON_COLS.get(table, set())
    dt_cols = _DT_COLS.get(table, set())
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        for col in json_cols:
            v = d.get(col)
            if isinstance(v, str):
                try:
                    d[col] = json.loads(v)
                except json.JSONDecodeError:
                    d[col] = None
        for col in dt_cols:
            d[col] = _parse_dt(d.get(col))
        out.append(d)
    return out


async def migrate_legacy() -> None:
    """Copy the legacy single wayward.db into the (now attached) default scope.

    Reads the old DB with a throwaway engine and re-inserts via the live session,
    so schema-tagged models route each row to app/campaign/adventure.
    """
    from server.db.models import (
        ChatMessage, InventoryStack, LorebookConfig, LorebookEntry, NarratorConfig,
        OpenRouterSettings, PartyMember, PlayerCharacter, Quest, QuestObjective,
        StorySummary, WorldbuildingProposal,
    )

    leg = create_async_engine(f"sqlite+aiosqlite:///{db.LEGACY_DB_PATH.as_posix()}", echo=False)
    try:
        async with leg.connect() as c:
            tables = {
                t: await _read_legacy_table(c, t)
                for t in (
                    "openrouter_settings", "narrator_configs", "lorebook_entries",
                    "lorebook_config", "player_characters", "party_members", "quests",
                    "quest_objectives", "inventory_stacks", "story_summaries",
                    "chat_messages", "worldbuilding_proposals",
                )
            }
    finally:
        await leg.dispose()

    def _pick(row: dict, cols: set[str]) -> dict:
        return {k: v for k, v in row.items() if k in cols}

    async with db.new_session() as s:
        for row in tables["openrouter_settings"]:
            s.add(OpenRouterSettings(**_pick(row, {c.name for c in OpenRouterSettings.__table__.columns})))
        for row in tables["narrator_configs"]:
            s.add(NarratorConfig(**_pick(row, {c.name for c in NarratorConfig.__table__.columns})))
        for row in tables["lorebook_entries"]:
            s.add(LorebookEntry(**_pick(row, {c.name for c in LorebookEntry.__table__.columns})))
        for row in tables["lorebook_config"]:
            s.add(LorebookConfig(**_pick(row, {c.name for c in LorebookConfig.__table__.columns})))
        for row in tables["player_characters"]:
            s.add(PlayerCharacter(**_pick(row, {c.name for c in PlayerCharacter.__table__.columns})))
        for row in tables["party_members"]:
            s.add(PartyMember(**_pick(row, {c.name for c in PartyMember.__table__.columns})))
        for row in tables["quests"]:
            s.add(Quest(**_pick(row, {c.name for c in Quest.__table__.columns})))
        for row in tables["quest_objectives"]:
            s.add(QuestObjective(**_pick(row, {c.name for c in QuestObjective.__table__.columns})))
        for row in tables["inventory_stacks"]:
            s.add(InventoryStack(**_pick(row, {c.name for c in InventoryStack.__table__.columns})))
        for row in tables["story_summaries"]:
            s.add(StorySummary(**_pick(row, {c.name for c in StorySummary.__table__.columns})))
        for row in tables["chat_messages"]:
            s.add(ChatMessage(**_pick(row, {c.name for c in ChatMessage.__table__.columns})))
        for row in tables["worldbuilding_proposals"]:
            s.add(WorldbuildingProposal(**_pick(row, {c.name for c in WorldbuildingProposal.__table__.columns})))
        await s.commit()

    counts = {t: len(rows) for t, rows in tables.items() if rows}
    log.info("Migrated legacy wayward.db into default scope: %s", counts)
