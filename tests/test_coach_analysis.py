from app.coach_analysis import build_coach_recommendations


def market_row(**overrides):
    row = {
        "player_id": "1",
        "name": "Test",
        "full_name": "Test Player",
        "club": "Leipzig",
        "position": "MF",
        "market_value": 5_000_000,
        "price": 5_050_000,
        "facts_signal": "INTERESSANT",
        "mv_trend": {"label": "STABIL STEIGEND", "code": "STABLE_UP", "streak": 5, "steps_text": "+90k · +95k · +101k · +99k"},
        "trend_reversal_prediction": {"risk": "NIEDRIG", "probability": 0.18, "sample_count": 70},
        "is_kickbase": True,
    }
    row.update(overrides)
    return row


def test_interesting_market_player_becomes_transparent_trading_candidate():
    recs = build_coach_recommendations([market_row()], [])
    assert recs[0]["label"] == "TRADING-KANDIDAT"
    assert any("Refreshes" in reason for reason in recs[0]["reasons"])
    assert not any("/100" in reason for reason in recs[0]["reasons"])


def test_negative_budget_is_highest_priority_fact_warning():
    recs = build_coach_recommendations([], [], available_budget=-7_750_000)
    assert recs[0]["label"] == "LIQUIDITÄT PRÜFEN"
    assert "-7750000" in recs[0]["reasons"][0].replace(".", "")


def test_active_bid_is_shown_as_active_bid_not_player_score():
    recs = build_coach_recommendations([market_row(own_bid=5_100_000)], [])
    assert recs[0]["label"] == "GEBOT LÄUFT"
    assert recs[0]["kind"] == "bid"


def test_cooling_market_player_is_not_presented_as_buy_score():
    row = market_row(
        facts_signal="ABKÜHLEND",
        mv_trend={"label": "VERLANGSAMEND", "code": "SLOWING_UP", "streak": 6, "steps_text": "+180k · +140k · +90k · +40k"},
        trend_reversal_prediction={"risk": "HOCH", "probability": 0.61, "sample_count": 90},
    )
    recs = build_coach_recommendations([row], [])
    assert recs[0]["label"] == "ABKÜHLEND"
    assert any("Wende-Risiko" in reason for reason in recs[0]["reasons"])
