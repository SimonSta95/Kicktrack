from app.bidding import calculate_bid_capacity


def test_positive_balance_adds_full_cash_to_33_percent_credit():
    cap = calculate_bid_capacity(100_000_000, 10_000_000)
    assert cap.adjusted_squad_value == 100_000_000
    assert cap.minimum_balance == -33_000_000
    assert cap.maximum_new_bid == 43_000_000


def test_negative_balance_reduces_basis_like_kickbase_example():
    cap = calculate_bid_capacity(100_000_000, -10_000_000)
    assert cap.adjusted_squad_value == 90_000_000
    assert cap.minimum_balance == -29_700_000
    assert cap.maximum_new_bid == 19_700_000


def test_existing_bid_is_released_when_replacing_offer():
    cap = calculate_bid_capacity(100_000_000, -20_000_000, existing_bid=10_000_000)
    assert cap.effective_balance == -10_000_000
    assert cap.maximum_new_bid == 19_700_000
