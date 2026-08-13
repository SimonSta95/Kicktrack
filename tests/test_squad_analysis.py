from app.squad_analysis import enrich_squad_entries


def player(pid, name, pos, mv, *, entry=None, role="OFFEN", d1=0, d3=0, d7=0, ap=None):
    pnl = mv - entry if entry else None
    roi = (pnl / entry * 100.0) if entry else None
    return {
        "player_id": str(pid), "name": name, "position": pos, "market_value": mv,
        "entry_value": entry, "player_role": role, "d1": d1, "d3": d3, "d7": d7,
        "average_points": ap, "pnl": pnl, "roi": roi,
    }


def test_scores_are_bounded_and_explained():
    rows = enrich_squad_entries([
        player(1, "A", "MF", 10_000_000, entry=8_000_000, role="STAMM", d1=100_000, d3=300_000, d7=700_000),
        player(2, "B", "MF", 5_000_000, entry=6_000_000, role="TRANSFERLISTE", d1=-100_000, d3=-200_000, d7=-500_000),
        player(3, "C", "ABW", 7_000_000, entry=7_000_000),
    ], points_are_current=False)
    assert len(rows) == 3
    for row in rows:
        assert 0 <= row["squad_value_score"] <= 100
        assert 0 <= row["investment_score"] <= 100
        assert 0 <= row["sell_score"] <= 100
        assert "KADERWERT" in row["squad_analysis_text"]
        assert row["squad_signal"]


def test_strong_rising_starter_is_more_hold_worthy_than_falling_transfer_player():
    rows = enrich_squad_entries([
        player(1, "Strong", "MF", 10_000_000, entry=8_000_000, role="STAMM", d1=200_000, d3=500_000, d7=900_000),
        player(2, "Weak", "MF", 5_000_000, entry=6_000_000, role="TRANSFERLISTE", d1=-150_000, d3=-350_000, d7=-700_000),
        player(3, "Peer", "MF", 7_000_000, entry=7_000_000),
        player(4, "Peer2", "MF", 6_500_000, entry=6_500_000),
    ], points_are_current=False)
    strong = next(r for r in rows if r["name"] == "Strong")
    weak = next(r for r in rows if r["name"] == "Weak")
    assert strong["squad_value_score"] > weak["squad_value_score"]
    assert strong["investment_score"] > weak["investment_score"]
    assert weak["sell_score"] > strong["sell_score"]


def test_sell_decision_sharpens_falling_transferlist_player():
    rows = enrich_squad_entries([
        player(1, "Exit", "MF", 8_000_000, entry=6_000_000, role="TRANSFERLISTE", d1=-180_000, d3=-450_000, d7=-900_000),
        player(2, "Peer", "MF", 7_000_000, entry=7_000_000),
        player(3, "Peer2", "MF", 7_500_000, entry=7_500_000),
        player(4, "Peer3", "MF", 6_500_000, entry=6_500_000),
    ], points_are_current=False)
    target = next(r for r in rows if r["name"] == "Exit")
    assert target["sell_verdict"] in {"EHER VERKAUFEN", "JETZT VERKAUFEN"}
    assert "MW-Exit-Signal" in target["sell_decision_text"]


def test_loss_alone_does_not_create_profit_capture_pressure():
    rows = enrich_squad_entries([
        player(1, "Loss", "ST", 6_000_000, entry=8_000_000, role="STAMM", d1=100_000, d3=250_000, d7=400_000),
        player(2, "Peer", "ST", 5_500_000, entry=5_500_000),
        player(3, "Peer2", "ST", 5_800_000, entry=5_800_000),
    ], points_are_current=False)
    target = next(r for r in rows if r["name"] == "Loss")
    assert target["sell_decision_breakdown"]["gewinnmitnahme"] == 0.0


def test_financeable_market_upgrade_increases_sell_context():
    squad = [
        player(1, "Own", "ABW", 5_000_000, entry=5_000_000, role="OFFEN", d1=0, d3=0, d7=0),
        player(2, "Peer", "ABW", 8_000_000, entry=8_000_000, role="STAMM"),
        player(3, "Peer2", "ABW", 8_500_000, entry=8_500_000, role="STAMM"),
        player(4, "Peer3", "ABW", 9_000_000, entry=9_000_000, role="STAMM"),
    ]
    market = [{
        "player_id": "99", "name": "Upgrade", "position": "ABW", "price": 7_000_000,
        "signal": "KADER-UPGRADE", "replacement_value": 2_000_000, "squad_fit_score": 82,
        "investment_score": 65,
    }]
    without = enrich_squad_entries(squad, points_are_current=False, available_budget=2_000_000)
    with_market = enrich_squad_entries(squad, points_are_current=False, market_rows=market, available_budget=2_000_000)
    a = next(r for r in without if r["name"] == "Own")
    b = next(r for r in with_market if r["name"] == "Own")
    assert b["sell_decision_score"] > a["sell_decision_score"]
    assert b["sell_replacement_player"]["name"] == "Upgrade"
