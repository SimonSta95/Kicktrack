from app.kickbase import KickbaseClient


def test_manager_transfer_history_paginates_and_deduplicates_without_looping():
    client = KickbaseClient()
    calls = []

    page1 = [{"pi": str(i), "tty": 1, "trp": i, "dt": f"2026-08-01T00:{i:02d}:00Z"} for i in range(20)]
    page2 = [{"pi": "20", "tty": 2, "trp": 99, "dt": "2026-08-02T00:00:00Z"}]

    def fake_get(path, *, params=None):
        calls.append(params)
        if not params:
            return {"u": "m1", "it": page1}
        if params.get("start") == 20:
            return {"u": "m1", "it": page2}
        return {"u": "m1", "it": []}

    client._get_json = fake_get
    result = client.manager_transfers("l1", "m1")
    client.close()

    assert len(result["it"]) == 21
    assert calls == [None, {"start": 20}]


def test_market_value_history_prefers_competition_365_endpoint(monkeypatch):
    from app.kickbase import KickbaseClient

    client = KickbaseClient()
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        return {"it": [{"d": 20000, "mv": 1_000_000}]}

    monkeypatch.setattr(client, "_get_json", fake_get)
    payload = client.market_value_history("league", "player", 365)
    assert payload["it"]
    assert calls[0][0] == "/v4/competitions/1/players/player/marketValue/365"
    client.close()


def test_player_details_merges_localized_status_text(monkeypatch):
    from app.kickbase import KickbaseClient

    client = KickbaseClient()

    def fake_get(path, params=None):
        if path.startswith("/v4/leagues/"):
            return {"i": "7", "n": "Spieler", "tid": 1, "pos": 3, "mv": 2_000_000, "st": 2}
        return {"i": "7", "fn": "Max", "ln": "Spieler", "st": 2, "stxt": "Individuelles Training"}

    monkeypatch.setattr(client, "_get_json", fake_get)
    details = client.player_details("league", "7")
    assert details["status"] == 2
    assert details["status_text"] == "Individuelles Training"
    client.close()


def test_market_overview_reads_only_canonical_st_fields(monkeypatch):
    from app.kickbase import KickbaseClient

    client = KickbaseClient()

    def fake_budget_overview(league_id, manager_id=None, owned_player_ids=None):
        return {
            "market_raw": {
                "it": [{
                    "pi": "42", "fn": "Max", "pn": "Mustermann", "tid": 1,
                    "pos": 3, "mv": 3_000_000, "prc": 3_000_000,
                    "st": 2, "stl": [2], "status": 5,
                }]
            },
            "balance": 10_000_000,
            "rest_budget": 10_000_000,
            "rest_without_sales": 10_000_000,
            "committed": 0,
            "active_bids": [],
            "own_listings": [],
            "transfer_list_value": 0,
            "total_budget": 10_000_000,
        }

    monkeypatch.setattr(client, "budget_overview", fake_budget_overview)
    result = client.market_overview("l1")
    row = result["market_entries"][0]
    assert row["status"] == 2
    assert row["status_list"] == [2]
    assert row["status"] != 5
    client.close()


def test_place_market_offer_posts_price_to_documented_endpoint(monkeypatch):
    from app.kickbase import KickbaseClient

    class Response:
        status_code = 200
        content = b'{"ok":true}'
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    client = KickbaseClient()
    seen = {}

    def fake_post(path, json=None):
        seen["path"] = path
        seen["json"] = json
        return Response()

    monkeypatch.setattr(client.client, "post", fake_post)
    result = client.place_market_offer("league-1", "player-7", 12_300_000)
    assert result == {"ok": True}
    assert seen == {
        "path": "/v4/leagues/league-1/market/player-7/offers",
        "json": {"price": 12_300_000},
    }
    client.close()


def test_list_player_for_sale_uses_single_market_post(monkeypatch):
    from app.kickbase import KickbaseClient

    class Response:
        status_code = 200
        content = b'{}'
        text = "{}"

        @staticmethod
        def json():
            return {"ok": True}

    client = KickbaseClient()
    seen = {}

    def fake_post(path, json=None):
        seen["path"] = path
        seen["json"] = json
        return Response()

    monkeypatch.setattr(client.client, "post", fake_post)
    result = client.list_player_for_sale("l1", "p1", 5_500_000)

    assert result["ok"] is True
    assert result["price_set"] is True
    assert result["requested_price"] == 5_500_000
    assert seen["path"] == "/v4/leagues/l1/market"
    assert seen["json"]["pi"] == "p1"
    assert seen["json"]["prc"] == 5_500_000.0
    assert isinstance(seen["json"]["prc"], float)
    client.close()


def test_list_player_for_sale_surfaces_market_write_error(monkeypatch):
    from app.kickbase import KickbaseClient, KickbaseError

    class Response:
        status_code = 500
        content = b'{}'
        text = '{"err":2,"errMsg":"NotFound","svcs":[]}'

        @staticmethod
        def json():
            return {"err": 2, "errMsg": "NotFound", "svcs": []}

    client = KickbaseClient()
    monkeypatch.setattr(client.client, "post", lambda path, json=None: Response())

    try:
        client.list_player_for_sale("l1", "p1", 5_500_000)
    except KickbaseError as exc:
        assert "Spieler anbieten fehlgeschlagen" in str(exc)
    else:
        raise AssertionError("Expected KickbaseError")
    finally:
        client.close()


def test_normalize_incoming_offers_parses_manager_and_kickbase():
    client = KickbaseClient()
    payload = {
        "ofs": [
            {"i": "o2", "prc": 5_200_000, "u": {"i": "m2", "n": "Max"}},
            {"i": "kb", "prc": 5_000_000},
        ]
    }
    offers = client.normalize_incoming_offers(payload)
    assert offers[0]["offer_id"] == "o2"
    assert offers[0]["user_name"] == "Max"
    assert offers[0]["is_kickbase"] is False
    assert offers[1]["is_kickbase"] is True
    client.close()


def test_unverified_offer_writes_are_blocked_without_network(monkeypatch):
    from app.kickbase import KickbaseClient, KickbaseError

    client = KickbaseClient()
    calls = []
    monkeypatch.setattr(client.client, "post", lambda *args, **kwargs: calls.append(("POST", args, kwargs)))
    monkeypatch.setattr(client.client, "delete", lambda *args, **kwargs: calls.append(("DELETE", args, kwargs)))

    for action in (
        lambda: client.accept_manager_offer("l1", "p1", "o1"),
        lambda: client.decline_manager_offer("l1", "p1", "o1"),
    ):
        try:
            action()
        except KickbaseError:
            pass
        else:
            raise AssertionError("Expected KickbaseError for unverified offer action")

    assert calls == []
    client.close()

def test_accept_kickbase_sale_offer_uses_verified_sell_post_without_body(monkeypatch):
    from app.kickbase import KickbaseClient

    class Response:
        status_code = 200
        content = b'{}'
        text = "{}"

        @staticmethod
        def json():
            return {}

    client = KickbaseClient()
    seen = {}

    def fake_post(path, **kwargs):
        seen["path"] = path
        seen["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(client.client, "post", fake_post)
    result = client.accept_kickbase_sale_offer("l1", "p1")

    assert result == {}
    assert seen["path"] == "/v4/leagues/l1/market/p1/sell"
    assert seen["kwargs"] == {}
    client.close()

