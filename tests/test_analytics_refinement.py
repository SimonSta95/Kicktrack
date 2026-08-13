from app.intelligence import player_form, trade_profile, fixture_run
from app.market_analysis import enrich_market_entries


def test_player_form_exposes_robust_distribution_metrics():
    payload = {"it": [{"ph": [{"day": i + 1, "p": p} for i, p in enumerate([20, 60, 80, 100, 140])]}]}
    form = player_form(payload)
    assert form["median"] == 80
    assert form["robust_floor"] == 60
    assert form["robust_ceiling"] >= 100
    assert form["hit100"] == 40


def test_market_scoring_retires_fair_value_and_keeps_league_deals_as_context():
    rows = [
        {"player_id": "1", "position": "MF", "market_value": 10_000_000, "price": 9_000_000, "average_points": 100, "d3": 300_000, "d7": 500_000},
        {"player_id": "2", "position": "MF", "market_value": 10_000_000, "price": 10_000_000, "average_points": 80},
    ]
    transfers = [
        {"player_id": "1", "price": 11_000_000, "transfer_type": "BUY", "transferred_at": "2026-08-01T10:00:00+00:00"},
        {"player_id": "1", "price": 10_500_000, "transfer_type": "SELL", "transferred_at": "2026-08-02T10:00:00+00:00"},
    ]
    enriched = enrich_market_entries(rows, 20_000_000, [], points_are_current=True, league_transfers=transfers)
    first = enriched[0]
    assert first["fair_value"] is None
    assert first["league_deal_count"] == 2
    assert "Liga-Deals nur Kontext" in first["analysis_text"]
    assert "MW-Momentum" in first["analysis_text"]


def test_trade_profile_matches_realized_pnl_and_holding_time():
    transfers = [
        {"player_id": "1", "transfer_type": "BUY", "price": 5_000_000, "transferred_at": "2026-08-01T10:00:00+00:00"},
        {"player_id": "1", "transfer_type": "SELL", "price": 6_000_000, "transferred_at": "2026-08-04T10:00:00+00:00"},
    ]
    profile = trade_profile(transfers)
    assert profile["realized_pnl"] == 1_000_000
    assert profile["matched_trades"] == 1
    assert profile["avg_hold_days"] == 3


def test_fixture_has_home_adjusted_ease_without_changing_base_ease():
    fixtures = {"value": {"day": 1, "it": [{"day": 1, "it": [{"t1": "1", "t2": "2"}]}]}}
    table = {"value": {"it": [{"tid": "1", "cp": 1}, {"tid": "2", "cp": 2}]}}
    run = fixture_run("1", fixtures, table)
    assert run[0]["ease"] == 100
    assert run[0]["adjusted_ease"] == 100
