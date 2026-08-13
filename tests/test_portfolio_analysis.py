from datetime import datetime
from app.portfolio_analysis import BERLIN, analyze_portfolio, next_solvency_deadline


def test_preseason_uses_first_matchday_friday_deadline():
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    deadline = next_solvency_deadline(season_started=False, reference=ref)
    assert deadline.isoformat() == "2026-08-28T20:00:00+02:00"


def test_rotatable_squad_is_not_counted_as_cash_without_transferlist_role():
    market = [{
        "player_id": "buy",
        "market_value": 5_000_000,
        "price": 5_000_000,
        "effective_price": 5_000_000,
        "investment_score": 90,
        "squad_fit_score": 50,
        "fit_breakdown": {"qualitaet": 25, "replacement": 10},
        "d1": 150_000,
        "d3": 400_000,
        "d7": 700_000,
    }]
    squad = [{
        "player_id": "asset",
        "market_value": 15_000_000,
        "squad_value_score": 40,
        "trading_score": 30,
        "sell_decision_score": 80,
        "d1": -100_000,
        "d3": -200_000,
        "d7": -300_000,
    }]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    market_out, squad_out, summary = analyze_portfolio(
        market, squad, available_budget=-2_000_000, season_started=False, reference=ref
    )
    assert squad_out[0]["portfolio_role"] == "ROTATE/SELL"
    assert summary["projected_balance_before_new_buys"] == -2_000_000
    assert summary["transfer_list_capital"] == 0
    assert market_out[0]["portfolio_role"] == "PASS"
    assert market_out[0]["deadline_safe"] is False


def test_buy_is_blocked_if_projected_friday_balance_would_be_negative():
    market = [{
        "player_id": "buy",
        "market_value": 12_000_000,
        "price": 12_000_000,
        "effective_price": 12_000_000,
        "investment_score": 90,
        "squad_fit_score": 50,
        "fit_breakdown": {"qualitaet": 25, "replacement": 10},
        "d1": 200_000,
        "d3": 500_000,
        "d7": 900_000,
    }]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    market_out, _, _ = analyze_portfolio(
        market, [], available_budget=2_000_000, season_started=False, reference=ref
    )
    assert market_out[0]["portfolio_role"] == "PASS"
    assert market_out[0]["deadline_safe"] is False
    assert "Freitagssaldo" in market_out[0]["portfolio_block_reason"]


def test_strong_own_trading_asset_is_classified_as_invest_trade():
    squad = [{
        "player_id": "asset",
        "market_value": 5_000_000,
        "squad_value_score": 55,
        "trading_score": 85,
        "sell_decision_score": 35,
        "d1": 150_000,
        "d3": 400_000,
        "d7": 700_000,
    }]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    _, squad_out, _ = analyze_portfolio(
        [], squad, available_budget=5_000_000, season_started=False, reference=ref
    )
    assert squad_out[0]["portfolio_role"] == "INVEST/TRADE"
    assert squad_out[0]["expected_capital_return_pct"] > 1.0


def test_only_explicit_transferlist_players_count_as_sale_context():
    squad = [
        {"player_id": "listed", "market_value": 7_000_000, "player_role": "TRANSFERLISTE", "squad_value_score": 40, "trading_score": 70, "sell_decision_score": 60, "d1": 100_000},
        {"player_id": "hold", "market_value": 20_000_000, "player_role": "STAMM", "squad_value_score": 90, "trading_score": 80, "sell_decision_score": 10, "d1": 100_000},
    ]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    _, squad_out, summary = analyze_portfolio([], squad, available_budget=3_000_000, season_started=False, reference=ref)
    assert summary["transfer_list_capital"] == 7_000_000
    assert summary["projected_balance_before_new_buys"] == 3_000_000
    assert squad_out[0]["action"] == "VERKAUF WARTEN"
    assert squad_out[1]["action"] == "HALTEN"


def test_committed_bids_reduce_real_deadline_balance():
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    _, _, summary = analyze_portfolio([], [], available_budget=43_946_455, committed_budget=38_280_001, season_started=False, reference=ref)
    assert summary["balance_after_commitments"] == 5_666_454
    assert summary["projected_balance_before_new_buys"] == 5_666_454


def test_preseason_market_uses_kaderziel_instead_of_cant_miss():
    market = [{
        "player_id": "target",
        "market_value": 20_000_000,
        "price": 20_000_000,
        "effective_price": 20_000_000,
        "investment_score": 55,
        "squad_fit_score": 90,
        "fit_breakdown": {"qualitaet": 50, "replacement": 24},
        "d1": 20_000,
        "d3": 60_000,
        "d7": 100_000,
    }]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    rows, _, _ = analyze_portfolio(market, [], available_budget=30_000_000, season_started=False, reference=ref)
    assert rows[0]["portfolio_role"] == "KADERZIEL"
    assert rows[0]["action"] == "KADERZIEL"


def test_preseason_invest_role_has_simple_invest_action():
    market = [{
        "player_id": "trade",
        "market_value": 5_000_000,
        "price": 5_000_000,
        "effective_price": 5_000_000,
        "investment_score": 88,
        "squad_fit_score": 45,
        "fit_breakdown": {"qualitaet": 20, "replacement": 8},
        "d1": 160_000,
        "d3": 420_000,
        "d7": 760_000,
    }]
    ref = datetime(2026, 8, 13, 10, 0, tzinfo=BERLIN)
    rows, _, _ = analyze_portfolio(market, [], available_budget=15_000_000, season_started=False, reference=ref)
    assert rows[0]["portfolio_role"] == "INVEST"
    assert rows[0]["action"] == "INVEST"
