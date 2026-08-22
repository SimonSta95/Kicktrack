from datetime import date, timedelta

from app.market_value_history import MarketValueHistoryService
from app.storage import Storage


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def market_value_history(self, league_id, player_id, timeframe=365):
        self.calls += 1
        return self.payload


def _payload(days=20):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return {
        "it": [
            {"d": (start + timedelta(days=i)).isoformat(), "mv": 1_000_000 + i * 10_000}
            for i in range(days)
        ]
    }


def test_history_service_fetches_persists_and_reuses_fresh_history(tmp_path):
    storage = Storage(tmp_path / "history.db")
    client = FakeClient(_payload())
    service = MarketValueHistoryService(client, storage, "l1")

    first = service.ensure_many(["p1"])
    assert client.calls == 1
    assert first["useful_players"] == 1
    assert first["fresh_players"] == 1
    assert len(storage.all_history("p1")) >= 14

    second = service.ensure_many(["p1"])
    assert client.calls == 1
    assert second["fresh_players"] == 1
    storage.close()
