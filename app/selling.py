from __future__ import annotations


def listing_price_for_percent(market_value: int, percent_value: int = 100) -> int:
    """Return a listing target in whole euros without thousand-rounding.

    100 percent is always the exact market value. Percentage presets are
    calculated from the exact market value and truncated only to a whole euro,
    because the Kickbase write endpoint accepts integer euro amounts.
    """
    market_value = int(market_value or 0)
    percent_value = int(percent_value or 0)
    if market_value <= 0 or percent_value <= 0:
        return 0
    if percent_value == 100:
        return market_value
    return (market_value * percent_value) // 100
