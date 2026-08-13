from datetime import UTC, datetime, timedelta

from app.storage import Storage


def test_market_decision_log_and_backtest(tmp_path):
    storage = Storage(tmp_path / "test.db")
    decision_day = (datetime.now(UTC).date() - timedelta(days=8)).isoformat()
    # seed an older decision directly so the 7-day horizon is evaluable today
    storage.conn.execute(
        """INSERT INTO analytics_decisions(league_id,player_id,decision_date,signal,market_value,market_price,max_bid,investment_score,squad_fit_score,confidence_score,investment_horizon,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("L","P",decision_day,"KAUFEN",10_000_000,9_500_000,10_500_000,80,75,70,"HOLD",datetime.now(UTC).isoformat()),
    )
    storage.conn.execute(
        "INSERT INTO market_values(player_id,value,snapshot_date,recorded_at) VALUES(?,?,?,?)",
        ("P",11_000_000,datetime.now(UTC).date().isoformat(),datetime.now(UTC).isoformat()),
    )
    storage.conn.commit()
    summary = storage.decision_backtest_summary("L")
    assert summary["evaluated"] == 1
    assert summary["correct"] == 1
    assert summary["hit_rate"] == 100.0
    assert summary["buy_avg_return_7d"] == 10.0
    assert summary["buy_count"] == 1
