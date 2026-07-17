"""Campaign "World Rules" (R21) — pure helpers shared by the REST routes, the
Editor's world-rules tools, and the narrator prompt builder. No DB access here.
"""

from __future__ import annotations


def normalize_attributes(raw) -> list[dict]:
    """Normalize the declared attribute/stat list into ``[{name, description}]``.
    Accepts dicts (current) or bare strings (a name only); drops nameless items."""
    out: list[dict] = []
    for item in (raw or []):
        if isinstance(item, str):
            name, desc = item.strip(), ""
        elif isinstance(item, dict):
            name = str(item.get("name", "") or "").strip()
            desc = str(item.get("description", "") or "").strip()
        else:
            continue
        if name:
            out.append({"name": name, "description": desc})
    return out


def compose_rules_block(rules: dict) -> str:
    """Render a compact WORLD RULES block for the narrator prompt. Only non-empty
    facts are included; returns '' when there is nothing worth injecting."""
    lines: list[str] = []
    party = rules.get("party_size")
    if party:
        lines.append(f"Party: up to {party} companion(s) travel with the player.")
    name = (rules.get("currency_name") or "").strip()
    if name:
        abbrev = (rules.get("currency_abbrev") or "").strip()
        symbol = (rules.get("currency_symbol") or "").strip()
        tag = " / ".join(t for t in (abbrev, symbol) if t)
        lines.append(f"Currency: {name}" + (f" ({tag})" if tag else "") + ".")
    attrs = normalize_attributes(rules.get("attributes"))
    if attrs:
        rendered = "; ".join(a["name"] + (f" — {a['description']}" if a["description"] else "") for a in attrs)
        lines.append(f"Attributes: {rendered}.")
    tone = (rules.get("tone") or "").strip()
    if tone:
        lines.append(f"Tone: {tone}")
    if not lines:
        return ""
    return "WORLD RULES\n" + "\n".join(lines)
