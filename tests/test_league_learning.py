from app.league_learning import build_league_purchase_learning, estimate_winning_price, normalize_market_value_history


def test_normalize_epoch_day_history():
    rows = normalize_market_value_history({"it": [{"d": 20678, "mv": 10_000_000}]})
    assert rows and rows[0]["value"] == 10_000_000
    assert len(rows[0]["snapshot_date"]) == 10


def test_build_learning_excludes_own_manager_and_reconstructs_premium_and_outcome():
    transfers = [
        {"manager_id": "other", "player_id": "p1", "player_name": "A", "transfer_type": "BUY", "price": 11_000_000, "transferred_at": "2026-08-01T12:00:00Z"},
        {"manager_id": "me", "player_id": "p2", "player_name": "B", "transfer_type": "BUY", "price": 5_000_000, "transferred_at": "2026-08-01T12:00:00Z"},
        {"manager_id": "other", "player_id": "p1", "player_name": "A", "transfer_type": "SELL", "price": 12_000_000, "transferred_at": "2026-08-08T12:00:00Z"},
    ]
    histories = {"p1": [
        {"snapshot_date": "2026-08-01", "value": 10_000_000},
        {"snapshot_date": "2026-08-04", "value": 12_100_000},
        {"snapshot_date": "2026-08-08", "value": 12_500_000},
    ]}
    result = build_league_purchase_learning(transfers, own_manager_id="me", manager_names={"other": "Rival"}, histories=histories)
    assert result["external_buy_count"] == 1
    assert result["premium_sample_count"] == 1
    assert round(result["median_premium_pct"], 1) == 10.0
    assert round(result["median_buyer_return_3d_pct"], 1) == 10.0
    assert result["buys"][0]["manager_name"] == "Rival"


def test_winning_price_uses_bucket_only_with_enough_samples():
    learning = {
        "premium_sample_count": 5,
        "median_premium_pct": 7.0,
        "bucket_stats": {"10–20 Mio.": {"count": 3, "median_premium_pct": 12.0}},
    }
    result = estimate_winning_price(15_000_000, learning)
    assert result["price"] == 16_800_000
    assert result["premium_pct"] == 12.0
    assert result["source"] == "10–20 Mio."


def test_winning_price_does_not_guess_with_tiny_sample():
    result = estimate_winning_price(10_000_000, {"premium_sample_count": 2, "median_premium_pct": 25.0, "bucket_stats": {}})
    assert result["price"] is None


def test_active_bid_marks_good_chance_and_hold_below_ceiling():
    from app.league_learning import evaluate_active_bid
    result = evaluate_active_bid(
        bid=10_300_000,
        max_bid=10_800_000,
        winning={"price": 10_200_000, "sample_count": 8},
    )
    assert result["league_chance"] == "KNAPP"
    assert result["bid_action"] == "HALTEN"


def test_active_bid_does_not_chase_league_price_above_max_bid():
    from app.league_learning import evaluate_active_bid
    result = evaluate_active_bid(
        bid=10_400_000,
        max_bid=10_500_000,
        winning={"price": 11_200_000, "sample_count": 12},
    )
    assert result["league_chance"] == "UNWAHRSCHEINLICH"
    assert result["bid_action"] == "NICHT ERHÖHEN"


def test_active_bid_above_economic_ceiling_is_withdraw():
    from app.league_learning import evaluate_active_bid
    result = evaluate_active_bid(
        bid=11_000_000,
        max_bid=10_500_000,
        winning={"price": 11_100_000, "sample_count": 9},
    )
    assert result["bid_action"] == "ZURÜCKZIEHEN"


def test_active_bid_can_suggest_raise_only_inside_ceiling():
    from app.league_learning import evaluate_active_bid
    result = evaluate_active_bid(
        bid=9_800_000,
        max_bid=10_800_000,
        winning={"price": 10_300_000, "sample_count": 6},
    )
    assert result["league_chance"] == "UNWAHRSCHEINLICH"
    assert result["bid_action"] == "ERHÖHEN PRÜFEN"


def test_learning_builds_momentum_profiles_and_premium_outcomes():
    transfers = []
    histories = {}
    for idx, price in enumerate((10_200_000, 10_300_000, 10_350_000), start=1):
        pid = f"p{idx}"
        transfers.append({
            "manager_id": "other", "player_id": pid, "player_name": pid,
            "transfer_type": "BUY", "price": price,
            "transferred_at": "2026-08-08T12:00:00Z",
        })
        histories[pid] = [
            {"snapshot_date": "2026-08-01", "value": 9_000_000},
            {"snapshot_date": "2026-08-05", "value": 9_600_000},
            {"snapshot_date": "2026-08-08", "value": 10_000_000},
            {"snapshot_date": "2026-08-15", "value": 11_000_000},
        ]
    result = build_league_purchase_learning(transfers, histories=histories)
    assert "STARK STEIGEND" in result["investment_profiles"] or "STEIGEND" in result["investment_profiles"]
    assert result["premium_outcomes"]["0–4%"]["count"] == 3
    assert result["profitable_premium_band"] == "0–4%"


def test_estimate_investment_outcome_matches_current_momentum_profile():
    from app.league_learning import estimate_investment_outcome
    learning = {
        "investment_profiles": {
            "STARK STEIGEND": {
                "count": 5,
                "median_buyer_return_7d_pct": 4.5,
                "profitable_rate_7d": 0.8,
            }
        }
    }
    result = estimate_investment_outcome(
        market_value=10_000_000, d3=300_000, d7=700_000, learning=learning
    )
    assert result["profile"] == "STARK STEIGEND"
    assert result["label"] == "HISTORISCH STARK"
    assert result["median_return_7d_pct"] == 4.5


def test_premium_outcome_flags_historically_bad_overpay_band():
    from app.league_learning import evaluate_premium_outcome
    learning = {
        "premium_outcomes": {
            "8–12%": {
                "count": 6,
                "median_buyer_return_7d_pct": -2.0,
                "profitable_rate_7d": 0.33,
            }
        }
    }
    result = evaluate_premium_outcome(bid=11_000_000, market_value=10_000_000, learning=learning)
    assert result["band"] == "8–12%"
    assert result["label"] == "OVERPAY-RISIKO"


def test_historical_calibration_can_stop_raise_but_never_increase_ceiling():
    from app.league_learning import calibrate_bid_action
    base = {"bid_action": "ERHÖHEN PRÜFEN", "bid_action_tone": "positive"}
    result = calibrate_bid_action(
        base,
        investment_outcome={"label": "HISTORISCH OK", "sample_count": 5},
        premium_outcome={"label": "OVERPAY-RISIKO", "sample_count": 6},
    )
    assert result["bid_action"] == "NICHT ERHÖHEN"
    assert result["historical_veto"] is True
