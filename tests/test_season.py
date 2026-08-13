from datetime import date

from app.season import current_season_start, filter_current_season_transfers, season_label


def test_season_boundary_switches_on_july_first():
    assert current_season_start(date(2026, 6, 30)) == date(2025, 7, 1)
    assert current_season_start(date(2026, 7, 1)) == date(2026, 7, 1)
    assert current_season_start(date(2026, 8, 12)) == date(2026, 7, 1)
    assert season_label(date(2026, 8, 12)) == "2026/27"


def test_transfer_filter_removes_previous_season_events():
    events = [
        {"player_id": "old", "transferred_at": "2026-05-20T10:00:00Z"},
        {"player_id": "preseason", "transferred_at": "2026-07-10T10:00:00Z"},
        {"player_id": "current", "transferred_at": "2026-08-10T10:00:00Z"},
    ]
    filtered = filter_current_season_transfers(events, date(2026, 8, 12))
    assert [event["player_id"] for event in filtered] == ["preseason", "current"]
