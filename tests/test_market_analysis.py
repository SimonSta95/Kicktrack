from app.market_analysis import enrich_market_entries, financing_scenarios


def test_market_analysis_exposes_transparent_personalized_and_investment_scores():
    squad = [
        {"name": "Own MF 1", "position": "MF", "market_value": 8_000_000, "average_points": 55},
        {"name": "Own MF 2", "position": "MF", "market_value": 10_000_000, "average_points": 65},
    ]
    rows = [
        {
            "name": "Opportunity",
            "position": "MF",
            "price": 9_000_000,
            "market_value": 10_000_000,
            "average_points": 90,
            "market_trend": 1,
            "offer_count": 3,
        },
        {
            "name": "Expensive",
            "position": "MF",
            "price": 13_000_000,
            "market_value": 10_000_000,
            "average_points": 30,
            "market_trend": 2,
            "offer_count": 0,
        },
    ]
    result = enrich_market_entries(rows, available_budget=10_000_000, squad=squad, points_are_current=True)
    by_name = {row["name"]: row for row in result}

    opportunity = by_name["Opportunity"]
    expensive = by_name["Expensive"]
    assert 0 <= opportunity["squad_fit_score"] <= 100
    assert 0 <= opportunity["investment_score"] <= 100
    assert opportunity["investment_score"] > expensive["investment_score"]
    assert opportunity["squad_fit_score"] > expensive["squad_fit_score"]
    assert "positionsbedarf" in opportunity["fit_breakdown"]
    assert "markttrend" in opportunity["investment_breakdown"]
    assert "FÜR DEINEN KADER" in opportunity["analysis_text"]
    assert "INVESTMENT" in opportunity["analysis_text"]


def test_preseason_investment_does_not_use_old_points():
    rows = [
        {
            "name": "A",
            "position": "ST",
            "price": 9_000_000,
            "market_value": 10_000_000,
            "average_points": 200,
            "market_trend": 1,
            "offer_count": 1,
        },
        {
            "name": "B",
            "position": "ST",
            "price": 9_000_000,
            "market_value": 10_000_000,
            "average_points": 5,
            "market_trend": 1,
            "offer_count": 1,
        },
    ]
    result = enrich_market_entries(rows, 20_000_000, [], points_are_current=False)
    assert result[0]["investment_score"] == result[1]["investment_score"]
    assert result[0]["investment_breakdown"]["punkte_effizienz"] == 0


def test_financing_scenarios_prefers_fewer_and_transfer_list_sales():
    squad = [
        {"player_id": "1", "name": "Starter", "market_value": 8_000_000, "player_role": "STAMM"},
        {"player_id": "2", "name": "Sell Me", "market_value": 6_000_000, "player_role": "TRANSFERLISTE"},
        {"player_id": "3", "name": "Open", "market_value": 4_000_000, "player_role": "OFFEN"},
    ]
    result = financing_scenarios(15_000_000, 10_000_000, squad)
    assert result["gap"] == 5_000_000
    assert result["directly_affordable"] is False
    assert result["scenarios"]
    assert result["scenarios"][0]["players"][0]["name"] == "Sell Me"
    assert result["scenarios"][0]["remaining_budget"] == 1_000_000


def test_financing_scenarios_direct_purchase():
    result = financing_scenarios(8_000_000, 10_000_000, [])
    assert result["directly_affordable"] is True
    assert result["remaining_budget"] == 2_000_000


def test_decision_layer_exposes_max_bid_confidence_replacement_and_horizon():
    squad = [{"name":"Own MF", "position":"MF", "market_value":6_000_000, "average_points":60}]
    rows = [{
        "player_id":"x", "name":"Candidate", "position":"MF", "price":7_000_000,
        "market_value":8_000_000, "average_points":90, "market_trend":1,
        "d1":80_000, "d3":180_000, "d7":350_000, "d14":500_000,
    }]
    result = enrich_market_entries(rows, 20_000_000, squad, points_are_current=True)[0]
    assert result["replacement_value"] == 30
    assert result["max_bid"] > 0
    assert result["max_bid"] <= int(result["market_value"] * 1.08) + 10_000
    assert result["confidence_label"] in {"GERING", "MITTEL", "HOCH"}
    assert result["investment_horizon"] in {"FLIP 1–3T", "TRADING 1W", "HOLD", "KEIN KLARER HORIZONT"}
    assert "Max-Bid" in result["analysis_text"]
    assert "Datenbasis" in result["analysis_text"]


def test_price_well_above_max_bid_can_force_pass():
    squad = [{"name":"Own MF", "position":"MF", "market_value":5_000_000, "average_points":50}]
    row = enrich_market_entries([{
        "player_id":"x", "name":"Too expensive", "position":"MF", "price":30_000_000,
        "market_value":10_000_000, "average_points":100, "market_trend":1
    }], 50_000_000, squad, points_are_current=True)[0]
    assert row["max_bid"] is not None
    assert row["signal"] == "PASSEN"
