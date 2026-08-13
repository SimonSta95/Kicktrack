from types import SimpleNamespace

from app.storage import Storage


def test_apply_sync_result_is_atomic_snapshot(tmp_path):
    storage = Storage(tmp_path / "kicktrack.db")
    result = SimpleNamespace(
        league_id="league-1",
        manager_id="manager-1",
        players=[
            {
                "player_id": "51",
                "name": "Khedira",
                "club": "Union",
                "team_id": "40",
                "position": "MF",
                "daily_change": 10_000,
                "market_gain_loss": 250_000,
                "api_long_change": 100_000,
                "team_image": None,
                "status": 0,
                "market_value": 4_800_000,
            }
        ],
        acquisitions={
            "51": {
                "origin": "TRANSFER",
                "entry_value": 4_550_000,
                "purchase_price": 4_550_000,
                "purchase_date": "2026-08-01T12:00:00Z",
            }
        },
        transfers=[],
        dashboard={"profit": 300_000, "team_value": 4_800_000},
        league_info={"budget": 2_000_000},
    )

    storage.apply_sync_result(result)

    player = storage.get_player("51")
    assert player is not None
    assert player["market_value"] == 4_800_000
    assert player["entry_value"] == 4_550_000
    assert storage.get_setting("manager_id") == "manager-1"
    assert storage.dashboard_metrics("league-1")["total_assets"] == 6_800_000
    storage.close()


def test_player_points_are_persisted(tmp_path):
    from types import SimpleNamespace

    storage = Storage(tmp_path / "points.db")
    result = SimpleNamespace(
        players=[{
            "player_id": "51", "name": "Khedira", "club": "Union", "team_id": "40",
            "position": "MF", "market_value": 4_837_359, "daily_change": 120_000,
            "market_gain_loss": 389_428, "api_long_change": 200_000,
            "team_image": None, "status": 0, "points_total": 1956, "average_points": 61,
        }],
        acquisitions={"51": {"origin": "STARTKADER", "entry_value": 4_447_931,
                              "purchase_price": None, "purchase_date": None}},
        transfers=[], league_id="5012647", manager_id="manager", dashboard={}, league_info={},
    )

    storage.apply_sync_result(result)
    player = storage.get_player("51")

    assert player["points_total"] == 1956
    assert player["average_points"] == 61


def test_league_analysis_cache(tmp_path):
    from app.services.league import LeagueManager, LeagueOverviewResult, ManagerSquadResult

    storage = Storage(tmp_path / "league.db")
    overview = LeagueOverviewResult(
        league_id="l1",
        matchday=3,
        managers=[
            LeagueManager(manager_id="m1", name="Alice", place=1, points=1000, team_value=120_000_000),
            LeagueManager(manager_id="m2", name="Bob", place=2, points=900, team_value=110_000_000),
        ],
    )
    storage.replace_league_managers(overview)
    assert [row["manager_id"] for row in storage.league_managers("l1")] == ["m1", "m2"]
    assert storage.get_league_int_setting("l1", "matchday") == 3

    squad = ManagerSquadResult(
        league_id="l1",
        manager_id="m1",
        players=[
            {
                "player_id": "p1",
                "name": "Spieler",
                "club": "Bayern",
                "team_id": "2",
                "position": "MF",
                "market_value": 20_000_000,
                "points_total": 100,
                "average_points": 50,
                "team_image": None,
            }
        ],
    )
    storage.replace_manager_squad(squad)
    assert storage.manager_squad("l1", "m1")[0]["name"] == "Spieler"
    assert storage.player_owner("l1", "p1")["manager_name"] == "Alice"
    storage.close()


def test_storage_cache_is_safe_across_threads(tmp_path):
    """A Storage instance can be reused by a Qt-style background worker."""
    import threading

    storage = Storage(tmp_path / "threaded.db")
    storage.cache_set("main-thread", {"ok": True})

    errors = []
    values = []

    def worker():
        try:
            values.append(storage.cache_get("main-thread", 60))
            storage.cache_set("worker-thread", {"value": 42})
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            storage.close()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert values == [{"ok": True}]
    assert storage.cache_get("worker-thread", 60) == {"value": 42}
    storage.close()


def test_league_ownership_index_distinguishes_owner_and_free(tmp_path):
    from app.services.league import (
        LeagueManager,
        LeagueOverviewResult,
        LeagueOwnershipResult,
        ManagerSquadResult,
    )

    storage = Storage(tmp_path / "ownership.db")
    storage.replace_league_managers(
        LeagueOverviewResult(
            league_id="l1",
            managers=[
                LeagueManager(manager_id="m1", name="Alice", place=1),
                LeagueManager(manager_id="m2", name="Bob", place=2),
            ],
        )
    )
    result = LeagueOwnershipResult(
        league_id="l1",
        squads=[
            ManagerSquadResult(
                league_id="l1",
                manager_id="m1",
                players=[{
                    "player_id": "p1", "name": "Owned", "club": "Bayern",
                    "team_id": "2", "position": "MF", "market_value": 10_000_000,
                    "points_total": 0, "average_points": 0, "team_image": None,
                }],
            ),
            ManagerSquadResult(
                league_id="l1",
                manager_id="m2",
                players=[{
                    "player_id": "p2", "name": "Other", "club": "Mainz",
                    "team_id": "18", "position": "ST", "market_value": 8_000_000,
                    "points_total": 0, "average_points": 0, "team_image": None,
                }],
            ),
        ],
    )
    storage.replace_league_ownership(result)

    assert storage.player_owner("l1", "p1")["manager_name"] == "Alice"
    assert storage.player_owner("l1", "free-player") is None
    assert storage.league_ownership_is_fresh("l1", 15 * 60)
    assert storage.ownership_coverage("l1") == (2, 2)


def test_league_manager_transfer_history_is_upserted(tmp_path):
    storage = Storage(tmp_path / "manager-transfers.db")
    events = [
        {
            "player_id": "p1",
            "player_name": "Spieler",
            "team_id": "2",
            "club": "Bayern",
            "transfer_type": "BUY",
            "price": 10_000_000,
            "transferred_at": "2026-08-01T12:00:00+00:00",
            "team_image": None,
        }
    ]
    storage.upsert_league_manager_transfers("l1", "m1", events)
    storage.upsert_league_manager_transfers("l1", "m1", events)
    rows = storage.league_manager_transfer_rows("l1", "m1")
    assert len(rows) == 1
    assert rows[0]["price"] == 10_000_000
    storage.close()


def test_league_manager_transfer_rows_can_filter_previous_season(tmp_path):
    storage = Storage(tmp_path / "season_transfers.db")
    storage.upsert_league_manager_transfers(
        "league",
        "manager",
        [
            {
                "player_id": "old", "player_name": "Alt", "transfer_type": "BUY",
                "price": 1_000_000, "transferred_at": "2026-05-20T10:00:00Z",
            },
            {
                "player_id": "new", "player_name": "Neu", "transfer_type": "BUY",
                "price": 2_000_000, "transferred_at": "2026-08-10T10:00:00Z",
            },
        ],
    )
    rows = storage.league_manager_transfer_rows("league", "manager", since="2026-07-01")
    assert [row["player_id"] for row in rows] == ["new"]


def test_team_value_history_returns_chronological_snapshots(tmp_path):
    storage = Storage(tmp_path / "dashboard-history.db")
    storage.conn.executemany(
        """
        INSERT INTO dashboard_snapshots(
            league_id, snapshot_date, team_value, budget, total_assets, recorded_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        [
            ("l1", "2026-08-10", 100_000_000, 5_000_000, 105_000_000, "2026-08-10T08:00:00+00:00"),
            ("l1", "2026-08-11", 102_000_000, 4_000_000, 106_000_000, "2026-08-11T08:00:00+00:00"),
        ],
    )
    storage.conn.commit()

    rows = storage.team_value_history("l1", 90)

    assert [row["snapshot_date"] for row in rows] == ["2026-08-10", "2026-08-11"]
    assert [row["team_value"] for row in rows] == [100_000_000, 102_000_000]
    storage.close()


def test_storage_repairs_current_club_names_from_team_ids_on_startup(tmp_path):
    db_path = tmp_path / "club-repair.db"
    storage = Storage(db_path)
    storage.conn.execute(
        "INSERT INTO players(player_id, name, club, team_id) VALUES (?, ?, ?, ?)",
        ("enzo", "Enzo Leopold", "Team 15", "15"),
    )
    storage.conn.execute(
        """
        INSERT INTO league_manager_players(
            league_id, manager_id, player_id, name, club, team_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("l1", "m1", "adam", "Raif Adam", "Gladbach", "77", "2026-08-12T10:00:00+00:00"),
    )
    storage.conn.commit()
    storage.close()

    repaired = Storage(db_path)
    enzo = repaired.conn.execute("SELECT club, team_id FROM players WHERE player_id='enzo'").fetchone()
    adam = repaired.conn.execute(
        "SELECT club, team_id FROM league_manager_players WHERE player_id='adam'"
    ).fetchone()
    assert enzo["club"] == "Gladbach"
    assert enzo["team_id"] == "15"
    assert adam["club"] == "Elversberg"
    assert adam["team_id"] == "77"



def test_league_player_returns_foreign_player_stats(tmp_path):
    from app.services.league import LeagueOwnershipResult, ManagerSquadResult

    storage = Storage(tmp_path / "foreign-player.db")
    storage.replace_league_ownership(
        LeagueOwnershipResult(
            league_id="l1",
            squads=[
                ManagerSquadResult(
                    league_id="l1",
                    manager_id="m2",
                    players=[{
                        "player_id": "p9",
                        "name": "Foreign",
                        "club": "Bayern",
                        "team_id": "2",
                        "position": "MF",
                        "market_value": 12_000_000,
                        "points_total": 321,
                        "average_points": 64,
                        "team_image": None,
                    }],
                )
            ],
        )
    )

    player = storage.league_player("l1", "p9")
    assert player is not None
    assert player["market_value"] == 12_000_000
    assert player["points_total"] == 321
    assert player["average_points"] == 64
    storage.close()
