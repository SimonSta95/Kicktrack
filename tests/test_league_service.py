from pathlib import Path

from app.services.league import LeagueAnalysisService
from app.storage import Storage


class FakeClient:
    def __init__(self):
        self.calls = {"managers": 0, "ranking": 0, "dashboard": 0, "competition": 0, "squad": 0, "transfers": 0}

    @staticmethod
    def _to_int(value):
        if value is None:
            return None
        return int(value)

    def league_managers(self, league_id):
        self.calls["managers"] += 1
        return {"managers": [{"manager_id": "1", "name": "Simon", "is_user": True}, {"manager_id": "2", "name": "Old"}], "matchday": 0}

    def league_ranking(self, league_id):
        self.calls["ranking"] += 1
        return {"managers": [{"manager_id": "1", "name": "Simon", "points": 0, "place": 1, "team_value": 0}], "matchday": 0}

    def manager_dashboard(self, league_id, manager_id):
        self.calls["dashboard"] += 1
        if manager_id == "1":
            return {"manager_name": "Simon", "team_value": 144_000_000, "profit": 615_000, "average_points": 0, "matchday_wins": 0}
        return {"manager_name": "Old", "team_value": 100_000_000, "profit": -1_000_000, "points": 35_793, "average_points": 1052, "matchday_wins": 10, "place": 1}

    def competition_player_teams(self):
        self.calls["competition"] += 1
        return {"99": {"club": "Gladbach", "team_id": "77", "team_image": None}}

    def manager_squad(self, league_id, manager_id):
        self.calls["squad"] += 1
        return [{"player_id": "99", "name": "Bolin", "club": "Team 15", "team_id": "15", "position": "MF", "market_value": 1, "points_total": 0, "average_points": 0, "team_image": None}]

    def manager_transfers(self, league_id, manager_id):
        self.calls["transfers"] += 1
        return {"it": [{"pi": "99", "pn": "Bolin", "tid": 77, "tty": 1, "trp": 5_000_000, "dt": "2026-08-10T12:00:00Z"}]}

    def parse_manager_transfers(self, data):
        return [{
            "player_id": "99", "player_name": "Bolin", "team_id": "77",
            "club": "Gladbach", "transfer_type": "BUY", "price": 5_000_000,
            "transferred_at": "2026-08-10T12:00:00Z", "team_image": None,
        }]


def make_service(tmp_path: Path):
    storage = Storage(tmp_path / "test.db")
    client = FakeClient()
    return LeagueAnalysisService(client, storage), client, storage


def test_preseason_hides_stale_metrics_but_keeps_dashboard_team_value(tmp_path):
    service, client, storage = make_service(tmp_path)
    result = service.fetch_overview("league")
    assert result.season_started is False
    current = next(m for m in result.managers if m.manager_id == "1")
    assert current.points == 0
    assert current.place == 1
    assert current.average_points is None
    assert current.matchday_wins is None
    assert current.team_value == 144_000_000
    old = next(m for m in result.managers if m.manager_id == "2")
    assert old.points is None
    assert old.average_points is None
    assert old.matchday_wins is None
    assert old.place is None
    assert old.team_value == 100_000_000


def test_dashboard_cache_is_persistent_and_reused(tmp_path):
    service, client, storage = make_service(tmp_path)
    service.fetch_overview("league")
    first_dashboard_calls = client.calls["dashboard"]
    service.fetch_overview("league")
    assert client.calls["dashboard"] == first_dashboard_calls
    assert client.calls["managers"] == 1
    assert client.calls["ranking"] == 1


def test_force_refresh_bypasses_short_ttl_cache(tmp_path):
    service, client, storage = make_service(tmp_path)
    service.fetch_overview("league")
    service.fetch_overview("league", force=True)
    assert client.calls["managers"] == 2
    assert client.calls["ranking"] == 2
    assert client.calls["dashboard"] == 4


def test_competition_mapping_uses_sqlite_cache(tmp_path):
    service, client, storage = make_service(tmp_path)
    first = service.fetch_manager_squad("league", "1")
    second = service.fetch_manager_squad("league", "1", force=True)
    assert first.players[0]["club"] == "Gladbach"
    assert second.players[0]["club"] == "Gladbach"
    assert client.calls["competition"] == 1


def test_team_value_falls_back_to_cached_squad_sum_when_api_reports_zero(tmp_path):
    service, client, storage = make_service(tmp_path)

    def zero_dashboard(league_id, manager_id):
        client.calls["dashboard"] += 1
        return {"manager_name": manager_id, "team_value": 0, "profit": 0}

    def valued_squad(league_id, manager_id):
        client.calls["squad"] += 1
        return [
            {"player_id": "a", "name": "A", "market_value": 10_000_000},
            {"player_id": "b", "name": "B", "market_value": 7_500_000},
        ]

    client.manager_dashboard = zero_dashboard
    client.manager_squad = valued_squad

    first = service.fetch_overview("league")
    assert {m.team_value for m in first.managers} == {17_500_000}
    assert client.calls["squad"] == 2

    # A forced league refresh still reuses the persistent 15-minute squad cache.
    service.fetch_overview("league", force=True)
    assert client.calls["squad"] == 2


def test_fetch_ownership_reuses_sqlite_squad_cache(tmp_path):
    storage = Storage(tmp_path / "ownership-cache.db")
    client = FakeClient()
    service = LeagueAnalysisService(client, storage)

    first = service.fetch_ownership("league", ["1", "2"])
    second = service.fetch_ownership("league", ["1", "2"])

    assert not first.failed_manager_ids
    assert not second.failed_manager_ids
    assert len(first.squads) == 2
    # One API request per manager on the first pass; the second pass is SQLite-only.
    assert client.calls["squad"] == 2


def test_manager_detail_uses_persistent_transfer_cache(tmp_path):
    service, client, storage = make_service(tmp_path)
    first = service.fetch_manager_detail("league", "1")
    second = service.fetch_manager_detail("league", "1")
    assert len(first.transfers) == 1
    assert len(second.transfers) == 1
    assert client.calls["transfers"] == 1
    assert storage.league_manager_transfer_rows("league", "1")[0]["player_name"] == "Bolin"


def test_manager_detail_persists_only_current_season_transfers(tmp_path, monkeypatch):
    service, client, storage = make_service(tmp_path)

    client.manager_transfers = lambda league_id, manager_id: {
        "it": [
            {"pi": "old", "pn": "Alt", "tid": 3, "tty": 1, "trp": 1_000_000, "dt": "2026-05-20T10:00:00Z"},
            {"pi": "new", "pn": "Neu", "tid": 3, "tty": 1, "trp": 2_000_000, "dt": "2026-08-10T10:00:00Z"},
        ]
    }
    client.parse_manager_transfers = lambda data: [
        {
            "player_id": item["pi"], "player_name": item["pn"], "team_id": str(item["tid"]),
            "club": "Dortmund", "transfer_type": "BUY", "price": item["trp"],
            "transferred_at": item["dt"], "team_image": None,
        }
        for item in data["it"]
    ]

    # Freeze the season helper used by the service to the current 2026/27 window.
    monkeypatch.setattr(
        "app.services.league.filter_current_season_transfers",
        lambda events: [e for e in events if str(e.get("transferred_at", "")) >= "2026-07-01"],
    )

    result = service.fetch_manager_detail("league", "1")
    assert [event["player_id"] for event in result.transfers] == ["new"]
    rows = storage.league_manager_transfer_rows("league", "1")
    assert [row["player_id"] for row in rows] == ["new"]


def test_team_id_mapping_resolves_gladbach_and_elversberg(tmp_path):
    service, client, storage = make_service(tmp_path)
    players = [
        {"player_id": "enzo", "name": "Enzo Leopold", "club": "Gladbach", "team_id": "15"},
        {"player_id": "gya", "name": "Jan Gyamerah", "club": "Elversberg", "team_id": "77"},
    ]
    canonical = {
        "enzo": {"club": "Gladbach", "team_id": "15", "team_image": None},
        "gya": {"club": "Elversberg", "team_id": "77", "team_image": None},
    }

    enriched = service._enrich_players(players, canonical)
    assert enriched[0]["club"] == "Gladbach"
    assert enriched[0]["team_id"] == "15"
    assert enriched[1]["club"] == "Elversberg"
    assert enriched[1]["team_id"] == "77"



def test_enrich_players_recomputes_club_from_team_id_when_competition_has_no_name():
    players = [
        {"player_id": "3516", "name": "Leopold", "club": "Team 15", "team_id": "15"},
        {"player_id": "859", "name": "Gyamerah", "club": "Gladbach", "team_id": "77"},
        {"player_id": "12317", "name": "Adam", "club": "Gladbach", "team_id": "77"},
    ]
    canonical = {
        "3516": {"club": None, "team_id": "15", "team_image": None},
        "859": {"club": None, "team_id": "77", "team_image": None},
        "12317": {"club": None, "team_id": "77", "team_image": None},
    }

    enriched = LeagueAnalysisService._enrich_players(players, canonical)

    assert enriched[0]["club"] == "Gladbach"
    assert enriched[1]["club"] == "Elversberg"
    assert enriched[2]["club"] == "Elversberg"

