from app.storage import Storage


def _insert_live(storage, player_id: str, value: int, snapshot_date: str, recorded_at: str):
    storage.conn.execute(
        """
        INSERT INTO market_values(player_id, value, snapshot_date, recorded_at, source)
        VALUES(?, ?, ?, ?, 'live')
        ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
            value=excluded.value, recorded_at=excluded.recorded_at, source='live'
        """,
        (player_id, value, snapshot_date, recorded_at),
    )
    storage.conn.commit()


def test_prediction_tracking_evaluates_actual_refresh(tmp_path):
    storage = Storage(tmp_path / "predictions.db")
    pred = {
        "p1": {
            "delta": 200_000,
            "expected_value": 5_200_000,
            "low_delta": 100_000,
            "high_delta": 300_000,
            "confidence": "HOCH",
            "sample_count": 80,
            "history_days": 20,
            "method": "test",
        }
    }
    written = storage.record_mv_predictions(
        "l1", pred, current_values={"p1": 5_000_000},
        current_deltas={"p1": 180_000}, target_date="2026-08-15",
    )
    assert written == 1

    # 22:05 Europe/Berlin = 20:05 UTC in August: definitely after refresh.
    _insert_live(storage, "p1", 5_150_000, "2026-08-15", "2026-08-15T20:05:00+00:00")
    evaluated = storage.evaluate_mv_predictions("l1", through_date="2026-08-15")
    assert evaluated == 1

    row = storage.mv_prediction_rows("l1", limit=1)[0]
    assert row["actual_delta"] == 150_000
    assert row["absolute_error"] == 50_000
    assert row["signed_error"] == 50_000
    assert row["direction_hit"] == 1
    assert row["actual_snapshot_date"] == "2026-08-15"


def test_prediction_evaluation_ignores_pre_refresh_snapshot_and_uses_next_morning(tmp_path):
    storage = Storage(tmp_path / "post_refresh.db")
    storage.record_mv_predictions(
        "l1",
        {"p1": {"delta": 150_000, "expected_value": 5_150_000, "confidence": "MITTEL"}},
        current_values={"p1": 5_000_000}, target_date="2026-08-15",
    )

    # This is the exact bug from the old evaluator: a same-day observation made
    # before 22:00 must NOT count as the outcome of the 22:00 refresh.
    _insert_live(storage, "p1", 5_000_000, "2026-08-15", "2026-08-15T16:00:00+00:00")
    assert storage.evaluate_mv_predictions("l1", through_date="2026-08-15") == 0
    assert storage.mv_prediction_rows("l1", limit=1)[0]["evaluated_at"] is None

    # If the app is next opened the following morning, that observation is still
    # the result of the previous night's refresh and must be matched to 15 Aug.
    _insert_live(storage, "p1", 5_120_000, "2026-08-16", "2026-08-16T06:30:00+00:00")
    assert storage.evaluate_mv_predictions("l1", through_date="2026-08-15") == 1
    row = storage.mv_prediction_rows("l1", limit=1)[0]
    assert row["actual_delta"] == 120_000
    assert row["direction_hit"] == 1
    assert row["actual_snapshot_date"] == "2026-08-16"


def test_prediction_evaluation_repairs_legacy_wrong_same_day_match(tmp_path):
    storage = Storage(tmp_path / "repair.db")
    storage.record_mv_predictions(
        "l1",
        {"p1": {"delta": 100_000, "expected_value": 5_100_000, "confidence": "MITTEL"}},
        current_values={"p1": 5_000_000}, target_date="2026-08-15",
    )
    # Simulate a bad evaluation written by <= V5.3.1.
    storage.conn.execute(
        """UPDATE mv_predictions SET actual_value=5000000, actual_delta=0,
        absolute_error=100000, signed_error=100000, direction_hit=0,
        evaluated_at='2026-08-16T06:00:00+00:00' WHERE league_id='l1' AND player_id='p1'"""
    )
    storage.conn.commit()
    _insert_live(storage, "p1", 5_080_000, "2026-08-16", "2026-08-16T06:30:00+00:00")
    assert storage.evaluate_mv_predictions("l1", through_date="2026-08-15") == 1
    row = storage.mv_prediction_rows("l1", limit=1)[0]
    assert row["actual_delta"] == 80_000
    assert row["direction_hit"] == 1


def test_prediction_summary_reports_mae_and_direction(tmp_path):
    storage = Storage(tmp_path / "summary.db")
    storage.record_mv_predictions(
        "l1",
        {
            "p1": {"delta": 100_000, "expected_value": 5_100_000, "confidence": "HOCH"},
            "p2": {"delta": -100_000, "expected_value": 4_900_000, "confidence": "MITTEL"},
        },
        current_values={"p1": 5_000_000, "p2": 5_000_000},
        current_deltas={"p1": 90_000, "p2": -90_000}, target_date="2026-08-15",
    )
    _insert_live(storage, "p1", 5_080_000, "2026-08-15", "2026-08-15T20:05:00+00:00")
    _insert_live(storage, "p2", 5_050_000, "2026-08-15", "2026-08-15T20:05:00+00:00")
    assert storage.evaluate_mv_predictions("l1", through_date="2026-08-15") == 2

    summary = storage.mv_prediction_summary("l1", limit_days=1000)
    assert summary["evaluated"] == 2
    assert summary["direction_hit_rate"] == 50.0
    assert summary["mae"] == 85_000.0
    assert summary["within_100k_rate"] == 50.0


def test_prediction_tracking_stores_prediction_source(tmp_path):
    storage = Storage(tmp_path / "sources.db")
    storage.record_mv_predictions(
        "l1",
        {"p1": {"delta": 100_000, "expected_value": 5_100_000, "confidence": "HOCH"}},
        current_values={"p1": 5_000_000},
        target_date="2026-08-15",
        sources={"p1": "MANAGER_SQUAD"},
    )
    row = storage.mv_prediction_rows("l1", limit=1)[0]
    assert row["prediction_source"] == "MANAGER_SQUAD"


def test_prediction_tracking_uses_model_baseline_delta_when_live_delta_missing(tmp_path):
    storage = Storage(tmp_path / "baseline_from_model.db")
    storage.record_mv_predictions(
        "l1",
        {
            "p1": {
                "delta": 180_000,
                "expected_value": 5_180_000,
                "baseline_delta": 170_000,
                "confidence": "MITTEL",
            }
        },
        current_values={"p1": 5_000_000},
        target_date="2026-08-18",
    )
    row = storage.mv_prediction_rows("l1", limit=1)[0]
    assert row["baseline_delta"] == 170_000


def test_prediction_summary_ignores_legacy_forecasts_without_auditable_baseline(tmp_path):
    storage = Storage(tmp_path / "legacy_quality.db")
    storage.record_mv_predictions(
        "l1",
        {
            "legacy": {"delta": 0, "expected_value": 5_000_000, "confidence": "UNSICHER"},
            "valid": {"delta": 100_000, "expected_value": 5_100_000, "confidence": "MITTEL"},
        },
        current_values={"legacy": 5_000_000, "valid": 5_000_000},
        current_deltas={"valid": 90_000},
        target_date="2026-08-15",
    )
    _insert_live(storage, "legacy", 5_200_000, "2026-08-15", "2026-08-15T20:05:00+00:00")
    _insert_live(storage, "valid", 5_080_000, "2026-08-15", "2026-08-15T20:05:00+00:00")
    storage.evaluate_mv_predictions("l1", through_date="2026-08-15")

    summary = storage.mv_prediction_summary("l1", limit_days=1000)
    assert summary["evaluated"] == 1
    assert summary["direction_hit_rate"] == 100.0
