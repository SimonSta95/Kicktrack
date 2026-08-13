from datetime import datetime, timedelta, timezone

from app.coach_analysis import build_coach_recommendations


def market_row(**overrides):
    row = {
        "player_id": "1", "name": "Mario Götze", "full_name": "Mario Götze",
        "club": "Frankfurt", "position": "MF", "price": 2_880_204,
        "market_value": 4_369_039, "is_kickbase": False, "seller_id": "s1",
        "seller_name": "Kelzi95", "max_bid": 4_500_000, "investment_score": 80,
        "squad_fit_score": 60, "signal": "INVEST-CHANCE", "market_trend": 1,
        "d1": 150_000, "d7": 700_000, "confidence_label": "MITTEL",
        "investment_horizon": "TRADING 1W",
        "listed_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
    }
    row.update(overrides)
    return row


def test_old_manager_listing_below_mv_is_not_treated_as_lowball():
    recs = build_coach_recommendations([market_row()], [], managers=[])
    assert recs[0]["label"] == "MANAGER-DEAL PRÜFEN"
    assert "4.369.039" in recs[0]["action"]
    assert "Listing ist veraltet" in recs[0]["action"]


def test_kickbase_buy_is_planable():
    row = market_row(is_kickbase=True, seller_id=None, seller_name="Kickbase", signal="KAUFEN", price=4_000_000)
    recs = build_coach_recommendations([row], [])
    assert recs[0]["label"] == "KAUFEN"
    assert recs[0]["planability"] == "HOCH"


def test_negative_budget_is_highest_priority_warning():
    recs = build_coach_recommendations([], [], available_budget=-7_750_000)
    assert recs[0]["label"] == "BUDGET ENTLASTEN"
    assert recs[0]["priority"] == 100


def test_stale_manager_listings_are_capped_as_manager_deals():
    rows = [market_row(player_id=str(i), name=f"Player {i}", full_name=f"Player {i}") for i in range(8)]
    recs = build_coach_recommendations(rows, [], managers=[], available_budget=10_000_000)
    assert sum(1 for rec in recs if rec["kind"] == "manager_buy") == 2
    assert not any(rec["label"] == "LOWBALL-CHANCE" for rec in recs)


def test_negative_budget_suppresses_manager_buy_suggestions():
    recs = build_coach_recommendations([market_row()], [], managers=[], available_budget=-1_000_000)
    assert recs[0]["label"] == "BUDGET ENTLASTEN"
    assert not any(rec["kind"] == "manager_buy" for rec in recs)


def test_manager_deals_are_capped_to_two():
    rows = [
        market_row(
            player_id=str(i),
            name=f"Manager Deal {i}",
            full_name=f"Manager Deal {i}",
            price=4_000_000,
            market_value=4_200_000,
            max_bid=4_500_000,
            listed_at=(datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
            investment_score=80,
            squad_fit_score=80,
            d1=10_000,
            d7=20_000,
        )
        for i in range(6)
    ]
    recs = build_coach_recommendations(rows, [], managers=[], available_budget=20_000_000)
    assert sum(1 for rec in recs if rec["kind"] == "manager_buy") == 2


def test_negative_budget_suppresses_all_buy_suggestions():
    manager = market_row(
        player_id="m", name="Manager Buy", full_name="Manager Buy",
        price=4_000_000, market_value=4_200_000, max_bid=4_500_000,
        listed_at=(datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
        investment_score=90, squad_fit_score=90,
    )
    kickbase = market_row(
        player_id="k", name="Kickbase Buy", full_name="Kickbase Buy",
        is_kickbase=True, seller_id=None, seller_name="Kickbase",
        signal="KAUFEN", price=4_000_000, max_bid=4_500_000,
    )
    recs = build_coach_recommendations([manager, kickbase], [], available_budget=-500_000)
    assert recs[0]["label"] == "BUDGET ENTLASTEN"
    assert not any(rec["kind"] in {"manager_buy", "kickbase_buy"} for rec in recs)
