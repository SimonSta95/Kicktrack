use std::collections::HashMap;

use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeagueManager {
    pub id: String,
    pub name: String,
    pub profile_image_path: Option<String>,
    pub is_self: bool,
    pub team_value: Option<i64>,
    pub profit: Option<i64>,
    pub points: Option<i64>,
    pub current_matchday_points: Option<i64>,
    pub average_points: Option<f64>,
    pub matchday_wins: Option<i64>,
    pub place: Option<i64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeagueOverviewResponse {
    pub managers: Vec<LeagueManager>,
}

pub fn parse_league_managers(managers_payload: &Value, ranking_payload: &Value) -> Vec<LeagueManager> {
    let mut by_id: HashMap<String, LeagueManager> = HashMap::new();

    for value in items(managers_payload) {
        absorb_manager(&mut by_id, value);
    }
    for value in items(ranking_payload) {
        absorb_manager(&mut by_id, value);
    }

    let mut managers = by_id.into_values().collect::<Vec<_>>();
    managers.sort_by(|a, b| {
        a.place
            .unwrap_or(i64::MAX)
            .cmp(&b.place.unwrap_or(i64::MAX))
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    managers
}

fn absorb_manager(by_id: &mut HashMap<String, LeagueManager>, value: &Value) {
    let Some(id) = string_value(value, &["i", "u", "ui", "id", "managerId", "userId"]) else {
        return;
    };

    let fallback_name = format!("Manager {id}");
    let entry = by_id.entry(id.clone()).or_insert_with(|| LeagueManager {
        id,
        name: fallback_name,
        profile_image_path: None,
        is_self: false,
        team_value: None,
        profit: None,
        points: None,
        current_matchday_points: None,
        average_points: None,
        matchday_wins: None,
        place: None,
    });

    if let Some(name) = string_value(value, &["unm", "n", "name", "username"]) {
        entry.name = name;
    }
    entry.profile_image_path = string_value(value, &["uim", "im", "profileImage", "profile"])
        .or_else(|| entry.profile_image_path.clone());
    entry.is_self = bool_value(value, &["isu", "isUser", "is_user", "me"]).unwrap_or(entry.is_self);
    entry.team_value = integer_value(value, &["tv", "teamValue"]).or(entry.team_value);
    entry.profit = integer_value(value, &["prft", "profit"]).or(entry.profit);
    entry.points = integer_value(value, &["tp", "p", "points", "totalPoints"]).or(entry.points);
    entry.current_matchday_points = current_matchday_points(value).or(entry.current_matchday_points);
    entry.average_points = number_value(value, &["ap", "averagePoints"]).or(entry.average_points);
    entry.matchday_wins = integer_value(value, &["mdw", "matchdayWins"]).or(entry.matchday_wins);
    entry.place = integer_value(value, &["pl", "place", "rank", "ranking"]).or(entry.place);
}


pub fn merge_manager_dashboard(manager: &mut LeagueManager, payload: &Value) {
    if let Some(name) = string_value(payload, &["unm", "n", "name", "username"]) {
        manager.name = name;
    }
    manager.profile_image_path = string_value(payload, &["uim", "im", "profileImage", "profile"])
        .or_else(|| manager.profile_image_path.clone());

    // Dashboard is the most specific live manager resource. If a field is
    // present here, it wins over the compact settings/ranking payload.
    if let Some(value) = integer_value(payload, &["tv", "teamValue"]) {
        manager.team_value = Some(value);
    }
    if let Some(value) = integer_value(payload, &["prft", "profit"]) {
        manager.profit = Some(value);
    }
    if let Some(value) = integer_value(payload, &["tp", "p", "points", "totalPoints"]) {
        manager.points = Some(value);
    }
    if let Some(value) = current_matchday_points(payload) {
        manager.current_matchday_points = Some(value);
    }
    if let Some(value) = number_value(payload, &["ap", "averagePoints"]) {
        manager.average_points = Some(value);
    }
    if let Some(value) = integer_value(payload, &["mdw", "matchdayWins"]) {
        manager.matchday_wins = Some(value);
    }
    if let Some(value) = integer_value(payload, &["pl", "place", "rank", "ranking"]) {
        manager.place = Some(value);
    }
}

fn current_matchday_points(value: &Value) -> Option<i64> {
    // Live matchday points are exposed directly by the league ranking as `mdp`.
    // `ph` on the manager dashboard is historical matchday data and must never
    // overwrite the live value: during an active matchday its last entry can
    // still be the previous completed gameweek.
    integer_value(
        value,
        &[
            "mdp",
            "currentMatchdayPoints",
            "matchdayPoints",
            "currentPoints",
        ],
    )
}

fn items(value: &Value) -> Vec<&Value> {
    if let Some(array) = value.as_array() {
        return array.iter().collect();
    }

    for key in ["it", "us", "users", "managers", "ranking"] {
        if let Some(array) = value.get(key).and_then(Value::as_array) {
            return array.iter().collect();
        }
    }

    Vec::new()
}

fn string_value(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::String(text) if !text.trim().is_empty() => Some(text.to_string()),
            Value::Number(number) => Some(number.to_string()),
            _ => None,
        })
    })
}

fn integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| value.get(*key).and_then(number_as_i64))
}

fn number_as_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok()))
            .or_else(|| number.as_f64().map(|value| value.round() as i64)),
        Value::String(text) => text
            .parse::<i64>()
            .ok()
            .or_else(|| text.parse::<f64>().ok().map(|value| value.round() as i64)),
        _ => None,
    }
}

fn number_value(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number.as_f64(),
            Value::String(text) => text.parse::<f64>().ok(),
            _ => None,
        })
    })
}

fn bool_value(value: &Value, keys: &[&str]) -> Option<bool> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Bool(flag) => Some(*flag),
            Value::Number(number) => number.as_i64().map(|number| number != 0),
            Value::String(text) => match text.as_str() {
                "true" | "1" => Some(true),
                "false" | "0" => Some(false),
                _ => None,
            },
            _ => None,
        })
    })
}


#[cfg(test)]
mod tests {
    use super::current_matchday_points;
    use serde_json::json;

    #[test]
    fn reads_live_matchday_points_from_ranking_field() {
        assert_eq!(current_matchday_points(&json!({"mdp": 228})), Some(228));
    }

    #[test]
    fn ignores_manager_points_history_for_live_points() {
        assert_eq!(current_matchday_points(&json!({"ph": [1241, 650, 587]})), None);
    }

    #[test]
    fn explicit_live_field_wins_even_when_history_exists() {
        assert_eq!(
            current_matchday_points(&json!({"mdp": 228, "ph": [1241]})),
            Some(228)
        );
    }
}
