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
    assert read["schemaVersion"] == 2
    char_files.delete_character(ch["id"])


def test_legacy_file_is_migrated_on_read():
    import json
    ch = char_files.create_character("character", {"name": "Legacy"})
    # Hand-write a legacy-shaped file (old keys + top-level fieldSkill).
    char_files.write_character(ch["id"], {
        "id": ch["id"], "type": "character", "schemaVersion": 1,
        "basicInfo": {"name": "Legacy", "gender": "male", "age": 40, "drive": "Revenge."},
        "fieldSkill": {"name": "Duelist", "description": "Deadly with a blade."},
    })
    read = char_files.read_character(ch["id"])
    assert read["basicInfo"]["sex"] == "male"
    assert read["basicInfo"]["apparentAge"] == "40"
    assert read["basicInfo"]["instinct"] == "Revenge."
    assert read["basicInfo"]["strengths"] == "Duelist — Deadly with a blade."
    assert "fieldSkill" not in read
    assert "gender" not in read["basicInfo"]
    char_files.delete_character(ch["id"])
