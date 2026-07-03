"""Multi-database storage: app.db + per-campaign + per-adventure SQLite files.

The world (campaign) and each save file (adventure) live in their own .db files
on disk so they're modular and shareable. At runtime we open ONE engine on
app.db and ATTACH the *active* campaign.db (AS campaign) and adventure.db
(AS adventure) onto every connection. Models are schema-tagged (see models.py),
so a single session reads/writes all three transparently — `select(LorebookEntry)`
resolves to `campaign.lorebook_entries`, `select(PlayerCharacter)` to
`adventure.player_characters`, etc.

Switching campaign/adventure just swaps the attached paths and disposes pooled
connections so they re-attach. See storage.py for the folder layout + bootstrap.
"""

import uuid
from pathlib import Path

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base

SERVER_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SERVER_DIR / "data"
APP_DB_PATH = DATA_DIR / "app.db"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
LEGACY_DB_PATH = SERVER_DIR.parent / "wayward.db"

# Active scope paths, read by the ATTACH listener on every new connection.
_active_campaign_path: Path | None = None
_active_adventure_path: Path | None = None

engine = None
async_session: async_sessionmaker | None = None


def _tables_for_schema(schema: str | None):
    return [t for t in Base.metadata.tables.values() if t.schema == schema]


def _attach(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    if _active_campaign_path is not None:
        cur.execute("ATTACH DATABASE ? AS campaign", (_active_campaign_path.as_posix(),))
    if _active_adventure_path is not None:
        cur.execute("ATTACH DATABASE ? AS adventure", (_active_adventure_path.as_posix(),))
    cur.close()


def _build_engine() -> None:
    global engine, async_session
    eng = create_async_engine(f"sqlite+aiosqlite:///{APP_DB_PATH.as_posix()}", echo=False)
    event.listen(eng.sync_engine, "connect", _attach)
    engine = eng
    async_session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session


def new_session() -> AsyncSession:
    """Open a session on the current engine. Use this (not a top-level
    `from database import async_session`) so callers always get the live
    sessionmaker after init/switch."""
    return async_session()


async def switch_active(campaign_path: Path | None, adventure_path: Path | None) -> None:
    """Point the engine at a different campaign/adventure (between turns only)."""
    global _active_campaign_path, _active_adventure_path
    _active_campaign_path = campaign_path
    _active_adventure_path = adventure_path
    if engine is not None:
        await engine.dispose()  # pooled conns re-attach the new paths on reconnect
        if adventure_path is not None:
            await _run_scope_migrations()  # bring this scope's schema up to date


# ── Per-file table creation ───────────────────────────────────────

async def _create_in_file(db_path: Path, schema: str) -> None:
    """Create a schema's tables inside a (possibly new) .db file.

    Uses a throwaway engine that attaches the target file under `schema`, so the
    schema-qualified models materialise in the right file.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_async_engine(f"sqlite+aiosqlite:///{APP_DB_PATH.as_posix()}", echo=False)

    def _attach_one(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute(f"ATTACH DATABASE ? AS {schema}", (db_path.as_posix(),))
        cur.close()

    event.listen(eng.sync_engine, "connect", _attach_one)
    async with eng.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_tables_for_schema(schema)))
    await eng.dispose()


async def create_campaign_db(db_path: Path) -> None:
    await _create_in_file(db_path, "campaign")


async def create_adventure_db(db_path: Path) -> None:
    await _create_in_file(db_path, "adventure")


# ── Startup ───────────────────────────────────────────────────────

async def init_db() -> None:
    """Boot the storage layer: ensure app.db, resolve/create the active scope,
    then attach it. Delegates default-scope creation/migration to storage.py."""
    global _active_campaign_path, _active_adventure_path
    _active_campaign_path = None  # don't attach anything while we set up app.db
    _active_adventure_path = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)

    _build_engine()
    # app.db tables (no active scope attached yet).
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_tables_for_schema(None)))
    await _run_app_migrations()

    from server.db import storage  # late import (storage imports this module)
    from server.db.models import AppState

    async with async_session() as s:
        st = (await s.execute(select(AppState))).scalars().first()
        campaign_id = st.active_campaign_id if st else None
        adventure_id = st.active_adventure_id if st else None

    valid = bool(
        campaign_id and adventure_id
        and storage.campaign_dir(campaign_id).exists()
        and storage.adventure_dir(campaign_id, adventure_id).exists()
    )
    source: str | None = None
    if not valid:
        # Create the empty default campaign + adventure structure (folders, db
        # files with tables, json sidecars). Data is loaded after we attach.
        campaign_id, adventure_id = await storage.create_default_scope()
        source = "legacy" if LEGACY_DB_PATH.exists() else "fresh"
        async with async_session() as s:
            st = (await s.execute(select(AppState))).scalars().first()
            if not st:
                st = AppState(id=1)
                s.add(st)
            st.active_campaign_id = campaign_id
            st.active_adventure_id = adventure_id
            await s.commit()

    await switch_active(
        storage.campaign_db_path(campaign_id),
        storage.adventure_db_path(campaign_id, adventure_id),
    )
    await _run_scope_migrations()

    # Now the new campaign/adventure DBs are attached — load their initial data.
    if source == "legacy":
        await storage.migrate_legacy()
    elif source == "fresh":
        from server.db.seed import seed_defaults
        await seed_defaults()

    # Convert any catalog-id equipment + inventory stacks (from seed/legacy) into
    # non-stacking item instances. Idempotent — safe on already-migrated data.
    if source in ("legacy", "fresh"):
        await migrate_to_item_instances()


async def _run_app_migrations() -> None:
    """Additive ALTERs for columns added to app.db (openrouter_settings) after a
    user's app.db was first created."""
    migrations = [
        ("openrouter_settings", "summary_threshold", "ALTER TABLE openrouter_settings ADD COLUMN summary_threshold FLOAT DEFAULT 0.7"),
        ("openrouter_settings", "summary_model_id", "ALTER TABLE openrouter_settings ADD COLUMN summary_model_id VARCHAR DEFAULT ''"),
        ("openrouter_settings", "action_suggestions_model_id", "ALTER TABLE openrouter_settings ADD COLUMN action_suggestions_model_id VARCHAR DEFAULT ''"),
    ]
    async with engine.begin() as conn:
        for table, column, ddl in migrations:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            cols = [row[1] for row in result.fetchall()]
            if column not in cols:
                await conn.execute(text(ddl))


async def _run_scope_migrations() -> None:
    """Additive ALTERs for columns added to campaign/adventure schemas after a
    user's files were first created. (New files are created complete, so this is
    a no-op for them; kept for forward compatibility.)"""
    migrations: list[tuple[str, str, str]] = [
        ("adventure.chat_messages", "day", "ALTER TABLE adventure.chat_messages ADD COLUMN day INTEGER"),
        ("campaign.narrator_configs", "action_suggestions_enabled", "ALTER TABLE campaign.narrator_configs ADD COLUMN action_suggestions_enabled INTEGER DEFAULT 0"),
        ("campaign.lorebook_entries", "scenario_fields", "ALTER TABLE campaign.lorebook_entries ADD COLUMN scenario_fields JSON"),
    ]
    async with engine.begin() as conn:
        for qualified, column, ddl in migrations:
            schema, table = qualified.split(".", 1)
            result = await conn.execute(text(f"PRAGMA {schema}.table_info({table})"))
            cols = [row[1] for row in result.fetchall()]
            if column not in cols:
                await conn.execute(text(ddl))
    await migrate_to_item_instances()


async def migrate_to_item_instances() -> None:
    """One-time, idempotent back-fill from legacy InventoryStack + catalog-id
    equipment slots to ItemInstance.

    - Each legacy inventory stack becomes instance row(s): Equipment splits into
      ``count`` rows of 1; stackables stay one row with the count. Migrated stacks
      are then deleted, so re-running is a no-op.
    - Each character equipment slot still holding a *catalog* item id is given a
      freshly-minted instance and rewritten to that instance id. Slots already
      holding an instance id are left alone — safe to call repeatedly.
    """
    if async_session is None or _active_adventure_path is None:
        return

    async with engine.begin() as conn:
        res = await conn.execute(text("PRAGMA adventure.table_info(item_instances)"))
        if not res.fetchall():
            await conn.execute(text(
                "CREATE TABLE adventure.item_instances "
                "(id VARCHAR NOT NULL PRIMARY KEY, item_id VARCHAR NOT NULL, count INTEGER DEFAULT 1)"
            ))

    from server.db.models import (
        InventoryStack, ItemInstance, LorebookEntry, PartyMember, PlayerCharacter,
    )

    async with async_session() as s:
        catalog = (await s.execute(
            select(LorebookEntry).where(LorebookEntry.cat == "items")
        )).scalars().all()
        item_type = {c.id: (c.item_type or "") for c in catalog}
        catalog_ids = set(item_type.keys())
        instance_ids = {
            i.id for i in (await s.execute(select(ItemInstance))).scalars().all()
        }

        # Legacy inventory stacks → instances, then consume the stacks.
        stacks = (await s.execute(select(InventoryStack))).scalars().all()
        for st in stacks:
            if item_type.get(st.item_id) == "Equipment":
                for _ in range(max(1, st.count)):
                    inst = ItemInstance(id=str(uuid.uuid4()), item_id=st.item_id, count=1)
                    s.add(inst)
                    instance_ids.add(inst.id)
            else:
                inst = ItemInstance(id=str(uuid.uuid4()), item_id=st.item_id, count=max(1, st.count))
                s.add(inst)
                instance_ids.add(inst.id)
            await s.delete(st)

        # Equipment slots that still hold a catalog item id → mint an instance.
        chars = [
            *(await s.execute(select(PlayerCharacter))).scalars().all(),
            *(await s.execute(select(PartyMember))).scalars().all(),
        ]
        for ch in chars:
            equipment = dict(ch.equipment or {})
            changed = False
            for slot, val in list(equipment.items()):
                if not val or val in instance_ids:
                    continue
                if val in catalog_ids:
                    inst = ItemInstance(id=str(uuid.uuid4()), item_id=val, count=1)
                    s.add(inst)
                    instance_ids.add(inst.id)
                    equipment[slot] = inst.id
                    changed = True
                # else: dangling reference — leave as-is
            if changed:
                ch.equipment = equipment

        await s.commit()
