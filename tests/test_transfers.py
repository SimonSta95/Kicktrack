from app.services.transfers import analyze_manager_transfers


def test_transfer_behavior_pairs_buy_and_sell_without_inventing_start_squad_cost():
    events = [
        {"player_id": "p1", "player_name": "A", "transfer_type": "BUY", "price": 10_000_000, "transferred_at": "2026-08-01T12:00:00+00:00"},
        {"player_id": "p2", "player_name": "Startspieler", "transfer_type": "SELL", "price": 8_000_000, "transferred_at": "2026-08-02T12:00:00+00:00"},
        {"player_id": "p1", "player_name": "A", "transfer_type": "SELL", "price": 12_500_000, "transferred_at": "2026-08-05T12:00:00+00:00"},
    ]
    result = analyze_manager_transfers(events)
    assert result.buy_count == 1
    assert result.sell_count == 2
    assert result.completed_trade_count == 1
    assert result.realized_pnl == 2_500_000
    assert result.average_holding_days == 4
    assert result.best_trade.player_name == "A"
