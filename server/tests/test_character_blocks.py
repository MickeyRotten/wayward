"""Pure-function tests for server/ai/character_blocks.py — the `locked`
mandatory-block convention and the markdown-header-depth composition added
for the Character Sheet UX pass (TODO.md)."""

from server.ai.character_blocks import (
    TAG_OPEN_NAME, TAG_CLOSE_NAME, default_blocks, compose_blocks,
)


def _by_name(blocks, name):
    return next(b for b in blocks if b["name"] == name)


def test_default_blocks_locks_only_the_mandatory_three():
    blocks = default_blocks("Tifa")
    assert _by_name(blocks, TAG_OPEN_NAME)["locked"] is True
    assert _by_name(blocks, TAG_CLOSE_NAME)["locked"] is True
    assert _by_name(blocks, "Equipment")["locked"] is True
    for name in ("Description", "Personality", "Instinct", "Strengths", "Other"):
        assert _by_name(blocks, name)["locked"] is False


def test_compose_blocks_root_text_gets_h2_heading():
    blocks = [
        {"id": "1", "type": "text", "name": "Personality", "content": "Wry", "enabled": True},
    ]
    out = compose_blocks(blocks, "Varena")
    assert out == "## Personality\nWry"


def test_compose_blocks_folder_child_gets_h3_heading():
    blocks = [
        {"id": "f", "type": "folder", "name": "Extras", "enabled": True, "children": [
            {"id": "2", "type": "text", "name": "Quirks", "content": "Hums when nervous.", "enabled": True},
        ]},
    ]
    out = compose_blocks(blocks, "Varena")
    assert out == "### Quirks\nHums when nervous."


def test_compose_blocks_description_and_tags_stay_bare_no_heading():
    blocks = [
        {"id": "o", "type": "text", "name": TAG_OPEN_NAME, "content": "<{{name}}>", "enabled": True},
        {"id": "d", "type": "text", "name": "Description", "content": "An elf.", "enabled": True},
        {"id": "c", "type": "text", "name": TAG_CLOSE_NAME, "content": "</{{name}}>", "enabled": True},
    ]
    out = compose_blocks(blocks, "Varena")
    assert out == "<Varena>\nAn elf.\n</Varena>"
    assert "##" not in out
