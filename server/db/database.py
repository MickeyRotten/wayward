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


async def _run_scope_migrations() -> None:
    """Additive ALTERs for columns added to campaign/adventure schemas after a
    user's files were first created. (New files are created complete, so this is
    a no-op for them; kept for forward compatibility.)"""
    migrations: list[tuple[str, str, str]] = [
        # (schema.table, column, DDL) — e.g.
        # ("adventure.chat_messages", "mode", "ALTER TABLE adventure.chat_messages ADD COLUMN mode VARCHAR DEFAULT 'narrator'"),
    ]
    if not migrations:
        return
    async with engine.begin() as conn:
        for qualified, column, ddl in migrations:
            schema, table = qualified.split(".", 1)
            result = await conn.execute(text(f"PRAGMA {schema}.table_info({table})"))
            cols = [row[1] for row in result.fetchall()]
            if column not in cols:
                await conn.execute(text(ddl))
