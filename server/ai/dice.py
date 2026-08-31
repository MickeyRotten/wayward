"""Seeded skill-check dice.

A regenerate button over an unseeded roll is an open save-scum hole: the player
re-rolls until the answer is the one they wanted, and no failure ever has to be
lived with. ``random.randint`` was exactly that.

Every roll here is **pure in (turn, actor, skill, difficulty)**. A regenerate
re-sends the same turn, so it re-*tells* the same result; genuinely choosing
something else — a different action, a different skill — earns a new roll.

**Two seeding traps, both regression-tested in ``test_dice.py``.** They are the
reason this is thirty lines and not three:

1. FNV-1a's bit 0 is only the XOR of the input bytes' low bits, and ``h % n``
   shares its parity when ``n`` is even. Feeding a raw FNV hash to the modulo
   therefore makes a die's parity a predictable function of the seed's
   characters — on some seed families a d20 that can only roll odd.
2. Hashing ``seed|i`` for extra dice — seeds a suffix apart — leaks the same
   relationship *between* dice and locks them into fixed relative parities.
   Each die still looks uniform alone; only the joint distribution is wrong.

So: **one** hash, run through a murmur3 finalizer (``_avalanche``), with any
extra dice counting off that mixed base.
"""

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK64 = 0xFFFFFFFFFFFFFFFF
_GOLDEN = 0x9E3779B97F4A7C15  # 2^64 / φ — the step between derived dice

# Difficulty → DC on a d20. Kept small and legible; the narrator picks a band,
# never a number.
DIFFICULTY_DCS: dict[str, int] = {
    "easy": 8,
    "normal": 12,
    "hard": 16,
    "heroic": 19,
}
DEFAULT_DIFFICULTY = "normal"


def _fnv1a(text: str) -> int:
    h = _FNV_OFFSET
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & _MASK64
    return h


def _avalanche(x: int) -> int:
    """murmur3's 64-bit finalizer — the step that makes every output bit depend
    on every input bit, which is what the modulo below assumes."""
    x &= _MASK64
    x ^= x >> 33
    x = (x * 0xFF51AFD7ED558CCD) & _MASK64
    x ^= x >> 33
    x = (x * 0xC4CEB9FE1A85EC53) & _MASK64
    x ^= x >> 33
    return x


def seed_hash(*parts) -> int:
    """The mixed base for a roll. Exported so anything that needs to reproduce a
    turn's randomness (a future animation, a replay) uses the same seam."""
    return _avalanche(_fnv1a("|".join(str(p) for p in parts)))


def roll_dice(seed: int, count: int = 1, sides: int = 20) -> list[int]:
    """``count`` dice off one mixed base. Extra dice count off the base by the
    golden-ratio step and are re-avalanched — never re-hashed from a suffixed
    seed (trap 2 above)."""
    count = max(1, min(int(count), 10))
    sides = max(2, min(int(sides), 100))
    return [
        (_avalanche(seed + i * _GOLDEN) % sides) + 1
        for i in range(count)
    ]


def normalize_difficulty(raw) -> str:
    key = (str(raw or "")).strip().lower()
    return key if key in DIFFICULTY_DCS else DEFAULT_DIFFICULTY


def skill_check(
    turn: int,
    actor: str,
    skill: str,
    difficulty: str,
    variant: int = 0,
) -> dict:
    """Roll one d20 against the difficulty's DC.

    ``variant`` is the swipe index: a *deliberate* new take on the same turn
    (the player asked for a different telling) rolls fresh, while a plain
    regenerate of the same variant re-tells the same result."""
    diff = normalize_difficulty(difficulty)
    dc = DIFFICULTY_DCS[diff]
    seed = seed_hash(turn, variant, actor.strip().lower(), skill.strip().lower(), diff)
    roll = roll_dice(seed, 1, 20)[0]

    if roll == 20:
        outcome = "critical success"
    elif roll == 1:
        outcome = "critical failure"
    elif roll >= dc:
        outcome = "success"
    else:
        outcome = "failure"

    return {"roll": roll, "dc": dc, "difficulty": diff, "outcome": outcome}
