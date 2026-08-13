from app.kickbase import KickbaseClient


def test_budget_overview_combines_balance_listings_and_active_bids(monkeypatch):
    client = KickbaseClient()

    budget = {"b": 5_000_000}
    market = {
        "players": [
            {
                "id": "sell-1",
                "firstName": "Own",
                "lastName": "Player",
                "userId": "me",
                "price": 20_000_000,
                "marketValue": 18_000_000,
                "offers": [{"id": "incoming", "price": 21_000_000}],
            },
            {
                "id": "buy-1",
                "firstName": "Target",
                "lastName": "One",
                "userId": "other",
                "price": 16_000_000,
                "offers": [{"id": "mine", "price": 10}],
            },
            {
                "id": "buy-2",
                "firstName": "Target",
                "lastName": "Two",
                "userId": "other2",
                "price": 20_000_000,
                "offers": [{"id": "mine2", "price": 20_000_000}],
            },
        ]
    }

    def fake_get(path, *, params=None):
        return budget if path.endswith("/me/budget") else market

    monkeypatch.setattr(client, "_get_json", fake_get)
    result = client.budget_overview("league", "me", {"sell-1"})
    client.close()

    assert result["balance"] == 5_000_000
    assert result["transfer_list_value"] == 20_000_000
    assert result["committed"] == 20_000_010
    assert result["total_budget"] == 25_000_000
    assert result["rest_budget"] == 4_999_990
    assert result["rest_without_sales"] == -15_000_010
    assert [bid["name"] for bid in result["active_bids"]] == ["Target One", "Target Two"]


def test_budget_overview_can_identify_own_listing_by_squad_id(monkeypatch):
    client = KickbaseClient()
    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, *, params=None: {"budget": 1_000_000}
        if path.endswith("/me/budget")
        else {"it": [{"i": "42", "n": "Listed", "prc": 3_500_000}]},
    )
    result = client.budget_overview("league", None, {"42"})
    client.close()

    assert result["transfer_list_value"] == 3_500_000
    assert result["total_budget"] == 4_500_000


def test_budget_overview_parses_compact_v4_own_offer_and_reconciles_pbaa(monkeypatch):
    client = KickbaseClient()
    budget = {"b": 34_863_027, "pbaa": 27_913_027, "pbas": 34_863_027}
    market = {
        "it": [
            {
                "i": "8277",
                "fn": "Vitalie",
                "n": "Becker",
                "mv": 6_865_611,
                "tfhmvt": 185_432,
                "prc": 6_865_611,
                "ofc": 1,
                "uop": 6_950_000,
                "uoid": "3979846",
                "ofs": [
                    {
                        "u": "3979846",
                        "unm": "Simon",
                        "uoid": "3979846",
                        "uop": 6_950_000,
                        "st": 0,
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, *, params=None: budget if path.endswith("/me/budget") else market,
    )
    result = client.budget_overview("5012647", "3979846", set())
    client.close()

    assert result["balance"] == 34_863_027
    assert result["committed"] == 6_950_000
    assert result["rest_without_sales"] == 27_913_027
    assert result["rest_budget"] == 27_913_027
    assert len(result["active_bids"]) == 1
    assert result["active_bids"][0]["name"] == "Becker"
    assert result["active_bids"][0]["bid"] == 6_950_000


def test_budget_overview_does_not_count_other_users_compact_offer(monkeypatch):
    client = KickbaseClient()
    market = {
        "it": [
            {
                "i": "1",
                "n": "Other Bid",
                "uop": 9_000_000,
                "uoid": "someone-else",
                "ofs": [{"u": "someone-else", "uop": 9_000_000}],
            }
        ]
    }
    monkeypatch.setattr(
        client,
        "_get_json",
        lambda path, *, params=None: {"b": 5_000_000, "pbaa": 5_000_000}
        if path.endswith("/me/budget")
        else market,
    )
    result = client.budget_overview("league", "me", set())
    client.close()

    assert result["active_bids"] == []
    assert result["committed"] == 0


def test_market_overview_exposes_full_market_player_context(monkeypatch):
    client = KickbaseClient()
    budget = {"b": 10_000_000, "pbaa": 8_000_000}
    market = {
        "it": [
            {
                "i": "8277",
                "fn": "Vitalie",
                "n": "Becker",
                "tid": "8",
                "pos": 2,
                "mv": 6_865_611,
                "tfhmvt": 185_432,
                "prc": 6_865_611,
                "p": 100,
                "ap": 50,
                "ofc": 1,
                "uoid": "me",
                "uop": 6_950_000,
                "ofs": [{"u": "me", "uop": 6_950_000}],
            }
        ]
    }
    monkeypatch.setattr(client, "_get_json", lambda path, *, params=None: budget if path.endswith("/me/budget") else market)
    result = client.market_overview("league", "me", set())
    client.close()

    player = result["market_entries"][0]
    assert player["full_name"] == "Vitalie Becker"
    assert player["club"] == "Schalke"
    assert player["position"] == "ABW"
    assert player["own_bid"] == 6_950_000
    assert player["average_points"] == 50
    assert player["daily_change"] == 185_432
    assert player["d1"] == 185_432


def test_market_overview_hides_previous_season_points_before_market_start(monkeypatch):
    client = KickbaseClient()
    budget = {"b": 10_000_000, "pbaa": 10_000_000}
    market = {
        "dt": "2999-08-28T18:30:00Z",
        "it": [{"i": "1", "fn": "Old", "n": "Points", "tid": "2", "pos": 3, "mv": 5_000_000, "prc": 5_000_000, "p": 3000, "ap": 90}],
    }
    monkeypatch.setattr(client, "_get_json", lambda path, *, params=None: budget if path.endswith("/me/budget") else market)
    result = client.market_overview("league", "me", set())
    client.close()
    assert result["points_are_current"] is False
    assert result["market_entries"][0]["points_total"] is None
    assert result["market_entries"][0]["average_points"] is None
