from app.preseason_tools import add_value_scores, optimize_starting_squad


def test_value_score_is_position_relative():
    rows = [
        {"player_id":"a","position":"MF","squad_fit_score":80,"investment_score":70,"effective_price":5_000_000},
        {"player_id":"b","position":"MF","squad_fit_score":70,"investment_score":60,"effective_price":20_000_000},
    ]
    out = add_value_scores(rows)
    assert out[0]["value_score"] > out[1]["value_score"]



def test_optimizer_respects_budget_and_formation():
    squad = [
        {"player_id":"tw","name":"TW","position":"TW","squad_value_score":60},
        {"player_id":"a1","name":"A1","position":"ABW","squad_value_score":60},
        {"player_id":"a2","name":"A2","position":"ABW","squad_value_score":60},
        {"player_id":"a3","name":"A3","position":"ABW","squad_value_score":60},
        {"player_id":"m1","name":"M1","position":"MF","squad_value_score":60},
        {"player_id":"m2","name":"M2","position":"MF","squad_value_score":60},
        {"player_id":"m3","name":"M3","position":"MF","squad_value_score":60},
        {"player_id":"m4","name":"M4","position":"MF","squad_value_score":60},
        {"player_id":"s1","name":"S1","position":"ST","squad_value_score":60},
        {"player_id":"s2","name":"S2","position":"ST","squad_value_score":60},
        {"player_id":"s3","name":"S3","position":"ST","squad_value_score":60},
    ]
    market = [
        {"player_id":"new","name":"New","position":"MF","squad_fit_score":95,"investment_score":80,"value_score":90,"effective_price":5_000_000,"portfolio_role":"KADERZIEL"}
    ]
    result = optimize_starting_squad(squad, market, 5_000_000)
    assert result["feasible"] is True
    assert len(result["players"]) == 11
    assert result["spent"] <= 5_000_000
    assert result["formation"] in {"3-4-3","3-5-2","4-3-3","4-4-2","4-5-1","5-3-2","5-4-1"}
