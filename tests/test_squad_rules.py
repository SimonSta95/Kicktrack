from app.squad_rules import MAX_SQUAD_SIZE, active_bid_count, required_sales, squad_capacity


def test_capacity_labels_and_free_slots():
    cap = squad_capacity([{"player_id": str(i)} for i in range(18)])
    assert cap.is_full
    assert cap.free == 0
    assert cap.maximum == MAX_SQUAD_SIZE
    assert "KADER VOLL" in cap.label


def test_required_sales_accounts_for_roster_limit():
    assert required_sales(16, 2) == 0
    assert required_sales(17, 2) == 1
    assert required_sales(18, 1) == 1
    assert required_sales(18, 4) == 4


def test_active_bid_count_deduplicates_players():
    rows = [
        {"player_id": "1", "own_bid": 100},
        {"player_id": "1", "own_bid": 100},
        {"player_id": "2", "own_bid": 200},
        {"player_id": "3", "own_bid": 0},
    ]
    assert active_bid_count(rows) == 2
