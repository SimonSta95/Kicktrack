from __future__ import annotations

# Canonical current Kickbase team-id mapping used by current squad/player views.
# IDs are derived from Kickbase payloads; historical transfer rows are not rewritten.
TEAM_NAMES: dict[str, str] = {
    "2": "Bayern",
    "3": "Dortmund",
    "4": "Frankfurt",
    "5": "Freiburg",
    "6": "Hamburg",
    "7": "Leverkusen",
    "8": "Schalke",
    "9": "Stuttgart",
    "10": "Bremen",
    "13": "Augsburg",
    "14": "Hoffenheim",
    "15": "Gladbach",
    "18": "Mainz",
    "28": "Köln",
    "29": "Paderborn",
    "40": "Union",
    "43": "Leipzig",
    "77": "Elversberg",
}


def team_name(team_id: str | int | None) -> str:
    if team_id is None:
        return ""
    key = str(team_id)
    return TEAM_NAMES.get(key, f"Team {key}")
