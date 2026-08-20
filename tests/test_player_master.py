from pathlib import Path

from app.player_master import _candidate_score, _extract_candidates
from app.storage import Storage


def test_sync_player_master_keeps_missing_players_before_marking_left(tmp_path: Path):
    storage = Storage(tmp_path / "kicktrack.db")
    first = [
        {"player_id": "1", "name": "Kane", "full_name": "Harry Kane", "club": "Bayern München", "team_id": "2", "position": "ST", "market_value": 50_000_000},
        {"player_id": "2", "name": "Porath", "full_name": "Finn Porath", "club": "Schalke 04", "team_id": "18", "position": "MF", "market_value": 5_000_000},
    ]
    result = storage.sync_player_master(first, missing_threshold=3)
    assert result["new"] == 2
    assert result["active"] == 2

    storage.sync_player_master(first[:1], missing_threshold=3)
    assert storage.player_master_row("2")["active_state"] == "UNKNOWN"
    storage.sync_player_master(first[:1], missing_threshold=3)
    assert storage.player_master_row("2")["active_state"] == "UNKNOWN"
    storage.sync_player_master(first[:1], missing_threshold=3)
    assert storage.player_master_row("2")["active_state"] == "LEFT_LEAGUE"


def test_returning_player_becomes_active_again(tmp_path: Path):
    storage = Storage(tmp_path / "kicktrack.db")
    player = {"player_id": "7", "name": "Test", "full_name": "Max Test", "club": "Testclub", "team_id": "9", "position": "MF"}
    storage.sync_player_master([player], missing_threshold=1)
    storage.sync_player_master([{"player_id": "8", "name": "Other", "full_name": "Other Player"}], missing_threshold=1)
    assert storage.player_master_row("7")["active_state"] == "LEFT_LEAGUE"
    storage.sync_player_master([player], missing_threshold=1)
    row = storage.player_master_row("7")
    assert row["active_state"] == "ACTIVE"
    assert row["miss_count"] == 0


def test_fotmob_candidate_parser_and_scoring():
    payload = {
        "results": [
            {"type": "player", "id": 1192406, "name": "Lorenz Assignon", "teamName": "VfB Stuttgart"},
            {"type": "team", "id": 1, "name": "VfB Stuttgart"},
        ]
    }
    candidates = _extract_candidates(payload)
    assert len(candidates) == 1
    assert candidates[0]["fotmob_id"] == "1192406"
    score, reason = _candidate_score(
        {"name": "Assignon", "full_name": "Lorenz Assignon", "club": "VfB Stuttgart"},
        candidates[0],
    )
    assert score >= 90
    assert "Name" in reason


def test_fotmob_current_search_gateway_payload():
    payload = {
        "squadMemberSuggest": [
            {
                "options": [
                    {
                        "text": "Lorenz Assignon|VfB Stuttgart",
                        "payload": {"id": 1192406, "teamId": 10269, "teamName": "VfB Stuttgart"},
                    }
                ]
            }
        ]
    }
    candidates = _extract_candidates(payload)
    assert candidates == [
        {
            "fotmob_id": "1192406",
            "name": "Lorenz Assignon",
            "team": "VfB Stuttgart",
            "position": "",
            "shirt_number": "",
            "raw": payload["squadMemberSuggest"][0]["options"][0],
        }
    ]
    score, _ = _candidate_score(
        {"name": "Assignon", "full_name": "Lorenz Assignon", "club": "VfB Stuttgart"},
        candidates[0],
    )
    assert score >= 90


def test_short_surname_plus_exact_club_is_auto_match_quality():
    score, reason = _candidate_score(
        {"name": "Porath", "full_name": "Porath", "club": "Schalke 04"},
        {"fotmob_id": "123", "name": "Finn Porath", "team": "Schalke 04"},
    )
    assert score >= 78
    assert "Nachname/Kurzname exakt" in reason


def test_short_surname_plus_similar_localized_club_is_auto_match_quality():
    score, reason = _candidate_score(
        {"name": "Kane", "full_name": "Kane", "club": "Bayern München"},
        {"fotmob_id": "456", "name": "Harry Kane", "team": "Bayern Munich"},
    )
    assert score >= 78
    assert "Nachname/Kurzname exakt" in reason


def test_portrait_review_acceptance_metadata_and_reject_reset(tmp_path: Path):
    from app.player_master import PortraitMatch

    storage = Storage(tmp_path / "kicktrack.db")
    storage.sync_player_master([
        {"player_id": "11", "name": "Porath", "full_name": "Porath", "club": "Schalke 04", "position": "MF"}
    ])
    storage.save_portrait_match(PortraitMatch(
        "11", "123", 74, "NEEDS_REVIEW", "Nachname/Kurzname exakt",
        "https://images.fotmob.com/image_resources/playerimages/123.png", None,
        "Finn Porath", "Schalke 04",
    ))

    rows = storage.portrait_review_rows()
    assert len(rows) == 1
    assert rows[0]["portrait_candidate_name"] == "Finn Porath"
    assert rows[0]["portrait_candidate_team"] == "Schalke 04"
    assert storage.player_master_stats()["review"] == 1

    storage.reject_portrait_candidate("11")
    assert storage.player_master_stats()["review"] == 0
    assert storage.player_master_stats()["rejected"] == 1
    assert storage.portrait_review_rows() == []

    assert storage.reset_rejected_portraits() == 1
    row = storage.player_master_row("11")
    assert row["portrait_state"] == "MISSING"


def test_same_surname_same_club_collision_requires_review(tmp_path: Path):
    from app.player_master import FotMobPortraitResolver

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "squadMemberSuggest": [{
                    "options": [
                        {"text": "Vitalie Becker|Schalke 04", "payload": {"id": 101, "teamName": "Schalke 04", "position": "Defender", "shirtNumber": 33}},
                        {"text": "Timo Becker|Schalke 04", "payload": {"id": 102, "teamName": "Schalke 04", "position": "Defender", "shirtNumber": 5}},
                    ]
                }]
            }

    resolver = FotMobPortraitResolver(tmp_path / "portraits")
    resolver.client.get = lambda *args, **kwargs: FakeResponse()
    match = resolver.search({"player_id": "77", "name": "Becker", "full_name": "Becker", "club": "Schalke 04", "position": "ABW"})
    resolver.close()

    assert match.state == "NEEDS_REVIEW"
    assert "gleicher Nachname mehrfach im selben Verein" in match.reason
    assert match.candidate_position == "Defender"
    assert match.candidate_shirt_number in {"33", "5"}


def test_player_master_can_be_enriched_with_kickbase_full_name(tmp_path: Path):
    storage = Storage(tmp_path / "kicktrack.db")
    storage.sync_player_master([
        {"player_id": "33", "name": "Becker", "full_name": "Becker", "club": "Schalke", "position": "ABW", "market_value": 1_000_000}
    ])
    updated = storage.enrich_player_master_identity("33", {
        "player_id": "33",
        "name": "Becker",
        "full_name": "Vitalie Becker",
        "club": "Schalke",
        "position": "ABW",
        "market_value": 1_100_000,
    })
    assert updated is not None
    assert updated["name"] == "Becker"
    assert updated["full_name"] == "Vitalie Becker"
    assert updated["market_value"] == 1_100_000
    assert updated["portrait_state"] == "MISSING"
