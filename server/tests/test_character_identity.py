"""Unified character identity schema — the migrate_basic_info seam and the
character-file read/write round-trip (see the Character Unification plan)."""

from server.db import characters as char_files
from server.db.characters import migrate_basic_info


# ── Pure: old-shape → new-shape migration ──────────────────────────

def test_migrate_maps_old_keys_to_new():
    got = migrate_basic_info(
        {
            "name": "Varena", "gender": "female", "species": "elf",
            "age": 120, "heightCm": 170, "weightKg": 60,
            "description": "Tall and watchful.", "personality": "Wry.",
            "drive": "Protect the weak.", "likes": "rain", "dislikes": "liars",
            "other": "Left-handed.",
        },
        {"name": "Sharpshooter", "description": "Never misses at range."},
    )
    assert got == {
        "name": "Varena",
        "species": "elf",
        "sex": "female",
        "apparentAge": "120",
        "description": "Tall and watchful.",
        "personality": "Wry.",
        "instinct": "Protect the weak.",
        "strengths": "Sharpshooter — Never misses at range.",
        "other": "Left-handed.",
    }
    # No leftover legacy keys.
    for dead in ("gender", "age", "heightCm", "weightKg", "likes", "dislikes", "drive"):
        assert dead not in got


def test_migrate_is_idempotent_on_new_shape():
    new = {
        "name": "Hero", "species": "human", "sex": "", "apparentAge": "",
        "description": "", "personality": "", "instinct": "",
        "strengths": "Brawler — hits hard.", "other": "",
    }
    assert migrate_basic_info(new) == new


def test_migrate_strengths_combine_variants():
    assert migrate_basic_info({}, {"name": "Scout", "description": ""})["strengths"] == "Scout"
    assert migrate_basic_info({}, {"name": "", "description": "Sneaky."})["strengths"] == "Sneaky."
    assert migrate_basic_info({}, {"name": "", "description": ""})["strengths"] == ""
    # An existing strengths string wins over a (stale) field_skill.
    assert migrate_basic_info({"strengths": "Keep this."}, {"name": "X", "description": "Y"})["strengths"] == "Keep this."


def test_migrate_empty_age_is_blank_not_zero():
    assert migrate_basic_info({"age": 0})["apparentAge"] == ""
    assert migrate_basic_info({"age": 30})["apparentAge"] == "30"


# ── Integration: character files read back in the new shape ─────────

def test_create_and_read_uses_new_schema():
    ch = char_files.create_character("character", {
        "name": "Test NPC", "sex": "nonbinary", "apparentAge": "ageless",
        "species": "spirit", "description": "A drifting light.",
        "personality": "Curious.", "instinct": "Wander toward warmth.",
        "strengths": "Phasewalk — slips through walls.", "other": "Hums.",
    })
    read = char_files.read_character(ch["id"])
    assert read["basicInfo"]["sex"] == "nonbinary"
    assert read["basicInfo"]["apparentAge"] == "ageless"
    assert read["basicInfo"]["strengths"] == "Phasewalk — slips through walls."
    assert "fieldSkill" not in read
    assert read["schemaVersion"] == 4
    char_files.delete_character(ch["id"])


def test_legacy_folder_is_migrated_to_single_png_on_read():
    """Pre-rebuild characters were a folder (character.json + full/crop files),
    not a single PNG — read_character() must convert one on first read."""
    import json
    import uuid

    cid = str(uuid.uuid4())
    old_dir = char_files.char_dir(cid)
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "character.json").write_text(json.dumps({
        "id": cid, "type": "character", "schemaVersion": 1,
        "basicInfo": {"name": "Legacy", "gender": "male", "age": 40, "drive": "Revenge."},
        "fieldSkill": {"name": "Duelist", "description": "Deadly with a blade."},
    }), encoding="utf-8")

    read = char_files.read_character(cid)
    assert read["name"] == "Legacy"
    assert read["basicInfo"]["sex"] == "male"
    assert read["basicInfo"]["apparentAge"] == "40"
    assert read["basicInfo"]["instinct"] == "Revenge."
    assert read["basicInfo"]["strengths"] == "Duelist — Deadly with a blade."
    assert char_files.exists(cid)          # the single PNG now exists...
    assert not old_dir.exists()            # ...and the old folder is gone.
    char_files.delete_character(cid)


def test_pre_lock_field_cards_get_locked_backfilled_on_read():
    """Characters written before SCHEMA_VERSION 4 (the `locked` field on
    mandatory blocks) — like the bundled Varena card, or any pre-existing
    install's characters — must pick up `locked` on their Open/Close Tag and
    Equipment blocks the first time they're read after upgrading, not just
    on freshly-created ones."""
    import uuid

    # Hand-build a pre-`locked`-field block list (blocks_from_legacy_basic_info
    # already always locks these now, so it can't simulate old data itself)
    # and write it directly with an old schemaVersion stamped, the way a real
    # pre-upgrade character file would look on disk.
    cid = str(uuid.uuid4())
    old_blocks = [
        {"id": "o", "type": "text", "name": "Open Tag", "enabled": True, "content": "<{{name}}>"},
        {"id": "d", "type": "text", "name": "Description", "enabled": True, "content": "An old card."},
        {"id": "e", "type": "equipment", "name": "Equipment", "enabled": True},
        {"id": "c", "type": "text", "name": "Close Tag", "enabled": True, "content": "</{{name}}>"},
    ]
    old_version = char_files.SCHEMA_VERSION
    try:
        char_files.SCHEMA_VERSION = 3  # simulate a pre-migration write
        char_files.write_character(cid, name="Old Card", char_type="character", blocks=old_blocks)
        pre = char_files.read_character(cid)
        assert pre["schemaVersion"] == 3
        assert not any(b.get("locked") for b in pre["blocks"])
    finally:
        char_files.SCHEMA_VERSION = old_version
    # The in-memory read cache would otherwise still hold the pre-upgrade
    # entry (same mtime) — in real life a version bump ships with a server
    # restart, which starts with an empty cache; simulate that here.
    char_files._read_cache.pop(cid, None)

    upgraded = char_files.read_character(cid)
    assert upgraded["schemaVersion"] == 4
    by_name = {b["name"]: b for b in upgraded["blocks"]}
    assert by_name["Open Tag"]["locked"] is True
    assert by_name["Close Tag"]["locked"] is True
    assert next(b for b in upgraded["blocks"] if b["type"] == "equipment")["locked"] is True

    # Idempotent — reading again doesn't re-trigger the migration or drift.
    again = char_files.read_character(cid)
    assert again["schemaVersion"] == 4
    char_files.delete_character(cid)
