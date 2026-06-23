import re
from dataclasses import dataclass

from server.db.models import PartyMember

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
    party_members: list[PartyMember],
    current_turn: int,
) -> list[SpotlightSignal]:
    msg_lower = player_message.lower()
    context_lower = (player_message + " " + recent_context).lower()
    group_addressed = bool(GROUP_ADDRESS_RE.search(msg_lower))

    signals = []
    for pm in party_members:
        name = pm.basic_info.get("name", "")
        name_lower = name.lower()

        # Direct address: name in message OR group address
        directly_addressed = (
            group_addressed or (bool(name_lower) and name_lower in msg_lower)
        )

        # Field skill relevance: keyword overlap
        skill_desc = pm.field_skill.get("description", "")
        skill_keywords = _extract_keywords(skill_desc)
        field_skill_relevant = any(kw in context_lower for kw in skill_keywords)

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
    party_members: list[PartyMember],
) -> list[str]:
    text_lower = response_text.lower()
    speaker_ids = []
    for pm in party_members:
        name = pm.basic_info.get("name", "")
        if name and name.lower() in text_lower:
            speaker_ids.append(pm.id)
    return speaker_ids
