from datetime import date, timedelta

from app.market_value_insights import analyze_market_value_trend, predict_trend_reversal, facts_first_market_signal


def _history(values, start=date(2026, 8, 1)):
    return [
        {"snapshot_date": (start + timedelta(days=i)).isoformat(), "value": value}
        for i, value in enumerate(values)
    ]


def test_trend_detects_slowing_positive_steps():
    values = [10_000_000]
    for delta in [200_000, 180_000, 150_000, 110_000, 70_000, 40_000]:
        values.append(values[-1] + delta)
    result = analyze_market_value_trend(_history(values), market_value=values[-1])
    assert result["code"] == "SLOWING_UP"
    assert result["label"] == "VERLANGSAMEND"
    assert result["recent_velocity"] < result["older_velocity"]


def test_trend_detects_accelerating_positive_steps():
    values = [5_000_000]
    for delta in [30_000, 45_000, 60_000, 90_000, 130_000, 180_000]:
        values.append(values[-1] + delta)
    result = analyze_market_value_trend(_history(values), market_value=values[-1])
    assert result["code"] == "ACCELERATING_UP"


def test_facts_first_signal_uses_trend_and_price_not_magic_score():
    row = {
        "market_value": 10_000_000,
        "price": 10_100_000,
        "mv_trend": {"code": "STABLE_UP", "streak": 4, "steps_text": "+90k · +95k · +100k · +105k"},
        "trend_reversal_prediction": {"risk": "NIEDRIG", "probability": 0.18, "sample_count": 80},
    }
    signal, reasons = facts_first_market_signal(row)
    assert signal == "INTERESSANT"
    assert any("+1.0%" in reason for reason in reasons)
    assert not any("/100" in reason for reason in reasons)


def test_reversal_prediction_degrades_when_history_is_too_small():
    player = _history([1_000_000, 1_100_000, 1_180_000, 1_220_000, 1_230_000])
    rows = [{"player_id": "p1", **row} for row in player]
    result = predict_trend_reversal(rows, player, market_value=1_230_000)
    assert result["risk"] == "UNSICHER"
    assert result["probability"] is None


def test_trend_display_uses_ci_symbols():
    from app.market_value_insights import trend_display

    expected = {
        "ACCELERATING_UP": "⇈ BESCHLEUNIGEND",
        "STABLE_UP": "↑ STABIL STEIGEND",
        "SLOWING_UP": "↗ VERLANGSAMEND",
        "TURNING_UP": "↗ WENDE AUFWÄRTS",
        "TURNING_DOWN": "↘ WENDE ABWÄRTS",
        "SIDEWAYS": "→ SEITWÄRTS",
        "RECOVERING": "↘ ERHOLUNG",
        "STABLE_DOWN": "↓ STABIL FALLEND",
        "ACCELERATING_DOWN": "⇊ BESCHLEUNIGT FALLEND",
    }
    for code, label in expected.items():
        assert trend_display({"code": code, "label": label.split(" ", 1)[1]}) == label


def test_trend_tone_is_semantic():
    from app.market_value_insights import trend_tone

    assert trend_tone("ACCELERATING_UP") == "positive"
    assert trend_tone("SLOWING_UP") == "warning"
    assert trend_tone("TURNING_UP") == "positive"
    assert trend_tone("TURNING_DOWN") == "negative"
    assert trend_tone("ACCELERATING_DOWN") == "negative"
    assert trend_tone("SIDEWAYS") == "muted"


def test_trend_distinguishes_upward_and_downward_turns():
    rising_after_fall = [10_000_000, 9_800_000, 9_600_000, 9_450_000, 9_520_000, 9_640_000, 9_800_000]
    up = analyze_market_value_trend(_history(rising_after_fall), market_value=rising_after_fall[-1])
    assert up["code"] == "TURNING_UP"
    assert up["direction"] == "UP"

    falling_after_rise = [10_000_000, 10_200_000, 10_400_000, 10_550_000, 10_480_000, 10_360_000, 10_200_000]
    down = analyze_market_value_trend(_history(falling_after_rise), market_value=falling_after_rise[-1])
    assert down["code"] == "TURNING_DOWN"
    assert down["direction"] == "DOWN"
