from types import SimpleNamespace as NS

from server.ai.lore_injector import format_lore_block, group_by_position, match_entries


def _entry(**kw):
    base = dict(enabled=True, permanent=False, title="", keywords=[], cat="world", content="")
    base.update(kw)
    return NS(**base)


def test_keyword_match_is_case_insensitive():
    e = _entry(title="Ancient Ruin", keywords=["kal-toth"])
    assert match_entries("you glimpse KAL-TOTH beyond the trees", [e]) == [e]


def test_title_is_implicit_keyword():
    e = _entry(title="Murkwood")
    assert match_entries("we walk into murkwood at dusk", [e]) == [e]


def test_disabled_entries_never_match():
    e = _entry(title="Murkwood", enabled=False, permanent=True)
    assert match_entries("we walk into murkwood", [e]) == []


def test_permanent_entries_always_match():
    e = _entry(title="Scenario", permanent=True)
    assert match_entries("totally unrelated", [e]) == [e]


def test_no_match_returns_empty():
    entries = [_entry(title="Murkwood"), _entry(title="Goblin", keywords=["goblin"])]
    assert match_entries("nothing relevant here", entries) == []


def test_group_by_position_sorts_by_order():
    cfg = NS(
        injection_order={"world": 10, "items": 0},
        injection_position={"world": "top", "items": "top", "spells": "bogus"},
    )
    world, item, spell = _entry(cat="world"), _entry(cat="items"), _entry(cat="spells")
    groups = group_by_position([world, item, spell], cfg)
    assert groups["top"] == [item, world, spell]  # items order 0 < world 10 < spells default 50...

    # unknown position falls back to top
    assert spell in groups["top"]


def test_format_lore_block():
    e = _entry(title="Murkwood", cat="world", content="A dark forest.")
    block = format_lore_block([e])
    assert "LOREBOOK ENTRIES:" in block and "[WORLD] Murkwood: A dark forest." in block
    assert format_lore_block([]) == ""
