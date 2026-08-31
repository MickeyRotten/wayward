"""The trailing ``<<<TURN>>>`` block — one machine-read line carrying the
turn's scene state and the player's next choices.

**Why this exists.** Scene state used to cost a whole model round-trip: the
narrator called ``set_scene`` with four strings, the loop executed it, appended
a tool result and called the model again to write the prose. A round-trip is the
most expensive thing a turn can spend, and it was buying four strings that the
model could equally well append to the beat it had just written. Action options
had the same shape and were already solved this way (the old
``<<<OPTIONS>>>`` block); this generalises that trick and folds both into one
marker, so there is one thing to teach, one thing to parse, and one thing to
strip.

**Emit canonical, read lenient.** The guidance documents exactly one shape and
ships a worked example, because an example is a stronger instruction than a
schema. The reader, by contrast, accepts:

* marker variants — ``<<TURN>>``, ``[TURN]``, odd spacing, any case — but only
  when a JSON object actually follows, so the word "turn" in prose can never
  truncate a beat;
* the legacy ``<<<OPTIONS>>>`` marker followed by a bare array, so histories
  written before this block still parse;
* no marker at all: the last brace-balanced object whose keys intersect the
  contract. Without this a dropped marker leaves raw JSON rendered into the
  reading pane as narration;
* options as an array, a newline-joined string, a numbered map, or rows of
  ``{action: …}`` — the four shapes models actually reach for.

The block is **always** stripped from the prose, even when its JSON is
malformed, so a bad emit costs the turn its state and never leaks braces to the
player.
"""

import json
import re

TURN_MARKER = "<<<TURN>>>"
_LEGACY_OPTIONS_MARKER = "<<<OPTIONS>>>"

# Marker variants: any bracket run, optional spacing, TURN or OPTIONS, any case.
# Anchored to a line start (or the very start of the text) so the word cannot
# appear mid-sentence and cut a beat in half.
_MARKER_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:<{1,3}|\[|\{{2})[ \t]*(TURN|OPTIONS)[ \t]*(?:>{1,3}|\]|\}{2})[ \t]*",
    re.IGNORECASE,
)

# Keys the block may carry. A bare trailing object is only accepted as a block
# when it intersects this set — otherwise it is prose that happens to be JSON.
BLOCK_KEYS = frozenset({"location", "timeofday", "weather", "duration", "options"})

_OPTION_ALIASES = ("options", "actions", "choices", "suggestions", "nextactions", "moves")

MAX_OPTIONS = 6


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z]", "", str(k).lower())


def _loads_tolerant(raw: str):
    """``json.loads`` with one repair pass.

    Models routinely emit a raw newline or tab *inside* a string literal, which
    is invalid JSON and would otherwise cost the turn its whole block. Escape
    control characters that sit inside strings and try once more."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    out: list[str] = []
    in_str = False
    esc = False
    for c in raw:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            elif c == "\n":
                out.append("\\n")
                continue
            elif c == "\r":
                out.append("\\r")
                continue
            elif c == "\t":
                out.append("\\t")
                continue
        elif c == '"':
            in_str = True
        out.append(c)
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError:
        return None


def _balanced_object(text: str, start: int) -> tuple[dict | None, int]:
    """Parse a brace-balanced JSON object beginning at or after ``start``.

    Returns ``(obj, end_index)``; ``(None, -1)`` when nothing parses. Quote- and
    escape-aware, so a brace inside a description cannot end the object early."""
    i = text.find("{", start)
    if i < 0:
        return None, -1
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                obj = _loads_tolerant(text[i:j + 1])
                return (obj if isinstance(obj, dict) else None), j + 1
    return None, -1


def _balanced_array(text: str, start: int) -> tuple[list | None, int]:
    i = text.find("[", start)
    if i < 0:
        return None, -1
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                arr = _loads_tolerant(text[i:j + 1])
                if isinstance(arr, list):
                    return arr, j + 1
                # Salvage the complete quoted strings — a truncated array still
                # usually carries most of its options intact.
                return [
                    s.replace('\\"', '"').replace("\\\\", "\\")
                    for s in re.findall(r'"((?:[^"\\]|\\.)*)"', text[i:j + 1])
                ], j + 1
    return None, -1


def normalize_options(raw) -> list[str]:
    """Coerce the four shapes models reach for into a clean ``list[str]``.

    An array of objects used to reach the option button as a React child and
    throw, and a single newline-joined string rendered as one giant option — so
    this is not defensive tidying, it is the difference between buttons and no
    buttons."""
    items: list = []
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [ln for ln in raw.splitlines()]
    elif isinstance(raw, list):
        items = list(raw)
    elif isinstance(raw, dict):
        # {"1": "...", "2": "..."} — a map models produce when asked to number.
        items = [raw[k] for k in sorted(raw.keys(), key=lambda x: str(x))]
    else:
        return []

    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            # {action: "..."} / {text: "..."} / {label: "..."}
            val = next(
                (it[k] for k in it if _norm_key(k) in ("action", "text", "label", "option", "choice")),
                None,
            )
            it = val
        if it is None:
            continue
        s = str(it).strip()
        # Strip self-numbering ("1. ", "2) ") and wrapping emphasis.
        s = re.sub(r"^\s*[-*•]?\s*\d+[.)\]]\s*", "", s)
        s = re.sub(r"^\s*[-*•]\s*", "", s)
        s = s.strip().strip("*_` ").strip()
        if s:
            out.append(s)
    # The first-person backstop lives with the suggester (it is about how an
    # option READS, not what shape it arrived in) and is applied here so both
    # generation modes normalise identically.
    from server.ai.action_suggester import _to_first_person

    return [_to_first_person(o) for o in out[:MAX_OPTIONS]]


def _clean_block(obj: dict) -> dict:
    """Keep only contract keys, normalised, non-blank."""
    by_norm = {_norm_key(k): v for k, v in obj.items()}
    out: dict = {}
    for key, norm in (("location", "location"), ("timeOfDay", "timeofday"), ("weather", "weather")):
        v = by_norm.get(norm)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    dur = by_norm.get("duration")
    if isinstance(dur, str) and dur.strip():
        out["duration"] = dur.strip()
    for alias in _OPTION_ALIASES:
        if alias in by_norm:
            opts = normalize_options(by_norm[alias])
            if opts:
                out["options"] = opts
            break
    return out


def parse_turn_block(text: str) -> tuple[str, dict]:
    """Split narration prose from its trailing turn block.

    Returns ``(clean_prose, block)``. ``block`` is ``{}`` when nothing parsed —
    and the prose is still returned with any block-shaped tail removed, so a
    malformed emit degrades to "no state this turn" rather than leaking JSON."""
    if not text:
        return text, {}

    # 1. A recognised marker anywhere in the tail.
    last = None
    for m in _MARKER_RE.finditer(text):
        last = m
    if last is not None:
        head = text[: last.start()].rstrip()
        tail = text[last.end():]
        kind = last.group(1).upper()
        obj, _ = _balanced_object(tail, 0)
        if isinstance(obj, dict):
            block = _clean_block(obj)
            if block:
                return head, block
        arr, _ = _balanced_array(tail, 0)
        if isinstance(arr, list):
            opts = normalize_options(arr)
            if opts:
                return head, {"options": opts}
        # A block clipped by the response-token cap never closes its bracket, so
        # nothing above balances. Salvage the complete quoted strings — most of
        # the options are usually intact, and buttons beat no buttons.
        salvaged = normalize_options([
            m.replace('\\"', '"').replace("\\\\", "\\")
            for m in re.findall(r'"((?:[^"\\]|\\.)*)"', tail)
        ])
        if salvaged:
            return head, {"options": salvaged}
        # Marker present but nothing usable followed: still strip it. A visible
        # "<<<TURN>>>" in the reading pane is worse than a lost state write.
        # (`kind` is kept for the log line callers write.)
        _ = kind
        return head, {}

    # 2. No marker: the last brace-balanced object whose keys intersect the
    #    contract. This is the case that used to render raw JSON as narration.
    pos, found = 0, None
    while True:
        obj, end = _balanced_object(text, pos)
        if end < 0:
            break
        if isinstance(obj, dict) and {_norm_key(k) for k in obj} & BLOCK_KEYS:
            start = text.find("{", pos)
            found = (start, end, obj)
        pos = end
    if found:
        start, end, obj = found
        block = _clean_block(obj)
        if block and not text[end:].strip():
            return text[:start].rstrip(), block

    return text, {}


def build_turn_block_guidance(
    option_count: int | None,
    include_scene: bool = True,
    include_clock: bool = True,
) -> str:
    """The output protocol for the trailing block.

    Fields are documented only when they are switched on, because **a named
    field is an invitation** — a model shown ``"options"`` will produce options
    whether or not anything reads them. The worked example is BUILT from the
    same flags for the same reason: an example is the strongest instruction in
    the protocol, and one showing a field teaches it back after every rule above
    has dropped it."""
    from server.ai.clock import describe_ladder

    fields: list[str] = []
    example: dict = {}

    if option_count:
        fields.append(
            f'- "options" (REQUIRED): exactly {option_count} short choice phrases for the player. '
            'Each is FIRST PERSON starting with "I", 10 words or fewer, grounded in what you just '
            "narrated, never attacking or fighting, and never a reworded copy of another. Spread the "
            "set across different intents — cautious vs. bold, kind vs. ruthless, practical vs. "
            "curious — so each is a genuinely different decision. They are the PLAYER CHARACTER's "
            "impulses: phrase them in that character's voice, shaped by their Personality and Drive."
        )
        example["options"] = [
            "I follow the smoky trail.",
            "I wait for nightfall.",
            "I pocket the coin purse.",
            "I climb the watchtower.",
        ][:option_count] or ["I press on."]

    if include_scene:
        fields.append(
            '- "location": ONE place name — the most specific one, and nothing else. '
            '"Damp Cellar", never "Boars Head Tavern - Damp Cellar". Include it only when the scene '
            "has actually moved."
        )
        fields.append(
            '- "weather": a few words, only when it changed or was just established.'
        )
        example["location"] = "Damp Cellar"
        example["weather"] = "cold and still"

    if include_clock:
        fields.append(
            f'- "duration": how much time this beat took, as ONE of: {describe_ladder()}. '
            "Always include it. Never write a day number, a date, or a clock time — the game keeps "
            "the calendar and will tell you the time of day."
        )
        example["duration"] = "scene"

    if not fields:
        return ""

    return (
        "OUTPUT PROTOCOL — end every reply with the turn block.\n\n"
        "Write your narration first. Then, as the very last line, write exactly "
        f"{TURN_MARKER} immediately followed by one JSON object. After it, write nothing.\n\n"
        "Fields:\n" + "\n".join(fields) + "\n\n"
        "Worked example — the whole final line, exactly this shape:\n"
        f"{TURN_MARKER}{json.dumps(example, ensure_ascii=False)}\n\n"
        f"The {TURN_MARKER} line is machine-read and never shown to the player. "
        "Omit a field rather than guessing at it; omit the object's braces for nothing."
    )
