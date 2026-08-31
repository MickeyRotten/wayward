"""The active-party roll call — the one block that corrects the history.

The party roster used to be stated once, near the top of the prompt, a whole
history window before the beats that contradict it. A companion who left is
named in that block and then written out of the story twenty beats later, and
the *later* text is the one the model believes — which is why narrators keep
voicing people who are gone.

So composition is re-read from the bindings **every turn** and stated **after**
the history, under the state tier's authority line. It names who is here, who is
on the bench and explicitly not in the scene, and — the case that matters most —
it is emitted even when the party is empty. An empty party is exactly where the
history drifts, because there is nothing in the prompt to contradict a
transcript full of companions.
"""

from server.db.party import RuntimeCharacter


def _name(c: RuntimeCharacter) -> str:
    return (c.basic_info.get("name") or "").strip() or "Unnamed"


def compose_roll_call(
    pc: RuntimeCharacter,
    active: list[RuntimeCharacter],
    benched: list[RuntimeCharacter] | None = None,
    party_cap: int | None = None,
) -> str:
    """The PARTY block for the state tier. Always returns a non-empty string."""
    benched = benched or []
    pc_name = _name(pc)
    cap = f"/{party_cap}" if party_cap else ""

    lines = [f"PARTY — who is with {pc_name} right now ({len(active)}{cap}):"]
    if active:
        for m in active:
            lines.append(f"  · {_name(m)}")
    else:
        lines.append(
            f"  (nobody — {pc_name} is ALONE. Do not voice, reference, or bring along "
            "any companion, whatever earlier beats say.)"
        )

    if benched:
        names = ", ".join(_name(m) for m in benched)
        lines.append(
            f"  NOT in this scene: {names}. They exist in the world but are not "
            "travelling with the player — do not voice them."
        )

    return "\n".join(lines)
