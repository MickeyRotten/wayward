"""Species/Creature-template field composition — shared by the /lore API
routes (server/api/lore.py) and the Chronicler/Editor's create_lore/update_lore
tools (server/ai/worldbuilder.py, server/ai/planner.py). Single source of
truth for how the 8 structured Species fields fold into the underlying
LorebookEntry.content, so the existing prompt-injection pipeline
(lore_injector.py, prompt_builder.py) keeps reading an ordinary freeform
content string with zero changes. Mirrors server/ai/scenario.py's pattern —
one Species entry covers both sapient peoples and monsters/creatures; the
old 'monsters' lorebook category is retired (see migrate_legacy_species_fields
and server/db/database.py's migrate_species_lore).
"""

# (field key, display label) pairs, in display/compose order.
SPECIES_FIELDS: list[tuple[str, str]] = [
    ("overview", "Overview"),
    ("physicalAppearance", "Physical Appearance"),
    ("biologyReproduction", "Biology & Reproduction"),
    ("cultureBehavior", "Culture & Behavior"),
    ("dangerCombat", "Danger & Combat Notes"),
    ("typicalGear", "Typical Gear"),
    ("archetypesVariants", "Archetypes & Variants"),
    ("nameExamples", "Name Examples"),
]


def compose_species_content(fields: dict) -> str:
    """Compose the 8 structured Species fields into LorebookEntry.content.

    Empty/whitespace-only fields are skipped entirely (no dangling "Label: "
    line). Non-empty sections are joined as "Label: value" blocks separated by
    a blank line.
    """
    parts = []
    for key, label in SPECIES_FIELDS:
        value = (fields.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n\n".join(parts)


def merge_species_fields(existing: dict | None, partial: dict | None) -> dict:
    """Partial per-field merge: only keys present in `partial` overwrite
    `existing`; every other existing field is left untouched. Unknown keys
    are dropped, matching how the Editor's set_scenario tool does partial
    per-field updates."""
    merged = dict(existing or {})
    for key, _label in SPECIES_FIELDS:
        if partial and key in partial:
            merged[key] = partial[key] or ""
    return merged


def migrate_legacy_species_fields(species_fields: dict | None, content: str) -> dict:
    """One-time, non-destructive legacy migration: if `species_fields` is
    empty/missing (all falsy) but `content` is non-empty (a monsters-category
    entry recategorized from before this feature existed), seed the
    `overview` field from the old freeform content as a starting point.
    Otherwise return species_fields unchanged (normalized to a dict).

    Pure function — callers persist the result themselves if it changed.
    """
    fields = dict(species_fields or {})
    if not any(fields.values()) and (content or "").strip():
        fields["overview"] = content.strip()
    return fields
