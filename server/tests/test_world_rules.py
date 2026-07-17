"""R21: per-campaign World Rules — party size, currency, attributes, tone."""

from server.ai.rules import compose_rules_block, normalize_attributes


def test_normalize_attributes():
    assert normalize_attributes([{"name": " Might ", "description": " power "}, {"name": ""}, "Wits"]) == [
        {"name": "Might", "description": "power"},
        {"name": "Wits", "description": ""},
    ]
    assert normalize_attributes(None) == []


def test_compose_rules_block_skips_empties():
    assert compose_rules_block({}) == ""
    block = compose_rules_block({
        "party_size": 4, "currency_name": "Credits", "currency_abbrev": "cr",
        "currency_symbol": "¢", "attributes": [{"name": "Grit", "description": "toughness"}],
        "tone": "Noir.",
    })
    assert block.startswith("WORLD RULES")
    assert "up to 4 companion" in block
    assert "Currency: Credits (cr / ¢)." in block
    assert "Attributes: Grit — toughness." in block
    assert "Tone: Noir." in block


def test_campaign_rules_round_trip(client):
    # The boot Fantasy template seeds rules (Gold + attributes + tone).
    got = client.get("/api/campaign-rules").json()
    assert got["currencyName"] == "Gold"
    assert got["partySize"] == 3
    assert len(got["attributes"]) >= 1

    res = client.put("/api/campaign-rules", json={
        "partySize": 5,
        "currencyName": "Shards",
        "currencyAbbrev": "sh",
        "attributes": [{"name": "Focus", "description": ""}, {"name": "", "description": "dropped"}],
        "tone": "  Grim.  ",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["partySize"] == 5
    assert body["currencyName"] == "Shards"
    assert body["attributes"] == [{"name": "Focus", "description": ""}]  # nameless dropped
    assert body["tone"] == "Grim."
    # Persisted.
    assert client.get("/api/campaign-rules").json()["partySize"] == 5
    # partySize clamps to [0, 20].
    assert client.put("/api/campaign-rules", json={"partySize": 99}).json()["partySize"] == 20
