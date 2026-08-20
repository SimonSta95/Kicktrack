from app.selling import listing_price_for_percent


def test_sell_price_mw_is_exact():
    assert listing_price_for_percent(26_913_785, 100) == 26_913_785


def test_sell_price_percent_buttons_do_not_round_to_thousands():
    assert listing_price_for_percent(26_913_785, 102) == 27_452_060
    assert listing_price_for_percent(26_913_785, 105) == 28_259_474
    assert listing_price_for_percent(26_913_785, 110) == 29_605_163
