"""The Scenario (structured fields → the permanent locked World entry) and the
Lorebook (config + entry CRUD)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.scenario import compose_scenario_content, migrate_legacy_fields
from server.api.schemas import (
    LorebookConfigSchema,
    LorebookConfigUpdate,
    LorebookEntryCreate,
    LorebookEntrySchema,
    LorebookEntryUpdate,
    ScenarioResponse,
    ScenarioUpdate,
)
from server.db.database import get_session
from server.db.models import LorebookConfig, LorebookEntry

router = APIRouter()


# ── Scenario ───────────────────────────────────────────────────────

async def _get_or_create_scenario_entry(session: AsyncSession) -> LorebookEntry:
    """Fetch the Scenario LorebookEntry — matched by title, case-insensitively,
    the same lookup server/ai/planner.py's set_scenario/get_scenario tools
    already use. Creates it if a from-scratch campaign somehow lacks it."""
    scn = (await session.execute(
        select(LorebookEntry).where(func.lower(LorebookEntry.title) == "scenario")
    )).scalars().first()
    if not scn:
        scn = LorebookEntry(title="Scenario", cat="world", permanent=True, locked=True)
        session.add(scn)
        await session.commit()
        await session.refresh(scn)
    return scn


def _scenario_to_schema(scn: LorebookEntry) -> ScenarioResponse:
    fields = scn.scenario_fields or {}
    return ScenarioResponse(
        setting=fields.get("setting", ""),
        historyBrief=fields.get("historyBrief", ""),
        species=fields.get("species", ""),
        geography=fields.get("geography", ""),
        techAndMagic=fields.get("techAndMagic", ""),
        other=fields.get("other", ""),
    )


@router.get("/scenario", response_model=ScenarioResponse)
async def get_scenario(session: AsyncSession = Depends(get_session)):
    scn = await _get_or_create_scenario_entry(session)
    migrated = migrate_legacy_fields(scn.scenario_fields, scn.content)
    if migrated != (scn.scenario_fields or {}):
        scn.scenario_fields = migrated
        await session.commit()
        await session.refresh(scn)
    return _scenario_to_schema(scn)


@router.put("/scenario", response_model=ScenarioResponse)
async def update_scenario(
    data: ScenarioUpdate,
    session: AsyncSession = Depends(get_session),
):
    scn = await _get_or_create_scenario_entry(session)
    fields = dict(scn.scenario_fields or {})
    if data.setting is not None:
        fields["setting"] = data.setting
    if data.historyBrief is not None:
        fields["historyBrief"] = data.historyBrief
    if data.species is not None:
        fields["species"] = data.species
    if data.geography is not None:
        fields["geography"] = data.geography
    if data.techAndMagic is not None:
        fields["techAndMagic"] = data.techAndMagic
    if data.other is not None:
        fields["other"] = data.other
    scn.scenario_fields = fields
    scn.content = compose_scenario_content(fields)
    # Defensive: keep the invariants the prompt-injection pipeline depends on,
    # in case a row predates these being set correctly.
    scn.cat = "world"
    scn.permanent = True
    scn.locked = True
    await session.commit()
    await session.refresh(scn)
    return _scenario_to_schema(scn)


# ── Lorebook ─────────────────────────────────────────────────────

def _lore_to_schema(entry: LorebookEntry) -> LorebookEntrySchema:
    return LorebookEntrySchema(
        id=entry.id,
        title=entry.title,
        content=entry.content,
        keywords=entry.keywords or [],
        enabled=bool(entry.enabled),
        permanent=bool(entry.permanent),
        locked=bool(entry.locked),
        cat=entry.cat,
    )


@router.get("/lore/config", response_model=LorebookConfigSchema)
async def get_lore_config(session: AsyncSession = Depends(get_session)):
    cfg = (await session.execute(select(LorebookConfig))).scalars().first()
    if not cfg:
        cfg = LorebookConfig()
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return LorebookConfigSchema(
        injectionOrder=cfg.injection_order,
        injectionPosition=cfg.injection_position,
        scanDepth=int(getattr(cfg, "scan_depth", 3) or 0),
    )


@router.put("/lore/config", response_model=LorebookConfigSchema)
async def update_lore_config(
    data: LorebookConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    cfg = (await session.execute(select(LorebookConfig))).scalars().first()
    if not cfg:
        cfg = LorebookConfig()
        session.add(cfg)
    if data.injectionOrder is not None:
        cfg.injection_order = data.injectionOrder
    if data.injectionPosition is not None:
        cfg.injection_position = data.injectionPosition
    if data.scanDepth is not None:
        cfg.scan_depth = max(0, min(int(data.scanDepth), 20))
    await session.commit()
    await session.refresh(cfg)
    return LorebookConfigSchema(
        injectionOrder=cfg.injection_order,
        injectionPosition=cfg.injection_position,
        scanDepth=int(getattr(cfg, "scan_depth", 3) or 0),
    )


@router.get("/lore", response_model=list[LorebookEntrySchema])
async def list_lore_entries(
    cat: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(LorebookEntry)
    if cat:
        query = query.where(LorebookEntry.cat == cat)
    entries = (await session.execute(query)).scalars().all()
    return [_lore_to_schema(e) for e in entries]


@router.post("/lore", response_model=LorebookEntrySchema, status_code=201)
async def create_lore_entry(
    data: LorebookEntryCreate,
    session: AsyncSession = Depends(get_session),
):
    entry = LorebookEntry(
        title=data.title,
        content=data.content,
        keywords=data.keywords,
        enabled=data.enabled,
        permanent=data.permanent,
        cat=data.cat,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)


@router.get("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def get_lore_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    return _lore_to_schema(entry)


@router.put("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def update_lore_entry(
    entry_id: str,
    data: LorebookEntryUpdate,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    if data.title is not None:
        entry.title = data.title
    if data.content is not None:
        entry.content = data.content
    if data.keywords is not None:
        entry.keywords = data.keywords
    if data.enabled is not None:
        entry.enabled = data.enabled
    if data.permanent is not None:
        entry.permanent = data.permanent
    if data.cat is not None:
        entry.cat = data.cat
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)


@router.delete("/lore/{entry_id}", status_code=204)
async def delete_lore_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    if entry.locked:
        raise HTTPException(403, "This entry is locked and cannot be deleted")
    await session.delete(entry)
    await session.commit()
