from datetime import datetime
from zoneinfo import ZoneInfo

from app.season import SEASON_MODE_START, season_mode, season_mode_active

BERLIN = ZoneInfo("Europe/Berlin")


def test_auto_stays_preseason_before_switch():
    assert season_mode(datetime(2026, 8, 21, 21, 59, 59, tzinfo=BERLIN), "AUTO") == "PRESEASON"


def test_auto_switches_exactly_at_22_clock():
    assert SEASON_MODE_START == datetime(2026, 8, 21, 22, 0, tzinfo=BERLIN)
    assert season_mode(SEASON_MODE_START, "AUTO") == "SEASON"
    assert season_mode_active(SEASON_MODE_START, "AUTO") is True


def test_manual_overrides_are_deterministic():
    before = datetime(2026, 8, 20, 12, 0, tzinfo=BERLIN)
    after = datetime(2026, 8, 22, 12, 0, tzinfo=BERLIN)
    assert season_mode(before, "SEASON") == "SEASON"
    assert season_mode(after, "PRESEASON") == "PRESEASON"
