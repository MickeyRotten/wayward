"""The in-game clock — client-owned, never narrator-written.

The narrator used to write ``day`` as an integer straight into ``set_scene``,
which meant a value nothing validated: it could freeze, jump forward, or run
backwards, and a single confused beat desynced the calendar permanently.

Here the narrator emits a **duration label** off a fixed ladder and the server
owns every number. Three properties fall out of that:

* An unrecognised label falls to the smallest step, so a garbage value is
  *unrepresentable* rather than clamped into something plausible.
* A turn with **no** duration still advances time by the smallest step, so an
  unparseable beat can never freeze the world.
* Time reaches the player and the model as a **phase word** only
  (``phase_of``) — never a clock face — so nothing can narrate "half past two"
  and then contradict it two beats later.

``night`` is the one label that *anchors* rather than adds: it runs to the next
``WAKE_MINUTE`` (07:00) so sleeping always lands on a morning, and it sets
``rested``. A nap taken at eight in the morning would reach nearly a full day
forward, so an anchor further out than ``MAX_ANCHOR_REACH`` degrades to a
half-day step instead.
"""

MINUTES_PER_DAY = 1440
WAKE_MINUTE = 7 * 60          # 07:00 — where an anchored night lands
MAX_ANCHOR_REACH = 16 * 60    # beyond this, "night" is a nap, not a night

# The ladder. Order matters only for documentation; lookup is by key.
DURATION_STEPS: dict[str, int] = {
    "moment": 2,
    "brief": 10,
    "scene": 30,
    "hour": 60,
    "hours": 180,
    "halfday": 360,
    "day": MINUTES_PER_DAY,
}
# The smallest step — the fallback for a missing or unrecognised label, and the
# reason an unparseable turn still ages the world.
DEFAULT_DURATION = "moment"
ANCHOR_DURATION = "night"

DURATION_LABELS = (*DURATION_STEPS.keys(), ANCHOR_DURATION)

# Eight bands, ordered by their start minute. The label is all the model and the
# player ever see.
_PHASES: tuple[tuple[int, str], ...] = (
    (0, "late night"),
    (5 * 60, "dawn"),
    (7 * 60, "morning"),
    (11 * 60, "midday"),
    (13 * 60, "afternoon"),
    (17 * 60, "evening"),
    (19 * 60, "dusk"),
    (21 * 60, "night"),
)


def normalize_duration(raw) -> str:
    """Coerce whatever the narrator emitted onto the ladder.

    Anything unrecognised — a number, a phrase, ``None`` — becomes
    ``DEFAULT_DURATION``. That is deliberate: a bad label should cost the world
    two minutes, not a guess."""
    if not isinstance(raw, str):
        return DEFAULT_DURATION
    key = raw.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    if key in DURATION_STEPS or key == ANCHOR_DURATION:
        return key
    # A few spellings models reach for that map cleanly onto a rung.
    aliases = {
        "instant": "moment", "moments": "moment", "seconds": "moment",
        "minutes": "brief", "afew minutes": "brief", "short": "brief",
        "awhile": "scene", "while": "scene", "halfhour": "scene",
        "anhour": "hour", "onehour": "hour",
        "severalhours": "hours", "afewhours": "hours",
        "halfaday": "halfday", "halfday": "halfday", "afternoon": "halfday",
        "fullday": "day", "aday": "day", "allday": "day",
        "overnight": "night", "sleep": "night", "rest": "night",
    }
    return aliases.get(key, DEFAULT_DURATION)


def phase_of(minutes: int) -> str:
    """The phase word for a minute-of-day. This is the only form time takes
    outside this module."""
    m = int(minutes) % MINUTES_PER_DAY
    label = _PHASES[0][1]
    for start, name in _PHASES:
        if m >= start:
            label = name
        else:
            break
    return label


def advance_clock(day: int, minutes: int, duration: str | None) -> tuple[int, int, bool]:
    """Advance the clock by one turn.

    Returns ``(day, minutes, rested)``. ``rested`` is True only when an anchored
    night actually landed — the signal a caller can hang "you wake up" on."""
    day = max(1, int(day or 1))
    minutes = int(minutes or 0) % MINUTES_PER_DAY
    label = normalize_duration(duration)

    if label == ANCHOR_DURATION:
        reach = (WAKE_MINUTE - minutes) % MINUTES_PER_DAY
        if reach == 0:
            reach = MINUTES_PER_DAY
        if reach <= MAX_ANCHOR_REACH:
            total = minutes + reach
            return day + total // MINUTES_PER_DAY, total % MINUTES_PER_DAY, True
        label = "halfday"  # a nap, not a night

    total = minutes + DURATION_STEPS[label]
    return day + total // MINUTES_PER_DAY, total % MINUTES_PER_DAY, False


def describe_ladder() -> str:
    """The ladder as the output protocol states it to the narrator."""
    return (
        "moment (a beat) · brief (a few minutes) · scene (about half an hour) · "
        "hour · hours (a few) · halfday · day · night (sleep through to morning)"
    )
