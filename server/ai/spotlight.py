import re
from dataclasses import dataclass

from server.db.party import RuntimeCharacter

STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
    "either", "neither", "each", "every", "all", "any", "few", "more",
    "most", "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "while", "where",
    "how", "what", "which", "who", "whom", "this", "that", "these",
    "those", "it", "its", "he", "she", "his", "her", "they", "them",
    "their", "we", "our", "you", "your", "my", "me", "i", "able",
    "also", "still", "even", "much", "like", "well", "back", "make",
    "take", "get", "got", "put", "say", "said", "know", "come", "go",
    "see", "look", "think", "give", "use", "find", "tell", "ask",
    "work", "seem", "feel", "try", "leave", "call", "keep", "let",
    "begin", "show", "hear", "play", "run", "move", "live", "way",
    "thing", "man", "woman", "child", "world", "life", "hand", "part",
    "place", "case", "week", "company", "system", "program", "question",
    "during", "something", "nothing", "anything", "everything", "someone",
    "anyone", "everyone", "about", "around", "things", "really",
})

GROUP_ADDRESS_RE = re.compile(
    r"\b(we|everyone|you\s+all|you\s+guys|party|team|group|all\s+of\s+you|everybody)\b",
    re.IGNORECASE,
)

# Verbs that signal a line of dialogue is being attributed to a speaker.
_SAID_VERBS = (
    r"(?:say|says|said|ask|asks|asked|repl(?:y|ies|ied)|whispers?|whispered|"
    r"mutters?|muttered|shouts?|shouted|adds?|added|calls?|called|answers?|"
    r"answered|murmurs?|murmured|growls?|growled|grins?|grinned|laughs?|laughed|"
    r"offers?|offered|warns?|warned|notes?|noted|continues?|continued|hisses?|"
    r"hissed|breathes?|breathed|chuckles?|chuckled|sighs?|sighed|snaps?|snapped|"
    r"declares?|declared|remarks?|remarked|interjects?|interjected|nods?|nodded)"
)


def _name_pattern(name: str) -> str:
    """A word-boundary regex for a character's name OR its first token."""
    first = name.split()[0] if name.split() else name
    if first.lower() != name.lower():
        return rf"\b(?:{re.escape(name)}|{re.escape(first)})\b"
    return rf"\b{re.escape(name)}\b"


def _name_mentioned(name: str, text: str) -> bool:
    return bool(name) and re.search(_name_pattern(name), text, re.IGNORECASE) is not None


def _member_spoke(name: str, text: str) -> bool:
    """True only when ``name`` is attributed a line of dialogue — a name MENTION
    alone ('Tifa was asleep') does not count. Looks for the name adjacent to a
    quote or a said-verb, in either order."""
    if not _name_mentioned(name, text):
        return False
    n = _name_pattern(name)
    patterns = [
        rf'{n}\s*[:,]?\s*["“]',                  # Name: "…   /   Name, "…
        rf'{n}[^.!?\n"]{{0,40}}{_SAID_VERBS}\b',  # Name … said
        rf'{_SAID_VERBS}\b[^.!?\n"]{{0,25}}{n}',  # said … Name
        rf'["”][^"”\n]{{0,30}}{n}',               # …" Name   (trailing attribution)
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


@dataclass
class SpotlightSignal:
    member_id: str
    member_name: str
    directly_addressed: bool
    field_skill_relevant: bool
    turns_since_last_spoke: int


def compute_spotlight_signals(
    player_message: str,
    recent_context: str,
    party_members: list[RuntimeCharacter],
    current_turn: int,
) -> list[SpotlightSignal]:
    msg_lower = player_message.lower()
    context_lower = (player_message + " " + recent_context).lower()
    group_addressed = bool(GROUP_ADDRESS_RE.search(msg_lower))

    signals = []
    for pm in party_members:
        name = pm.basic_info.get("name", "")

        # Direct address: name (or first name) as a WORD in the message, or a
        # group address. Word-boundary avoids 'Al' matching 'also'.
        directly_addressed = group_addressed or _name_mentioned(name, msg_lower)

        # Field skill relevance: keyword overlap. Include the skill NAME's
        # distinctive tokens (e.g. 'Luma', 'Wrecking') — they recur in scenes
        # far more than the prose of the description.
        skill_name = pm.field_skill.get("name", "")
        skill_desc = pm.field_skill.get("description", "")
        skill_keywords = _extract_keywords(f"{skill_name} {skill_desc}")
        field_skill_relevant = any(
            re.search(rf"\b{re.escape(kw)}\b", context_lower) for kw in skill_keywords
        )

        # Turns since last spoke
        last_spoke = pm.last_spoke_turn or 0
        turns_since = current_turn - last_spoke

        signals.append(SpotlightSignal(
            member_id=pm.id,
            member_name=name,
            directly_addressed=directly_addressed,
            field_skill_relevant=field_skill_relevant,
            turns_since_last_spoke=turns_since,
        ))

    return signals


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if len(w) >= 4 and w not in STOPWORDS}


DEFAULT_SPOTLIGHT_RULE = (
    "RULE: Voice a party member only when directly addressed, clearly "
    "relevant to what's happening, or significantly overdue for a beat. "
    "Default to silence — most turns, no party member needs to speak. "
    "If a party member IS directly addressed, you MUST have them respond. "
    "Never have more than one react to the same beat unless the player "
    "addressed the whole group. When voiced, keep it to one or two "
    "sentences, true to their established character and Field Skill."
)


def format_spotlight_block(signals: list[SpotlightSignal], rule: str | None = None) -> str:
    lines = ["PARTY SPOTLIGHT — THIS TURN"]

    for s in signals:
        parts = []

        if s.directly_addressed:
            parts.append("DIRECTLY ADDRESSED")
        else:
            parts.append("not addressed")

        if s.field_skill_relevant:
            parts.append("scene may intersect their Field Skill")
        else:
            parts.append("no clear relevance to this beat")

        parts.append(f"last spoke {s.turns_since_last_spoke} turns ago")

        lines.append(f"  {s.member_name:12s} — {' · '.join(parts)}")

    lines.append("")
    lines.append(rule or DEFAULT_SPOTLIGHT_RULE)

    return "\n".join(lines)


def detect_speakers(
    response_text: str,
    party_members: list[RuntimeCharacter],
) -> list[str]:
    """Which party members actually SPOKE in this narration (were attributed a
    line of dialogue) — used to update last_spoke_turn. A bare mention of the
    name no longer counts (that previously corrupted the spotlight signal)."""
    speaker_ids = []
    for pm in party_members:
        name = pm.basic_info.get("name", "")
        if name and _member_spoke(name, response_text):
            speaker_ids.append(pm.id)
    return speaker_ids
