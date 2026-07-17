"""Lorebook keyword-matching and prompt-injection logic.

Deterministic, pre-LLM-call logic. Independently testable.
"""

from __future__ import annotations

from server.db.models import LorebookConfig, LorebookEntry


def match_entries(
    scan_text: str,
    entries: list[LorebookEntry],
) -> list[LorebookEntry]:
    """Return all entries that match: permanent=True, cat='pillars' (world
    rules — always injected for their high impact), OR any keyword — or the
    entry's own title, an implicit keyword — appears in ``scan_text``
    (case-insensitive). Disabled entries are skipped.

    ``scan_text`` is the text window being scanned: the new player message plus
    the last few turns of history (see build_prompt / LorebookConfig.scan_depth),
    so lore the narrator introduced still injects when the player replies with
    "tell me more about it"."""
    matched: list[LorebookEntry] = []
    msg_lower = scan_text.lower()
    for entry in entries:
        if not entry.enabled:
            continue
        # Pillars are the world's foundational rules — always in context.
        if entry.permanent or entry.cat == "pillars":
            matched.append(entry)
            continue
        title = (entry.title or "").strip().lower()
        candidates = [*(entry.keywords or []), *( [title] if title else [] )]
        for kw in candidates:
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
