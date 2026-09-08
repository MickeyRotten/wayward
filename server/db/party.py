"""Runtime party layer — joins per-adventure ``PartyBinding`` rows (DB) with
portable character identity files (see server/db/characters.py) into the
``RuntimeCharacter`` objects the rest of the app consumes.

Identity (basicInfo/fieldSkill/portraits) lives on disk and is shared/reusable;
this module owns the per-adventure state (role, equipment, in_party,
last_spoke_turn) and the create/read/write helpers that keep the two in sync.
``RuntimeCharacter.id`` is the *character id* (the stable identity key referenced
across the app — equip changes, client selection, …); the binding id is internal.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import characters as char_files
from server.db.models import PartyBinding


@dataclass
class RuntimeCharacter:
    id: str                 # character id (identity file) — the app-wide handle
    binding_id: str         # PartyBinding row id (internal)
    type: str               # persona | character
    role: str               # pc | member
    basic_info: dict        # LEGACY compatibility projection (see characters.py)
    blocks: list            # the real data — toggleable block tree
    equipment: dict
    in_party: bool
    last_spoke_turn: int

    @property
    def field_skill(self) -> dict:
        """Legacy shape for call sites not yet block-aware — the Strengths
        block's content, split back into {name, description} best-effort."""
        strengths = (self.basic_info or {}).get("strengths", "")
        name, _, desc = strengths.partition(" — ")
        return {"name": name, "description": desc or strengths}


def _compose(binding: PartyBinding, identity: dict | None) -> RuntimeCharacter:
    identity = identity or {}
    return RuntimeCharacter(
        id=binding.character_id,
        binding_id=binding.id,
        type=identity.get("type", "persona" if binding.role == "pc" else "character"),
        role=binding.role,
        basic_info=dict(identity.get("basicInfo") or {}),
        blocks=list(identity.get("blocks") or []),
        equipment=dict(binding.equipment or {}),
        in_party=bool(binding.in_party),
        last_spoke_turn=binding.last_spoke_turn or 0,
    )


# ── Binding accessors ─────────────────────────────────────────────

async def binding_for(session: AsyncSession, character_id: str) -> PartyBinding | None:
    return (await session.execute(
        select(PartyBinding).where(PartyBinding.character_id == character_id)
    )).scalars().first()


async def pc_binding(session: AsyncSession) -> PartyBinding | None:
    return (await session.execute(
        select(PartyBinding).where(PartyBinding.role == "pc")
    )).scalars().first()


async def member_bindings(session: AsyncSession) -> list[PartyBinding]:
    return list((await session.execute(
        select(PartyBinding).where(PartyBinding.role == "member")
        .order_by(PartyBinding.sort_order, PartyBinding.id)
    )).scalars().all())


async def all_bindings(session: AsyncSession) -> list[PartyBinding]:
    return list((await session.execute(select(PartyBinding))).scalars().all())


# ── Composite loaders ─────────────────────────────────────────────

async def load_pc(session: AsyncSession) -> RuntimeCharacter | None:
    b = await pc_binding(session)
    if b is None:
        return None
    return _compose(b, char_files.read_character(b.character_id))


async def load_party(session: AsyncSession) -> list[RuntimeCharacter]:
    """All party-member characters (in- and out-of-party), in list order."""
    out: list[RuntimeCharacter] = []
    for b in await member_bindings(session):
        out.append(_compose(b, char_files.read_character(b.character_id)))
    return out


async def load_character(session: AsyncSession, character_id: str) -> RuntimeCharacter | None:
    b = await binding_for(session, character_id)
    if b is None:
        return None
    return _compose(b, char_files.read_character(character_id))


async def load_all(session: AsyncSession) -> list[RuntimeCharacter]:
    """PC + every party member, composed."""
    out: list[RuntimeCharacter] = []
    pc = await load_pc(session)
    if pc:
        out.append(pc)
    out.extend(await load_party(session))
    return out


# ── Per-adventure state writers (mutate the binding) ──────────────

async def set_equipment(session: AsyncSession, character_id: str, equipment: dict) -> bool:
    b = await binding_for(session, character_id)
    if b is None:
        return False
    b.equipment = dict(equipment)  # reassign so SQLAlchemy tracks the JSON change
    return True


async def set_in_party(session: AsyncSession, character_id: str, in_party: bool) -> bool:
    b = await binding_for(session, character_id)
    if b is None:
        return False
    b.in_party = bool(in_party)
    return True


async def set_last_spoke(session: AsyncSession, character_id: str, turn: int) -> bool:
    b = await binding_for(session, character_id)
    if b is None:
        return False
    b.last_spoke_turn = turn
    return True


async def active_count(session: AsyncSession) -> int:
    return (await session.execute(
        select(func.count()).select_from(PartyBinding)
        .where(PartyBinding.role == "member", PartyBinding.in_party == True)  # noqa: E712
    )).scalar() or 0


# ── Identity writers (write the file) + create/bind orchestration ─

def _fold_field_skill(basic_info: dict | None, field_skill: dict | None) -> dict | None:
    """Legacy wire shape {fieldSkillName, fieldSkillDescription-ish object}
    folds into basicInfo.strengths, same rule the old migrate_basic_info used."""
    if not field_skill or (basic_info or {}).get("strengths"):
        return basic_info
    n, d = str(field_skill.get("name") or "").strip(), str(field_skill.get("description") or "").strip()
    if not (n or d):
        return basic_info
    out = dict(basic_info or {})
    out["strengths"] = f"{n} — {d}" if n and d else (d or n)
    return out


async def set_pc_identity(
    session: AsyncSession, basic_info: dict | None, field_skill: dict | None = None
) -> RuntimeCharacter:
    """Upsert the player character: create the persona file + pc binding on first
    call; otherwise patch the identity file. Equipment is set separately."""
    basic_info = _fold_field_skill(basic_info, field_skill)
    b = await pc_binding(session)
    if b is None:
        identity = char_files.create_character("persona", basic_info)
        b = PartyBinding(character_id=identity["id"], role="pc", in_party=True, sort_order=0)
        session.add(b)
        await session.flush()
    else:
        identity = char_files.update_identity(b.character_id, basic_info) \
            or char_files.create_character("persona", basic_info, cid=b.character_id)
    return _compose(b, identity)


async def _next_member_order(session: AsyncSession) -> int:
    mx = (await session.execute(
        select(func.coalesce(func.max(PartyBinding.sort_order), -1))
        .where(PartyBinding.role == "member")
    )).scalar()
    return (mx or 0) + 1


async def add_member(
    session: AsyncSession,
    basic_info: dict | None = None,
    in_party: bool = True,
    character_id: str | None = None,
    field_skill: dict | None = None,
) -> RuntimeCharacter:
    """Create a new character file + a member binding for this adventure."""
    basic_info = _fold_field_skill(basic_info, field_skill)
    identity = char_files.create_character("character", basic_info, cid=character_id)
    b = PartyBinding(
        character_id=identity["id"], role="member",
        in_party=in_party, sort_order=await _next_member_order(session),
    )
    session.add(b)
    await session.flush()
    return _compose(b, identity)


async def bind_existing(
    session: AsyncSession, character_id: str, in_party: bool = True
) -> RuntimeCharacter | None:
    """Bind an EXISTING library character into this adventure as a party member."""
    identity = char_files.read_character(character_id)
    if identity is None:
        return None
    b = PartyBinding(
        character_id=character_id, role="member",
        in_party=in_party, sort_order=await _next_member_order(session),
    )
    session.add(b)
    await session.flush()
    return _compose(b, identity)


async def update_member_identity(
    session: AsyncSession, character_id: str, basic_info: dict | None,
    field_skill: dict | None = None,
) -> RuntimeCharacter | None:
    b = await binding_for(session, character_id)
    if b is None or b.role != "member":
        return None
    basic_info = _fold_field_skill(basic_info, field_skill)
    identity = char_files.update_identity(character_id, basic_info)
    if identity is None:
        return None
    return _compose(b, identity)


async def remove_member(session: AsyncSession, character_id: str) -> bool:
    """Unbind a member from this adventure (the identity file is left in the
    library). Returns True if a binding was removed."""
    b = await binding_for(session, character_id)
    if b is None or b.role != "member":
        return False
    await session.delete(b)
    return True
