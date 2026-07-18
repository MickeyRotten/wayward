"""Campaign Builder "Story Style" — the catalog composer + the /campaign-style
routes. Pure-function coverage for the seam plus TestClient round-trips."""

import json

from server.ai import style


# ── Pure: composer / normalize / wire mapping / migration ─────────

def test_compose_empty_is_blank():
    assert style.compose_style_block({}) == ""
    assert style.compose_style_block({"genre": "", "tone": "   "}) == ""


def test_compose_uses_option_snippet_for_known_ids():
    block = style.compose_style_block({"genre": "high_fantasy", "tone": "epic"})
    assert block.startswith("STORY STYLE")
    assert "High Fantasy" in block  # the option's prompt snippet, not the raw id
    assert "high_fantasy" not in block


def test_compose_custom_value_renders_labelled_line():
    block = style.compose_style_block({"genre": "Solarpunk western"})
    assert "Genre: Solarpunk western" in block


def test_compose_custom_instructions_appended_last():
    block = style.compose_style_block({
        "genre": "high_fantasy",
        "custom_instructions": "The moon is always full.",
    })
    assert block.rstrip().endswith("The moon is always full.")


def test_normalize_drops_unknown_keys_and_blanks():
    got = style.normalize_style_fields({
        "genre": " high_fantasy ", "bogus": "x", "tone": "", "custom_instructions": "  keep  ",
    })
    assert got == {"genre": "high_fantasy", "custom_instructions": "keep"}
    assert style.normalize_style_fields("not a dict") == {}


def test_wire_mapping_round_trips_camel_and_snake():
    # camelCase in → snake_case storage; only provided keys kept.
    assert style.from_wire({"writingStyle": "martin", "tone": None, "genre": ""}) == {
        "writing_style": "martin", "genre": "",
    }
    # snake_case storage → full camelCase response (every key present).
    wire = style.to_wire({"writing_style": "martin"})
    assert wire["writingStyle"] == "martin"
    assert wire["genre"] == "" and wire["customInstructions"] == ""
    assert set(wire) == set(style.WIRE_TO_KEY)


def test_migrate_legacy_tone_seeds_once_then_idempotent():
    assert style.migrate_legacy_tone(None, "Bleak and grim") == {"tone": "Bleak and grim"}
    assert style.migrate_legacy_tone(None, "") is None          # nothing to migrate
    assert style.migrate_legacy_tone({"tone": "epic"}, "Bleak") is None  # already chosen


def test_options_payload_omits_prompt_snippets():
    payload = style.options_payload()
    keys = [f["key"] for f in payload["fields"]]
    assert "genre" in keys and "writingStyle" in keys  # camelCase wire keys
    for field in payload["fields"]:
        assert set(field) == {"key", "label", "allowCustom", "options"}
        for opt in field["options"]:
            assert set(opt) == {"id", "label", "hint"}  # never "prompt"


def test_catalog_reload_picks_up_edits(tmp_path, monkeypatch):
    catalog = {"fields": [{"key": "genre", "label": "Genre", "allow_custom": True,
                           "options": [{"id": "noir", "label": "Noir", "hint": "", "prompt": "Genre: Noir."}]}]}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("WAYWARD_STYLE_CATALOG", str(path))
    style._cache = None  # drop any cache from the bundled catalog
    assert style.option_ids("genre") == ["noir"]
    # Add an option; a changed mtime must invalidate the mtime-keyed cache.
    catalog["fields"][0]["options"].append({"id": "cozy", "label": "Cozy", "hint": "", "prompt": "Genre: Cozy."})
    path.write_text(json.dumps(catalog), encoding="utf-8")
    import os
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert style.option_ids("genre") == ["noir", "cozy"]
    style._cache = None  # don't leak the temp catalog into other tests


# ── Integration: the /campaign-style routes ───────────────────────

def test_campaign_style_options_route(client):
    payload = client.get("/api/campaign-style/options").json()
    keys = [f["key"] for f in payload["fields"]]
    assert "genre" in keys and "perspective" in keys
    for field in payload["fields"]:
        for opt in field["options"]:
            assert "prompt" not in opt


def test_create_with_style_round_trips_and_stays_isolated(client):
    orig = client.get("/api/campaigns").json()["activeId"]
    try:
        res = client.post("/api/campaigns", json={
            "name": "Styled World",
            "style": {"genre": "space_opera", "writingStyle": "Custom Bard", "perspective": "third_person"},
        })
        assert res.status_code == 200, res.text

        got = client.get("/api/campaign-style").json()
        assert got["genre"] == "space_opera"
        assert got["writingStyle"] == "Custom Bard"   # custom free-text preserved
        assert got["perspective"] == "third_person"
        assert got["tone"] == ""

        # Partial PUT leaves untouched fields intact.
        put = client.put("/api/campaign-style", json={"tone": "epic"}).json()
        assert put["tone"] == "epic" and put["genre"] == "space_opera"

        # An empty string clears a field without disturbing the rest.
        cleared = client.put("/api/campaign-style", json={"genre": ""}).json()
        assert cleared["genre"] == "" and cleared["writingStyle"] == "Custom Bard"
    finally:
        client.post(f"/api/campaigns/{orig}/load")
