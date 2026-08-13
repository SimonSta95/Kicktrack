from datetime import date, timedelta

from app.mv_prediction import build_predictions


def _rows(player_id: str, values: list[int], start=date(2026, 8, 1)):
    return [
        {"player_id": player_id, "value": value, "snapshot_date": (start + timedelta(days=i)).isoformat()}
        for i, value in enumerate(values)
    ]


def test_prediction_follows_latest_daily_change_and_returns_interval():
    rows = []
    # Enough comparable historical examples for calibration.
    for idx in range(20):
        base = 5_000_000 + idx * 10_000
        rows += _rows(f"hist-{idx}", [base, base + 100_000, base + 205_000, base + 315_000])
    rows += _rows("target", [4_800_000, 4_900_000, 5_020_000])

    pred = build_predictions(rows)["target"]
    assert pred["delta"] is not None
    assert pred["delta"] > 0
    assert pred["expected_value"] > 5_020_000
    assert pred["low_delta"] < pred["delta"] < pred["high_delta"]
    assert pred["sample_count"] >= 20


def test_prediction_is_uncertain_with_only_one_observation():
    pred = build_predictions(_rows("p", [5_000_000]))["p"]
    assert pred["delta"] is None
    assert pred["confidence"] == "UNSICHER"


def test_live_current_value_is_used_for_expected_value():
    rows = _rows("p", [5_000_000, 5_100_000, 5_200_000])
    pred = build_predictions(rows, current_values={"p": 5_250_000})["p"]
    assert pred["expected_value"] == 5_250_000 + pred["delta"]


def test_live_24h_delta_overrides_stale_same_value_daily_snapshot():
    # Before the 22:00 refresh, today's stored value can still equal yesterday's.
    # The Kickbase live 24h delta must drive the forecast instead of producing 0.
    rows = []
    for idx in range(20):
        base = 5_000_000 + idx * 20_000
        rows += _rows(f"hist-live-{idx}", [base, base + 180_000, base + 370_000, base + 565_000])
    rows += _rows("target-live", [5_500_000, 5_700_000, 5_700_000])

    pred = build_predictions(
        rows,
        current_values={"target-live": 5_700_000},
        current_deltas={"target-live": 200_000},
    )["target-live"]

    assert pred["delta"] > 0
    assert pred["delta"] != 0
    assert pred["expected_value"] > 5_700_000
