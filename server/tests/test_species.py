"""Species/Creature-template field composition — see CLAUDE.md >
Species & Creature Templates."""

from server.ai.species import (
    SPECIES_FIELDS,
    compose_species_content,
    merge_species_fields,
    migrate_legacy_species_fields,
)


# ── Pure: composer ──────────────────────────────────────────────────

def test_compose_empty_is_blank():
    assert compose_species_content({}) == ""
    assert compose_species_content({"overview": "", "typicalGear": "   "}) == ""


def test_compose_skips_empty_fields_and_orders_by_field_list():
    block = compose_species_content({
        "nameExamples": "Grak, Thok",
        "overview": "A hulking forest guardian.",
    })
    assert block == "Overview: A hulking forest guardian.\n\nName Examples: Grak, Thok"


def test_compose_all_fields_labeled():
    fields = {key: f"[{key}]" for key, _label in SPECIES_FIELDS}
    block = compose_species_content(fields)
    for key, label in SPECIES_FIELDS:
        assert f"{label}: [{key}]" in block


# ── Pure: partial merge ─────────────────────────────────────────────

def test_merge_keeps_untouched_fields_and_drops_unknown_keys():
    existing = {"overview": "Old overview.", "typicalGear": "Claws."}
    merged = merge_species_fields(existing, {"overview": "New overview.", "bogus": "x"})
    assert merged == {"overview": "New overview.", "typicalGear": "Claws."}
    assert "bogus" not in merged


def test_merge_none_partial_is_a_noop():
    existing = {"overview": "Old overview."}
    assert merge_species_fields(existing, None) == existing


def test_merge_none_existing_starts_fresh():
    assert merge_species_fields(None, {"overview": "Fresh."}) == {"overview": "Fresh."}


# ── Pure: legacy content → overview migration ───────────────────────

def test_migrate_legacy_seeds_overview_once_then_idempotent():
    assert migrate_legacy_species_fields(None, "A shadow that hunts by scent.") == {
        "overview": "A shadow that hunts by scent."
    }
    assert migrate_legacy_species_fields(None, "") == {}  # nothing to migrate
    assert migrate_legacy_species_fields({"overview": "Set already"}, "Old text") == {
        "overview": "Set already"
    }


from sqlalchemy import select

from server.tests.conftest import run


# ── Integration: DB migration (monsters → species) ──────────────────

def test_migrate_species_lore_recategorizes_and_renames_config_key(client):
    from server.db.database import migrate_species_lore, new_session
    from server.db.models import LorebookConfig, LorebookEntry

    async def seed_legacy():
        async with new_session() as s:
            s.add(LorebookEntry(title="Dire Wolf", content="A large wolf.", cat="monsters"))
            cfg = (await s.execute(select(LorebookConfig))).scalars().first()
            order = dict(cfg.injection_order or {})
            order["monsters"] = order.pop("species", 40)
            cfg.injection_order = order
            position = dict(cfg.injection_position or {})
            position["monsters"] = position.pop("species", "top")
            cfg.injection_position = position
            await s.commit()
    run(seed_legacy())

    run(migrate_species_lore())

    async def check():
        async with new_session() as s:
            entry = (await s.execute(
                select(LorebookEntry).where(LorebookEntry.title == "Dire Wolf")
            )).scalars().first()
            cfg = (await s.execute(select(LorebookConfig))).scalars().first()
            return entry, cfg
    entry, cfg = run(check())
    assert entry.cat == "species"
    assert entry.species_fields == {"overview": "A large wolf."}
    assert entry.content == "Overview: A large wolf."
    assert "species" in cfg.injection_order and "monsters" not in cfg.injection_order
    assert "species" in cfg.injection_position and "monsters" not in cfg.injection_position

    # Idempotent: running again changes nothing further and doesn't error.
    run(migrate_species_lore())
    entry2, cfg2 = run(check())
    assert entry2.cat == "species"
    assert entry2.species_fields == {"overview": "A large wolf."}
    assert entry2.content == "Overview: A large wolf."
    assert "monsters" not in cfg2.injection_order


# ── Integration: /lore API composes + merges species fields ────────

def test_lore_species_create_composes_content(client):
    res = client.post("/api/lore", json={
        "title": "Dire Wolf",
        "content": "",
        "cat": "species",
        "keywords": ["wolf"],
        "speciesFields": {
            "overview": "A larger, more cunning cousin of the common wolf.",
            "dangerCombat": "Hunts in coordinated packs; flees if its alpha falls.",
        },
    })
    assert res.status_code == 201, res.text
    body = res.json()
    entry_id = body["id"]
    assert body["speciesFields"]["overview"].startswith("A larger")
    assert body["content"] == (
        "Overview: A larger, more cunning cousin of the common wolf.\n\n"
        "Danger & Combat Notes: Hunts in coordinated packs; flees if its alpha falls."
    )

    # Partial PUT merges into existing fields rather than replacing them.
    put = client.put(f"/api/lore/{entry_id}", json={
        "speciesFields": {"typicalGear": "None — relies on claw and fang."},
    }).json()
    assert put["speciesFields"]["overview"].startswith("A larger")  # untouched
    assert put["speciesFields"]["typicalGear"] == "None — relies on claw and fang."
    assert "Typical Gear: None" in put["content"]

    # Non-species entries never carry speciesFields.
    other = client.post("/api/lore", json={"title": "A Cave", "content": "Dark.", "cat": "world"}).json()
    assert other["speciesFields"] is None
    client.delete(f"/api/lore/{other['id']}")
    client.delete(f"/api/lore/{entry_id}")
