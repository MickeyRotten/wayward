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
