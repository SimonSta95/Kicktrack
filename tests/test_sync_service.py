from app.services.sync import KickbaseSyncService


class FakeClient:
    def squad(self, league_id):
        return [{"player_id": "1", "market_value": 2_000_000, "market_gain_loss": 200_000}]

    def detect_manager_id(self, league_id, players):
        return "m1"

    def manager_transfers(self, league_id, manager_id):
        return {"it": []}

    def parse_manager_transfers(self, data):
        return []

    def acquisition_for_current_player(self, player, transfers):
        return {"origin": "STARTKADER", "entry_value": 1_800_000, "purchase_price": None, "purchase_date": None}

    def manager_dashboard(self, league_id, manager_id):
        return {"profit": 200_000, "team_value": 2_000_000}

    def league_info(self, league_id):
        return {"budget": 1_000_000}


def test_fetch_builds_coherent_sync_result():
    result = KickbaseSyncService(FakeClient()).fetch("league-1")

    assert result.manager_id == "m1"
    assert result.dashboard_loaded is True
    assert result.acquisitions["1"]["entry_value"] == 1_800_000
    assert result.league_info["budget"] == 1_000_000
