use std::collections::HashMap;

use serde::Serialize;
use serde_json::Value;
use tauri::State;

use crate::{
    kickbase::{
        error::CommandError,
        league::parse_league_managers,
        market::parse_market,
        squad::{parse_squad, PlayerPosition},
        validation::api_id,
    },
    state::AppState,
};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FairValueReferencePlayer {
    pub player_id: String,
    pub position: Option<i64>,
    pub market_value: i64,
    pub average_points: f64,
    pub total_points: Option<i64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FairValueReferenceResponse {
    pub players: Vec<FairValueReferencePlayer>,
    pub sample_size: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FairValueDatasetPlayer {
    pub player_id: String,
    pub name: String,
    pub first_name: Option<String>,
    pub position: i64,
    pub market_value: i64,
    pub average_points: f64,
    pub total_points: i64,
    pub status: i64,
    pub owner_id: Option<String>,
    pub owner_name: Option<String>,
    pub owner_is_self: bool,
    pub on_market: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FairValueDatasetResponse {
    pub players: Vec<FairValueDatasetPlayer>,
    pub manager_count: usize,
    pub loaded_manager_count: usize,
    pub unavailable_manager_count: usize,
}

#[tauri::command]
pub async fn fair_value_dataset(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<FairValueDatasetResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let token = state.active_token().await?;
    let managers_payload = state
        .kickbase
        .get_json(
            &token,
            &format!("/v4/leagues/{league_id}/settings/managers"),
        )
        .await?;
    let market_payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/market"))
        .await?;
    let managers = parse_league_managers(&managers_payload, &Value::Null);
    let manager_count = managers.len();
    let manager_meta = managers
        .iter()
        .map(|manager| (manager.id.clone(), (manager.name.clone(), manager.is_self)))
        .collect::<HashMap<_, _>>();

    let semaphore = state.player_request_limit.clone();
    let mut tasks = tokio::task::JoinSet::new();
    for manager in managers {
        let manager_id = match api_id(&manager.id, "Manager-ID") {
            Ok(manager_id) => manager_id,
            Err(_) => continue,
        };
        let client = state.kickbase.clone();
        let token = token.clone();
        let league_id = league_id.clone();
        let semaphore = semaphore.clone();
        tasks.spawn(async move {
            let result = match semaphore.acquire_owned().await {
                Ok(_permit) => client
                    .get_json(
                        &token,
                        &format!("/v4/leagues/{league_id}/managers/{manager_id}/squad"),
                    )
                    .await
                    .and_then(|payload| parse_squad(&payload)),
                Err(_) => Err(CommandError::internal(
                    "Die Fair-Value-Datenabfrage wurde abgebrochen.",
                )),
            };
            (manager_id, result)
        });
    }

    let mut by_id = HashMap::<String, FairValueDatasetPlayer>::new();
    let mut loaded_manager_count = 0usize;
    while let Some(result) = tasks.join_next().await {
        match result {
            Ok((manager_id, Ok(squad))) => {
                loaded_manager_count += 1;
                let (owner_name, owner_is_self) = manager_meta
                    .get(&manager_id)
                    .cloned()
                    .unwrap_or_else(|| (format!("Manager {manager_id}"), false));
                for player in squad.players {
                    let Some(position) = position_code(&player.position) else {
                        continue;
                    };
                    let (Some(market_value), Some(average_points), Some(total_points)) = (
                        player.market_value,
                        player.average_points,
                        player.points_total,
                    ) else {
                        continue;
                    };
                    if market_value <= 0
                        || average_points <= 0.0
                        || !average_points.is_finite()
                        || total_points <= 0
                    {
                        continue;
                    }
                    by_id.insert(
                        player.id.clone(),
                        FairValueDatasetPlayer {
                            player_id: player.id,
                            name: player.name,
                            first_name: player.first_name,
                            position,
                            market_value,
                            average_points,
                            total_points,
                            status: player.status.unwrap_or(0),
                            owner_id: Some(manager_id.clone()),
                            owner_name: Some(owner_name.clone()),
                            owner_is_self,
                            on_market: false,
                        },
                    );
                }
            }
            Ok((_manager_id, Err(_error))) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][fair-value] manager={} squad_failed={:?}",
                    _manager_id,
                    _error
                );
            }
            Err(_error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][fair-value] squad_task_failed={:?}",
                    _error
                );
            }
        }
    }

    let market = parse_market(&market_payload)?;
    for entry in market.entries {
        let Some(position) = position_code(&entry.position) else {
            continue;
        };
        let (Some(market_value), Some(average_points), Some(total_points)) =
            (entry.market_value, entry.average_points, entry.points_total)
        else {
            continue;
        };
        if market_value <= 0
            || average_points <= 0.0
            || !average_points.is_finite()
            || total_points <= 0
        {
            continue;
        }
        if let Some(player) = by_id.get_mut(&entry.player_id) {
            player.on_market = true;
            player.market_value = market_value;
            player.average_points = average_points;
            player.total_points = total_points;
            player.status = entry.status.unwrap_or(player.status);
        } else {
            let seller_id = entry.seller_id;
            let (owner_name, owner_is_self) = seller_id
                .as_ref()
                .and_then(|id| manager_meta.get(id))
                .cloned()
                .map(|(name, is_self)| (Some(name), is_self))
                .unwrap_or((entry.seller_name, false));
            by_id.insert(
                entry.player_id.clone(),
                FairValueDatasetPlayer {
                    player_id: entry.player_id,
                    name: entry.name,
                    first_name: entry.first_name,
                    position,
                    market_value,
                    average_points,
                    total_points,
                    status: entry.status.unwrap_or(0),
                    owner_id: seller_id,
                    owner_name,
                    owner_is_self,
                    on_market: true,
                },
            );
        }
    }

    let mut players = by_id.into_values().collect::<Vec<_>>();
    players.sort_by(|a, b| {
        a.position
            .cmp(&b.position)
            .then_with(|| b.average_points.total_cmp(&a.average_points))
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    let unavailable_manager_count = manager_count.saturating_sub(loaded_manager_count);

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][fair-value] players={} managers_loaded={}/{}",
        players.len(),
        loaded_manager_count,
        manager_count
    );

    Ok(FairValueDatasetResponse {
        players,
        manager_count,
        loaded_manager_count,
        unavailable_manager_count,
    })
}

fn position_code(position: &PlayerPosition) -> Option<i64> {
    match position {
        PlayerPosition::Goalkeeper => Some(1),
        PlayerPosition::Defender => Some(2),
        PlayerPosition::Midfielder => Some(3),
        PlayerPosition::Forward => Some(4),
        PlayerPosition::Unknown => None,
    }
}

#[tauri::command]
pub async fn fair_value_reference(
    state: State<'_, AppState>,
) -> Result<FairValueReferenceResponse, CommandError> {
    let token = state.active_token().await?;
    let mut by_id: HashMap<String, FairValueReferencePlayer> = HashMap::new();

    // The competition endpoint is capped at 25 entries, but the position filter
    // is honored. Four position-scoped requests therefore give us a broad,
    // current Bundesliga reference set without fanning out to player details.
    for position in 1..=4 {
        let payload = state
            .kickbase
            .get_json(
                &token,
                &format!("/v4/competitions/1/players?position={position}&sorting=1"),
            )
            .await?;
        for player in parse_reference_players(&payload, Some(position)) {
            by_id.insert(player.player_id.clone(), player);
        }
    }

    let players = by_id.into_values().collect::<Vec<_>>();
    let sample_size = players.len();

    #[cfg(debug_assertions)]
    crate::kt_debug!("[KickTrack][DEBUG][fair-value] reference_players={sample_size}");

    Ok(FairValueReferenceResponse {
        players,
        sample_size,
    })
}

fn parse_reference_players(
    payload: &Value,
    requested_position: Option<i64>,
) -> Vec<FairValueReferencePlayer> {
    let Some(items) = payload
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| payload.as_array())
    else {
        return Vec::new();
    };

    items
        .iter()
        .filter_map(|value| {
            let player_id = string_value(value, &["i", "pi", "id", "playerId"])?;
            let market_value = int_value(value, &["mv", "marketValue"])?;
            let average_points = number_value(value, &["ap", "averagePoints"])?;
            if market_value < 500_000 || !average_points.is_finite() || average_points <= 0.0 {
                return None;
            }
            Some(FairValueReferencePlayer {
                player_id,
                position: int_value(value, &["pos", "position"]).or(requested_position),
                market_value,
                average_points,
                total_points: int_value(value, &["p", "tp", "points", "pointsTotal"]),
            })
        })
        .collect()
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FixtureOutlookItem {
    pub day_number: i64,
    pub match_id: String,
    pub team_id: String,
    pub opponent_id: String,
    pub opponent_name: String,
    pub is_home: bool,
    pub kickoff: Option<String>,
    pub opponent_attack_index: f64,
    pub opponent_defense_index: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FixtureOutlookResponse {
    pub fixtures_by_team: HashMap<String, Vec<FixtureOutlookItem>>,
    pub completed_matches: usize,
    pub data_quality: String,
}

#[derive(Default, Debug, Clone)]
struct TeamStats {
    games: i64,
    goals_for: i64,
    goals_against: i64,
}

#[derive(Debug, Clone)]
struct RawFixture {
    day: i64,
    match_id: String,
    home_id: String,
    away_id: String,
    home_name: String,
    away_name: String,
    kickoff: Option<String>,
    status: Option<i64>,
    home_goals: Option<i64>,
    away_goals: Option<i64>,
}

#[tauri::command]
pub async fn fixture_outlook(
    state: State<'_, AppState>,
) -> Result<FixtureOutlookResponse, CommandError> {
    let token = state.active_token().await?;
    let payload = state
        .kickbase
        .get_json(&token, "/v4/competitions/1/matchdays")
        .await?;
    let fixtures = parse_all_fixtures(&payload);

    let mut stats: HashMap<String, TeamStats> = HashMap::new();
    let mut completed_matches = 0usize;
    for fixture in &fixtures {
        let Some(home_goals) = fixture.home_goals else {
            continue;
        };
        let Some(away_goals) = fixture.away_goals else {
            continue;
        };
        if fixture.status != Some(2) {
            continue;
        }
        completed_matches += 1;
        let home = stats.entry(fixture.home_id.clone()).or_default();
        home.games += 1;
        home.goals_for += home_goals;
        home.goals_against += away_goals;
        let away = stats.entry(fixture.away_id.clone()).or_default();
        away.games += 1;
        away.goals_for += away_goals;
        away.goals_against += home_goals;
    }

    let total_goals: i64 = stats.values().map(|s| s.goals_for).sum();
    let total_games: i64 = stats.values().map(|s| s.games).sum();
    let league_goal_rate = if total_games > 0 {
        total_goals as f64 / total_games as f64
    } else {
        1.5
    };
    let prior_games = 3.0; // early-season shrinkage keeps one wild result from dominating.

    let mut strengths: HashMap<String, (f64, f64)> = HashMap::new();
    let mut all_team_ids = Vec::<String>::new();
    for fixture in &fixtures {
        if !all_team_ids.contains(&fixture.home_id) {
            all_team_ids.push(fixture.home_id.clone());
        }
        if !all_team_ids.contains(&fixture.away_id) {
            all_team_ids.push(fixture.away_id.clone());
        }
    }
    for team_id in all_team_ids {
        let s = stats.get(&team_id).cloned().unwrap_or_default();
        let games = s.games as f64;
        let attack = (s.goals_for as f64 + prior_games * league_goal_rate)
            / (games + prior_games)
            / league_goal_rate.max(0.2);
        // >1 means the opponent concedes more than league average = easier to score against.
        let defense = (s.goals_against as f64 + prior_games * league_goal_rate)
            / (games + prior_games)
            / league_goal_rate.max(0.2);
        strengths.insert(team_id, (attack, defense));
    }

    let mut fixtures_by_team: HashMap<String, Vec<FixtureOutlookItem>> = HashMap::new();
    for fixture in fixtures.iter().filter(|f| f.status != Some(2)) {
        let (away_attack, away_defense) = strengths
            .get(&fixture.away_id)
            .copied()
            .unwrap_or((1.0, 1.0));
        fixtures_by_team
            .entry(fixture.home_id.clone())
            .or_default()
            .push(FixtureOutlookItem {
                day_number: fixture.day,
                match_id: fixture.match_id.clone(),
                team_id: fixture.home_id.clone(),
                opponent_id: fixture.away_id.clone(),
                opponent_name: fixture.away_name.clone(),
                is_home: true,
                kickoff: fixture.kickoff.clone(),
                opponent_attack_index: away_attack,
                opponent_defense_index: away_defense,
            });
        let (home_attack, home_defense) = strengths
            .get(&fixture.home_id)
            .copied()
            .unwrap_or((1.0, 1.0));
        fixtures_by_team
            .entry(fixture.away_id.clone())
            .or_default()
            .push(FixtureOutlookItem {
                day_number: fixture.day,
                match_id: fixture.match_id.clone(),
                team_id: fixture.away_id.clone(),
                opponent_id: fixture.home_id.clone(),
                opponent_name: fixture.home_name.clone(),
                is_home: false,
                kickoff: fixture.kickoff.clone(),
                opponent_attack_index: home_attack,
                opponent_defense_index: home_defense,
            });
    }
    for list in fixtures_by_team.values_mut() {
        list.sort_by_key(|item| item.day_number);
        list.truncate(5);
    }

    let data_quality = if completed_matches >= 45 {
        "HIGH"
    } else if completed_matches >= 18 {
        "MEDIUM"
    } else {
        "LOW"
    }
    .to_string();
    Ok(FixtureOutlookResponse {
        fixtures_by_team,
        completed_matches,
        data_quality,
    })
}

fn parse_all_fixtures(payload: &Value) -> Vec<RawFixture> {
    let Some(days) = payload
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| payload.as_array())
    else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for day in days {
        let day_number = int_value(day, &["day", "dn", "dayNumber"]).unwrap_or(0);
        let matches = day
            .get("it")
            .and_then(Value::as_array)
            .or_else(|| day.get("ms").and_then(Value::as_array))
            .or_else(|| day.get("matches").and_then(Value::as_array));
        let Some(matches) = matches else {
            continue;
        };
        for value in matches {
            let Some(home_id) = string_value(value, &["t1", "t1i", "homeTeamId"]) else {
                continue;
            };
            let Some(away_id) = string_value(value, &["t2", "t2i", "awayTeamId"]) else {
                continue;
            };
            out.push(RawFixture {
                day: day_number,
                match_id: string_value(value, &["mi", "i", "id", "matchId"]).unwrap_or_default(),
                home_id,
                away_id,
                home_name: string_value(value, &["t1sy", "t1n", "homeTeamName"])
                    .unwrap_or_else(|| "Heimteam".into()),
                away_name: string_value(value, &["t2sy", "t2n", "awayTeamName"])
                    .unwrap_or_else(|| "Auswärtsteam".into()),
                kickoff: string_value(value, &["dt", "md", "date", "kickoff"]),
                status: int_value(value, &["st", "status"]),
                home_goals: int_value(value, &["t1g", "t1go", "hg", "homeGoals", "homeScore"]),
                away_goals: int_value(value, &["t2g", "t2go", "ag", "awayGoals", "awayScore"]),
            });
        }
    }
    out
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
fn int_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number.as_i64(),
            Value::String(text) => text.parse::<i64>().ok(),
            _ => None,
        })
    })
}
fn number_value(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number.as_f64(),
            Value::String(text) => text.replace(',', ".").parse::<f64>().ok(),
            _ => None,
        })
    })
}

#[cfg(test)]
mod tests {
    use super::{parse_all_fixtures, parse_reference_players};
    use serde_json::json;

    #[test]
    fn parses_reference_player() {
        let rows = parse_reference_players(
            &json!({"it":[{"i":"7","pos":3,"mv":10000000,"ap":105.5,"p":211}]}),
            Some(3),
        );
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].market_value, 10_000_000);
    }

    #[test]
    fn parses_fixture_scores() {
        let rows = parse_all_fixtures(
            &json!({"it":[{"day":2,"it":[{"mi":"m","t1":"2","t2":"3","t1sy":"A","t2sy":"B","st":2,"t1g":2,"t2g":1}]}]}),
        );
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].home_goals, Some(2));
    }
}
