from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DB_PATH = Path(__file__).resolve().parent.parent.parent / "wayward.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session


async def create_tables():
    from server.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Lightweight migrations for columns added after initial schema
    await _run_migrations()


async def _run_migrations():
    """Add columns that may be missing from existing databases."""
    migrations = [
        # Task 5.1: speaker column on chat_messages
        ("chat_messages", "speaker", "ALTER TABLE chat_messages ADD COLUMN speaker VARCHAR DEFAULT 'narrator'"),
    ]
    async with engine.begin() as conn:
        for table, column, ddl in migrations:
            # Check if column already exists
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in result.fetchall()]
            if column not in columns:
                await conn.execute(text(ddl))
