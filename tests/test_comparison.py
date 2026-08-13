from app.services.comparison import summarize_squad


def test_summarize_squad_groups_positions_and_totals():
    players = [
        {"name": "Keeper", "position": "TW", "market_value": 5_000_000, "average_points": 80, "points_total": 800},
        {"name": "Defender", "position": "ABW", "market_value": 8_000_000, "average_points": 70, "points_total": 700},
        {"name": "Mid", "position": "MF", "market_value": 10_000_000, "average_points": 100, "points_total": 1000},
        {"name": "Striker", "position": "ST", "market_value": 12_000_000, "average_points": 90, "points_total": 900},
    ]

    summary = summarize_squad(players)

    assert summary.player_count == 4
    assert summary.market_value == 35_000_000
    assert summary.average_points == 85
    assert summary.total_points == 3400
    assert summary.positions["MF"].player_count == 1
    assert summary.positions["MF"].average_points == 100
    assert summary.top_by_average_points[0]["name"] == "Mid"
    assert summary.top_by_market_value[0]["name"] == "Striker"


def test_summarize_squad_handles_missing_points():
    summary = summarize_squad([
        {"name": "A", "position": "MF", "market_value": 1_000_000, "average_points": None, "points_total": None}
    ])

    assert summary.average_points is None
    assert summary.total_points is None
    assert summary.positions["MF"].average_points is None
