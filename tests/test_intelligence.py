from app.intelligence import player_form, parse_fixtures, fixture_run, trade_profile, squad_status, optimize_lineup, parse_activity_feed


def test_player_form_metrics():
    payload = {"it": [{"ph": [{"day": 1, "p": 50}, {"day": 2, "p": 70}, {"day": 3, "p": 90}]}]}
    result = player_form(payload)
    assert result["avg3"] == 70
    assert result["floor"] == 50
    assert result["ceiling"] == 90



def test_player_form_keeps_matchday_metadata_for_detail_chart():
    payload = {"it": [{"ph": [{
        "day": 4, "p": 123, "t1": "2", "t2": "43",
        "md": "2026-09-12T13:30:00Z", "cur": True, "st": 1,
    }]}]}
    result = player_form(payload)
    match = result["matches"][0]
    assert match["day"] == 4
    assert match["points"] == 123
    assert match["opponent_home"] == "2"
    assert match["opponent_away"] == "43"
    assert match["match_date"] == "2026-09-12T13:30:00Z"


def test_fixture_run_uses_opponent_table_place():
    fixtures = {"value": {"day": 1, "it": [{"day": 1, "it": [{"mi": "1", "t1": "8", "t2": "2", "t1sy": "S04", "t2sy": "FCB"}]}]}}
    table = {"value": {"it": [{"tid": "2", "tn": "Bayern", "cp": 1}, {"tid": "8", "tn": "Schalke", "cp": 18}]}}
    run = fixture_run("8", fixtures, table)
    assert run[0]["opponent"] == "Bayern"
    assert run[0]["ease"] == 0


def test_trade_profile_and_status():
    transfers = [{"transfer_type": "BUY", "price": 1_000_000}] * 6 + [{"transfer_type": "SELL", "price": 1_200_000}] * 6
    profile = trade_profile(transfers)
    assert profile["count"] == 12
    assert profile["label"] in {"AKTIV", "HOHE FLUKTUATION"}
    status = squad_status([{"name": "A", "kickbase_status": 0}, {"name": "B", "kickbase_status": 2}])
    assert status["available"] == 1
    assert status["questionable"] == 1
    assert status["unavailable"] == 0
    assert status["affected"][0]["status_detail"] == "ANGESCHLAGEN"


def test_lineup_optimizer_returns_eleven_when_possible():
    players = []
    positions = ["TW"] + ["ABW"] * 4 + ["MF"] * 5 + ["ST"] * 4
    for i, pos in enumerate(positions):
        players.append({"player_id": str(i), "name": f"P{i}", "position": pos, "market_value": 1_000_000 + i * 100_000, "average_points": 50 + i, "kickbase_status": 0})
    result = optimize_lineup(players)
    assert len(result["players"]) == 11


def test_activity_feed_parser():
    payload = {"af": [{"i": "a", "t": 1, "dt": "2026-08-12T12:00:00Z", "data": {"pi": "7", "pn": "Test", "byr": "Simon", "trp": 123}}]}
    rows = parse_activity_feed(payload)
    assert rows[0]["player_id"] == "7"
    assert rows[0]["price"] == 123


def test_lineup_optimizer_labels_actual_352_formation():
    players = []
    positions = ["TW"] + ["ABW"] * 3 + ["MF"] * 5 + ["ST"] * 2
    for i, pos in enumerate(positions):
        players.append({
            "player_id": str(i),
            "name": f"P{i}",
            "position": pos,
            "market_value": 1_000_000,
            "average_points": 50 + i,
            "kickbase_status": 0,
        })
    result = optimize_lineup(players)
    assert result["formation"] == "3-5-2"
    assert sum(1 for p in result["players"] if p["position"] == "ABW") == 3
    assert sum(1 for p in result["players"] if p["position"] == "MF") == 5
    assert sum(1 for p in result["players"] if p["position"] == "ST") == 2


def test_lineup_optimizer_chooses_best_valid_formation():
    players = [{"player_id": "gk", "name": "GK", "position": "TW", "market_value": 1_000_000, "average_points": 50, "kickbase_status": 0}]
    # Three very strong defenders, a weak fourth defender, five strong midfielders and three forwards.
    specs = [
        ("ABW", 100), ("ABW", 95), ("ABW", 90), ("ABW", 1),
        ("MF", 110), ("MF", 105), ("MF", 100), ("MF", 95), ("MF", 90),
        ("ST", 80), ("ST", 75), ("ST", 70),
    ]
    for i, (pos, points) in enumerate(specs):
        players.append({"player_id": f"p{i}", "name": f"P{i}", "position": pos, "market_value": 1_000_000, "average_points": points, "kickbase_status": 0})
    result = optimize_lineup(players)
    assert result["formation"] == "3-5-2"


def test_lineup_optimizer_can_force_424():
    players = []
    positions = ["TW"] + ["ABW"] * 5 + ["MF"] * 5 + ["ST"] * 4
    for i, pos in enumerate(positions):
        players.append({
            "player_id": str(i),
            "name": f"P{i}",
            "position": pos,
            "market_value": 1_000_000,
            "average_points": 50 + i,
            "kickbase_status": 0,
        })
    result = optimize_lineup(players, formation="4-2-4")
    assert result["feasible"] is True
    assert result["formation"] == "4-2-4"
    assert sum(1 for p in result["players"] if p["position"] == "ABW") == 4
    assert sum(1 for p in result["players"] if p["position"] == "MF") == 2
    assert sum(1 for p in result["players"] if p["position"] == "ST") == 4


def test_lineup_optimizer_marks_forced_formation_infeasible_without_fallback():
    players = []
    positions = ["TW"] + ["ABW"] * 4 + ["MF"] * 5 + ["ST"] * 2
    for i, pos in enumerate(positions):
        players.append({
            "player_id": str(i),
            "name": f"P{i}",
            "position": pos,
            "market_value": 1_000_000,
            "average_points": 50 + i,
            "kickbase_status": 0,
        })
    result = optimize_lineup(players, formation="5-2-3")
    assert result["feasible"] is False
    assert result["formation"] == "5-2-3"
    assert result["players"] == []
    assert result["missing"] == {"ABW": 1, "ST": 1}


def test_player_form_keeps_match_id_and_prefers_current_season_group():
    payload = {
        "it": [
            {"sid": "34", "ti": "2025/2026", "ph": [{"mi": "8604", "day": 33, "p": 152}]},
            {"sid": "42", "ti": "2026/2027", "ph": [
                {"mi": "11935", "day": 1, "p": 101, "cur": True, "t1": "43", "t2": "15"}
            ]},
        ]
    }
    result = player_form(payload)
    assert len(result["matches"]) == 1
    assert result["matches"][0]["match_id"] == "11935"
    assert result["matches"][0]["season_title"] == "2026/2027"


def test_event_type_and_playercenter_normalization():
    from app.intelligence import normalize_event_types, normalize_match_events

    labels = normalize_event_types({"it": [
        {"i": 3426, "ti": "Minutenbonus"},
        {"i": 3416, "ti": "Ballverlust"},
    ]})
    assert labels == {"3426": "Minutenbonus", "3416": "Ballverlust"}

    summary = normalize_match_events({
        "i": "2522",
        "n": "Raum",
        "mi": 8604,
        "p": 152,
        "t1": 43,
        "t2": 39,
        "t1g": 2,
        "t2g": 1,
        "events": [
            {"ei": "1", "eti": 3426, "p": 6, "mt": 94},
            {"ei": "2", "eti": 3416, "p": -1, "mt": 67},
            {"ei": "3", "eti": 9999, "p": 0, "mt": 50},
        ],
    }, labels)
    assert summary["total_points"] == 152
    assert summary["event_points"] == 5
    assert summary["unmapped_points"] == 147
    assert [event["label"] for event in summary["point_events"]] == ["Minutenbonus", "Ballverlust"]
