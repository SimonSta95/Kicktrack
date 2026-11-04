use std::{
    collections::HashMap,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use serde_json::Value;
use tauri::State;

use crate::{
    kickbase::{
        error::CommandError,
        league::{parse_league_managers, LeagueManager},
        validation::api_id,
    },
    state::AppState,
};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveLineupPlayer {
    pub player_id: String,
    pub name: String,
    pub position: Option<i64>,
    pub points: i64,
    pub team_id: Option<String>,
    pub status: Option<i64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveMatchdayResponse {
    pub day_number: Option<i64>,
    pub managers: Vec<LeagueManager>,
    pub own_lineup: Vec<LiveLineupPlayer>,
    pub own_lineup_available: bool,
    pub updated_at_unix: u64,
}

#[tauri::command]
pub async fn live_matchday(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<LiveMatchdayResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let token = state.active_token().await?;
    let managers_payload = state
        .kickbase
        .get_json(
            &token,
            &format!("/v4/leagues/{league_id}/settings/managers"),
        )
        .await?;
    let ranking_payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/ranking"))
        .await?;
    let mut managers = parse_league_managers(&managers_payload, &ranking_payload);
    managers.sort_by(|a, b| {
        b.current_matchday_points
            .unwrap_or(i64::MIN)
            .cmp(&a.current_matchday_points.unwrap_or(i64::MIN))
            .then_with(|| {
                a.place
                    .unwrap_or(i64::MAX)
                    .cmp(&b.place.unwrap_or(i64::MAX))
            })
    });

    let (own_lineup, own_lineup_available) = match state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/lineup/overview"))
        .await
    {
        Ok(payload) => (parse_live_lineup(&payload), true),
        Err(_error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][live] lineup overview failed: {:?}",
                _error
            );
            (Vec::new(), false)
        }
    };
    let day_number = integer_recursive(
        &ranking_payload,
        &[
            "day",
            "dn",
            "md",
            "matchday",
            "dayNumber",
            "currentMatchday",
        ],
        0,
    );
    let updated_at_unix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);

    Ok(LiveMatchdayResponse {
        day_number,
        managers,
        own_lineup,
        own_lineup_available,
        updated_at_unix,
    })
}

fn parse_live_lineup(payload: &Value) -> Vec<LiveLineupPlayer> {
    let mut players = HashMap::<String, LiveLineupPlayer>::new();
    collect_live_players(payload, &mut players, 0);
    let mut players = players.into_values().collect::<Vec<_>>();
    players.sort_by(|a, b| {
        a.position
            .unwrap_or(i64::MAX)
            .cmp(&b.position.unwrap_or(i64::MAX))
            .then_with(|| b.points.cmp(&a.points))
            .then_with(|| a.name.cmp(&b.name))
    });
    players
}

fn collect_live_players(
    value: &Value,
    players: &mut HashMap<String, LiveLineupPlayer>,
    depth: usize,
) {
    if depth > 10 {
        return;
    }
    match value {
        Value::Object(map) => {
            let explicit_player_id = string_value(value, &["pi", "playerId"]);
            let position = integer_value(value, &["pos", "position"]);
            let id = explicit_player_id.or_else(|| {
                position
                    .filter(|position| (1..=4).contains(position))
                    .and_then(|_| string_value(value, &["i", "id"]))
            });
            if let Some(player_id) = id {
                if let Some(points) =
                    integer_value(value, &["mdp", "livePoints", "pts", "points", "p"])
                {
                    let name = string_value(value, &["pn", "n", "name"])
                        .unwrap_or_else(|| format!("Spieler {player_id}"));
                    players.insert(
                        player_id.clone(),
                        LiveLineupPlayer {
                            player_id,
                            name,
                            position,
                            points,
                            team_id: string_value(value, &["tid", "teamId"]),
                            status: integer_value(value, &["st", "status"]),
                        },
                    );
                }
            }
            for child in map.values() {
                collect_live_players(child, players, depth + 1);
            }
        }
        Value::Array(items) => {
            for child in items {
                collect_live_players(child, players, depth + 1);
            }
        }
        _ => {}
    }
}

fn string_value(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::String(text) if !text.trim().is_empty() => Some(text.trim().to_string()),
            Value::Number(number) => Some(number.to_string()),
            _ => None,
        })
    })
}

fn integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number
                .as_i64()
                .or_else(|| number.as_f64().map(|value| value.round() as i64)),
            Value::String(text) => text.parse::<i64>().ok(),
            _ => None,
        })
    })
}

fn integer_recursive(value: &Value, keys: &[&str], depth: usize) -> Option<i64> {
    if depth > 6 {
        return None;
    }
    if let Some(value) = integer_value(value, keys) {
        return Some(value);
    }
    match value {
        Value::Object(map) => map
            .values()
            .find_map(|child| integer_recursive(child, keys, depth + 1)),
        Value::Array(items) => items
            .iter()
            .find_map(|child| integer_recursive(child, keys, depth + 1)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::parse_live_lineup;
    use serde_json::json;

    #[test]
    fn parses_nested_live_lineup_and_ignores_team_totals() {
        let payload = json!({
            "team": { "i": "team-1", "n": "Team", "p": 420 },
            "it": [
                { "pi": "p1", "pn": "Spieler Eins", "pos": 3, "p": 88, "tid": "10" },
                { "i": "p2", "n": "Spieler Zwei", "position": 4, "livePoints": -2 }
            ]
        });
        let players = parse_live_lineup(&payload);
        assert_eq!(players.len(), 2);
        assert_eq!(players[0].player_id, "p1");
        assert_eq!(players[1].points, -2);
    }
}
