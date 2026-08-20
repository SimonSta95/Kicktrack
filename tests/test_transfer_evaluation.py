from app.transfer_evaluation import evaluate_trade_cycles, transfer_evaluation_summary


def test_buy_and_sale_are_one_trade_cycle_with_7d_exit_timing():
    transfers = [
        {"player_id": "p1", "player_name": "A", "club": "X", "transfer_type": "BUY", "price": 10_000_000, "transferred_at": "2026-08-01T12:00:00+00:00"},
        {"player_id": "p1", "player_name": "A", "club": "X", "transfer_type": "SELL", "price": 12_000_000, "transferred_at": "2026-08-05T12:00:00+00:00"},
    ]
    histories = {"p1": [
        {"snapshot_date": "2026-08-01", "value": 9_800_000, "recorded_at": "2026-08-01T22:00:00+00:00"},
        {"snapshot_date": "2026-08-05", "value": 11_700_000, "recorded_at": "2026-08-05T22:00:00+00:00"},
        {"snapshot_date": "2026-08-08", "value": 11_000_000, "recorded_at": "2026-08-08T22:00:00+00:00"},
        {"snapshot_date": "2026-08-12", "value": 10_500_000, "recorded_at": "2026-08-12T22:00:00+00:00"},
    ]}
    rows = evaluate_trade_cycles(transfers, histories)
    assert len(rows) == 1
    trade = rows[0]
    assert trade["cycle_type"] == "CLOSED_TRADE"
    assert trade["buy_price"] == 10_000_000
    assert trade["sell_price"] == 12_000_000
    assert trade["result_pnl"] == 2_000_000
    assert round(trade["roi_pct"], 1) == 20.0
    # Exit timing is measured against market value at sale (11.7m), not sale price.
    assert trade["post_7d_delta"] == -1_200_000
    assert trade["exit_verdict"] == "TOP-EXIT"
    assert trade["verdict"] == "TOP-TRADE"


def test_open_negative_buy_is_not_called_fehlkauf():
    transfers = [
        {"player_id": "p2", "player_name": "Open", "transfer_type": "BUY", "price": 5_000_000, "transferred_at": "2026-08-01T12:00:00+00:00"}
    ]
    histories = {"p2": [
        {"snapshot_date": "2026-08-10", "value": 4_000_000, "recorded_at": "2026-08-10T22:00:00+00:00"}
    ]}
    row = evaluate_trade_cycles(transfers, histories)[0]
    assert row["cycle_type"] == "OPEN_TRADE"
    assert round(row["roi_pct"], 1) == -20.0
    assert row["financial_verdict"] == "FINANZIELL SCHWACH"
    assert row["verdict"] == "OFFENER TRADE"


def test_preseason_loss_trade_is_not_fehlkauf_without_sporting_evidence():
    transfers = [
        {"player_id": "p3", "player_name": "A", "transfer_type": "BUY", "price": 10_000_000, "transferred_at": "2026-08-01T12:00:00+00:00"},
        {"player_id": "p3", "player_name": "A", "transfer_type": "SELL", "price": 8_000_000, "transferred_at": "2026-08-05T12:00:00+00:00"},
    ]
    row = evaluate_trade_cycles(transfers, {})[0]
    assert row["roi_pct"] == -20.0
    assert row["sport_points"] is None
    assert row["verdict"] == "VERLUST-TRADE"


def test_fehlkauf_requires_financial_loss_and_weak_sporting_output():
    transfers = [
        {"player_id": "p4", "player_name": "A", "transfer_type": "BUY", "price": 10_000_000, "transferred_at": "2026-08-01T12:00:00+00:00"},
        {"player_id": "p4", "player_name": "A", "transfer_type": "SELL", "price": 8_000_000, "transferred_at": "2026-08-20T12:00:00+00:00"},
    ]
    performance = {"p4": {"it": [{"ph": [
        {"p": 30, "md": "2026-08-05T13:30:00Z"},
        {"p": 40, "md": "2026-08-12T13:30:00Z"},
    ]}]}}
    row = evaluate_trade_cycles(transfers, {}, performance)[0]
    assert row["sport_games"] == 2
    assert row["sport_avg"] == 35.0
    assert row["verdict"] == "FEHLKAUF"


def test_first_sell_with_pre_sale_history_is_reconstructed_as_start_inventory():
    transfers = [{"player_id": "p5", "player_name": "Start", "transfer_type": "SELL", "price": 8_000_000, "transferred_at": "2026-08-02T12:00:00+00:00"}]
    histories = {"p5": [
        {"snapshot_date": "2026-08-01", "value": 7_900_000, "recorded_at": "2026-08-01T22:00:00+00:00"},
        {"snapshot_date": "2026-08-02", "value": 8_000_000, "recorded_at": "2026-08-02T22:00:00+00:00"},
        {"snapshot_date": "2026-08-05", "value": 7_600_000, "recorded_at": "2026-08-05T22:00:00+00:00"},
        {"snapshot_date": "2026-08-09", "value": 7_000_000, "recorded_at": "2026-08-09T22:00:00+00:00"},
    ]}
    row = evaluate_trade_cycles(transfers, histories)[0]
    assert row["cycle_type"] == "CLOSED_START_SQUAD_TRADE"
    assert row["entry_source"] == "STARTBESTAND_REKONSTRUIERT"
    assert row["buy_price"] == 7_900_000
    assert row["sell_price"] == 8_000_000
    assert row["result_pnl"] == 100_000
    assert round(row["roi_pct"], 2) == round(100_000 / 7_900_000 * 100, 2)
    assert row["exit_verdict"] == "TOP-EXIT"


def test_summary_counts_cycles_not_raw_events():
    rows = [
        {"cycle_type": "CLOSED_TRADE", "roi_pct": 10.0, "sell_date": "x", "post_7d_pct": -5.0, "exit_verdict": "GUTES TIMING"},
        {"cycle_type": "CLOSED_TRADE", "roi_pct": -2.0, "sell_date": "x", "post_7d_pct": 8.0, "exit_verdict": "ZU FRÜH"},
        {"cycle_type": "OPEN_TRADE", "roi_pct": -4.0, "sell_date": None, "exit_verdict": "–"},
    ]
    summary = transfer_evaluation_summary(rows)
    assert summary["evaluated_trades"] == 2
    assert summary["open_trades"] == 1
    assert summary["avg_realized_roi_pct"] == 4.0
    assert summary["good_exits"] == 1
    assert summary["early_exits"] == 1


def test_start_squad_sale_uses_start_market_value_for_realized_trade_grade():
    transfers = [{
        "player_id": "p_start",
        "player_name": "Starter",
        "club": "X",
        "transfer_type": "SELL",
        "price": 8_500_000,
        "transferred_at": "2026-08-10T12:00:00+00:00",
    }]
    histories = {"p_start": [
        {"snapshot_date": "2026-08-01", "value": 7_100_000, "recorded_at": "2026-08-01T22:00:00+00:00"},
        {"snapshot_date": "2026-08-10", "value": 8_200_000, "recorded_at": "2026-08-10T22:00:00+00:00"},
    ]}
    acquisitions = {"p_start": {
        "origin": "STARTKADER",
        "entry_value": 7_000_000,
        "purchase_price": None,
    }}
    row = evaluate_trade_cycles(transfers, histories, {}, acquisitions)[0]
    assert row["cycle_type"] == "CLOSED_START_SQUAD_TRADE"
    assert row["buy_price"] == 7_000_000
    assert row["sell_price"] == 8_500_000
    assert row["result_pnl"] == 1_500_000
    assert round(row["roi_pct"], 1) == 21.4
    assert row["entry_source"] == "STARTKADER_MW"
    assert row["verdict"] in {"TOP-TRADE", "STARKER TRADE"}


def test_non_start_unpaired_sale_still_does_not_invent_purchase_price():
    transfers = [{
        "player_id": "p_unknown",
        "player_name": "Unknown",
        "transfer_type": "SELL",
        "price": 8_000_000,
        "transferred_at": "2026-08-10T12:00:00+00:00",
    }]
    acquisitions = {"p_unknown": {"origin": "UNKNOWN", "entry_value": 7_000_000}}
    row = evaluate_trade_cycles(transfers, {}, {}, acquisitions)[0]
    assert row["cycle_type"] == "UNPAIRED_SALE"
    assert row["buy_price"] is None
    assert row["roi_pct"] is None


def test_current_start_squad_starter_is_live_without_exit():
    acquisitions = {
        "p3": {
            "player_id": "p3",
            "name": "Starter",
            "club": "Testclub",
            "player_status": "KADER",
            "player_role": "STAMM",
            "origin": "STARTKADER",
            "entry_value": 5_000_000,
            "market_value": 5_600_000,
            "purchase_date": "2026-08-01T12:00:00+00:00",
        }
    }
    histories = {"p3": [
        {"snapshot_date": "2026-08-01", "value": 5_000_000, "recorded_at": "2026-08-01T22:00:00+00:00"},
        {"snapshot_date": "2026-08-10", "value": 5_600_000, "recorded_at": "2026-08-10T22:00:00+00:00"},
    ]}
    row = evaluate_trade_cycles([], histories, acquisition_by_player=acquisitions)[0]
    assert row["cycle_type"] == "OPEN_START_SQUAD"
    assert row["verdict"] == "LIVE · STAMM"
    assert row["exit_verdict"] == "–"
    assert row["sell_date"] is None
    assert row["result_pnl"] == 600_000
    assert round(row["roi_pct"], 1) == 12.0
