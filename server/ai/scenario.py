"""Scenario field composition — shared by the /scenario API routes
(server/api/routes.py) and the Editor's set_scenario/get_scenario chat tools
(server/ai/planner.py). Single source of truth for how the 6 structured
Scenario fields fold into the underlying LorebookEntry.content, so the existing
prompt-injection pipeline (lore_injector.py, prompt_builder.py) keeps reading
an ordinary freeform content string with zero changes.
"""

# (field key, display label) pairs, in display/compose order.
SCENARIO_FIELDS: list[tuple[str, str]] = [
    ("setting", "Setting"),
    ("historyBrief", "History (Brief)"),
    ("species", "Species"),
    ("geography", "Geography"),
    ("techAndMagic", "Technology & Magic"),
    ("other", "Other"),
]


def compose_scenario_content(fields: dict) -> str:
    """Compose the 6 structured Scenario fields into LorebookEntry.content.

    Empty/whitespace-only fields are skipped entirely (no dangling "Label: "
    line). Non-empty sections are joined as "Label: value" blocks separated by
    a blank line.
    """
    parts = []
    for key, label in SCENARIO_FIELDS:
        value = (fields.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n\n".join(parts)


def migrate_legacy_fields(scenario_fields: dict | None, content: str) -> dict:
    """One-time, non-destructive legacy migration: if `scenario_fields` is
    empty/missing (all falsy) but `content` is non-empty (a campaign created
    before this feature existed), seed the `setting` field from the old
    freeform content as a starting point. Otherwise return scenario_fields
    unchanged (normalized to a dict).

    Pure function — callers persist the result themselves if it changed.
    """
    fields = dict(scenario_fields or {})
    if not any(fields.values()) and (content or "").strip():
        fields["setting"] = content.strip()
    return fields
