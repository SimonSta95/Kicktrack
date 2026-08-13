from app.bid_analysis import rate_bid


def test_good_bid_near_market_value_with_good_player_scores():
    result = rate_bid(
        bid=6_950_000,
        market_value=6_865_611,
        investment_score=80,
        squad_fit_score=72,
        balance=34_863_027,
    )
    assert result["bid_signal"] in {"GUTES GEBOT", "FAIR", "SCHNÄPPCHEN"}
    assert result["bid_delta_pct"] > 0
    assert "GEBOTSBEWERTUNG" in result["bid_analysis_text"]


def test_large_overpay_is_flagged():
    result = rate_bid(
        bid=12_000_000,
        market_value=10_000_000,
        investment_score=45,
        squad_fit_score=40,
        balance=20_000_000,
    )
    assert result["bid_signal"] in {"ZU TEUER", "NICHT SINNVOLL"}


def test_bid_below_market_value_is_flagged_as_below_minimum():
    result = rate_bid(
        bid=8_500_000,
        market_value=10_000_000,
        investment_score=90,
        squad_fit_score=85,
        balance=40_000_000,
    )
    assert result["bid_signal"] == "UNTER MINDESTGEBOT"
    assert result["bid_score"] <= 20
    assert "Mindestgebot" in result["bid_analysis_text"]
