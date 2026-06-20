"""Lorebook keyword-matching and prompt-injection logic.

Deterministic, pre-LLM-call logic. Independently testable.
"""

from __future__ import annotations

from server.db.models import LorebookConfig, LorebookEntry


def match_entries(
    player_message: str,
    entries: list[LorebookEntry],
) -> list[LorebookEntry]:
    """Return all entries that match: permanent=True OR any keyword appears
    in the player message (case-insensitive). Disabled entries are skipped."""
    matched: list[LorebookEntry] = []
    msg_lower = player_message.lower()
    for entry in entries:
        if not entry.enabled:
            continue
        if entry.permanent:
            matched.append(entry)
            continue
        for kw in (entry.keywords or []):
            if kw.lower() in msg_lower:
                matched.append(entry)
                break
    return matched


def group_by_position(
    matched: list[LorebookEntry],
    config: LorebookConfig,
) -> dict[str, list[LorebookEntry]]:
    """Group matched entries by their category's configured injection position,
    sorted within each group by injection order (ascending)."""
    groups: dict[str, list[LorebookEntry]] = {
        "top": [],
        "before_input": [],
        "bottom": [],
    }
    order = config.injection_order or {}
    position = config.injection_position or {}
    for entry in matched:
        pos = position.get(entry.cat, "top")
        if pos not in groups:
            pos = "top"
        groups[pos].append(entry)
    for pos in groups:
        groups[pos].sort(key=lambda e: order.get(e.cat, 50))
    return groups


def format_lore_block(entries: list[LorebookEntry]) -> str:
    """Format a list of matched lorebook entries into a single text block
    for prompt injection."""
    if not entries:
        return ""
    lines = ["LOREBOOK ENTRIES:"]
    for e in entries:
        lines.append(f"[{e.cat.upper()}] {e.title}: {e.content}")
    return "\n".join(lines)
