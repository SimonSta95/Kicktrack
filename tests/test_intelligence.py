from app.intelligence import player_form, parse_fixtures, fixture_run, trade_profile, squad_status, optimize_lineup, parse_activity_feed


def test_player_form_metrics():
    payload = {"it": [{"ph": [{"day": 1, "p": 50}, {"day": 2, "p": 70}, {"day": 3, "p": 90}]}]}
    result = player_form(payload)
    assert result["avg3"] == 70
    assert result["floor"] == 50
    assert result["ceiling"] == 90


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
