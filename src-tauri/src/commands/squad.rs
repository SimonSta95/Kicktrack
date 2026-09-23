use std::{collections::HashMap, fs};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use tauri::State;

use crate::{
    db::{bytes_data_url, file_data_url, KickTrackDatabase},
    kickbase::{
        error::CommandError,
        squad::{parse_squad, parse_team_logos, SquadResponse},
    },
    portraits::sync_portraits_for_player_ids,
    state::AppState,
};

fn current_token(state: &State<'_, AppState>) -> Result<String, CommandError> {
    let session = state
        .session
        .lock()
        .map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;

    session
        .as_ref()
        .map(|session| session.token.clone())
        .ok_or_else(CommandError::session_expired)
}


#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NextFixture {
    pub match_id: String,
    pub home_team_id: String,
    pub away_team_id: String,
    pub home_team_name: String,
    pub away_team_name: String,
    pub kickoff: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NextMatchdayResponse {
    pub day_number: Option<i64>,
    pub fixtures: Vec<NextFixture>,
}

#[tauri::command]
pub async fn league_next_matchday(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<NextMatchdayResponse, CommandError> {
    if league_id.trim().is_empty() {
        return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich."));
    }

    let token = current_token(&state)?;
    let payload = state
        .kickbase
        .get_json(&token, "/v4/competitions/1/matchdays")
        .await?;

    let result = parse_next_matchday(&payload);

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][fixtures] league={} day={:?} fixtures={}",
        league_id.trim(),
        result.day_number,
        result.fixtures.len()
    );

    Ok(result)
}

fn parse_next_matchday(payload: &Value) -> NextMatchdayResponse {
    let days = payload
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| payload.as_array());

    let Some(days) = days else {
        return NextMatchdayResponse { day_number: None, fixtures: Vec::new() };
    };

    // Kickbase has shipped both `it` and `ms` as the match collection in this
    // resource. Prefer the first matchday that still contains a planned/live
    // match. This also keeps partially played matchdays visible until complete.
    let selected = days.iter().find(|day| {
        day_matches(day).is_some_and(|matches| {
            matches.iter().any(|fixture| match_status(fixture) != Some(2))
        })
    });

    let Some(day) = selected else {
        return NextMatchdayResponse { day_number: None, fixtures: Vec::new() };
    };

    let day_number = int_value(day, &["day", "dn", "dayNumber"]);
    let fixtures = day_matches(day)
        .into_iter()
        .flatten()
        .filter_map(parse_fixture)
        .collect();

    NextMatchdayResponse { day_number, fixtures }
}

fn day_matches(day: &Value) -> Option<&Vec<Value>> {
    day.get("it")
        .and_then(Value::as_array)
        .or_else(|| day.get("ms").and_then(Value::as_array))
        .or_else(|| day.get("matches").and_then(Value::as_array))
}

fn match_status(fixture: &Value) -> Option<i64> {
    int_value(fixture, &["st", "status"])
}

fn parse_fixture(fixture: &Value) -> Option<NextFixture> {
    let home_team_id = scalar_string(fixture, &["t1", "t1i", "homeTeamId", "home_team_id"])?;
    let away_team_id = scalar_string(fixture, &["t2", "t2i", "awayTeamId", "away_team_id"])?;

    Some(NextFixture {
        match_id: scalar_string(fixture, &["mi", "id", "matchId"]).unwrap_or_default(),
        home_team_id,
        away_team_id,
        home_team_name: scalar_string(
            fixture,
            &["t1sy", "t1n", "homeTeamName", "home_team_name"],
        )
        .unwrap_or_else(|| "Heimteam".to_string()),
        away_team_name: scalar_string(
            fixture,
            &["t2sy", "t2n", "awayTeamName", "away_team_name"],
        )
        .unwrap_or_else(|| "Auswärtsteam".to_string()),
        kickoff: scalar_string(fixture, &["dt", "md", "date", "kickoff"]),
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

#[tauri::command]
pub async fn league_squad(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<SquadResponse, CommandError> {
    if league_id.trim().is_empty() {
        return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich."));
    }

    let token = current_token(&state)?;
    let league_id = league_id.trim();
    let payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/squad"))
        .await?;

    let mut squad = parse_squad(&payload)?;
    let mut db = KickTrackDatabase::open_default()?;

    // Logo mapping is additive. If Kickbase changes this auxiliary endpoint,
    // the squad itself still loads and falls back to already cached logo data.
    if let Ok(team_payload) = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/lineup/teams"))
        .await
    {
        let logo_map = parse_team_logos(&team_payload);
        if !logo_map.is_empty() {
            if let Err(error) = db.upsert_team_logos(&logo_map) {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][squad:logos] cache metadata write failed: {:?}",
                    error
                );
            }
        }
    }

    // Live Kickbase payloads are authoritative for player existence. Register
    // every currently seen player before enrichment, so post-transfer-window
    // arrivals are not limited to the historical DB snapshot.
    let portrait_ids = squad.players.iter().map(|player| player.id.clone()).collect::<Vec<_>>();
    for player in &squad.players {
        let full_name = player.first_name.as_deref().map(|first| {
            let first = first.trim();
            if first.is_empty() || player.name.to_lowercase().starts_with(&format!("{} ", first.to_lowercase())) {
                player.name.clone()
            } else {
                format!("{first} {}", player.name)
            }
        });
        let position = match &player.position {
            crate::kickbase::squad::PlayerPosition::Goalkeeper => "TW",
            crate::kickbase::squad::PlayerPosition::Defender => "ABW",
            crate::kickbase::squad::PlayerPosition::Midfielder => "MF",
            crate::kickbase::squad::PlayerPosition::Forward => "ST",
            crate::kickbase::squad::PlayerPosition::Unknown => "UNKNOWN",
        };
        db.upsert_player_reference(
            &player.id,
            &player.name,
            full_name.as_deref(),
            player.team_id.as_deref(),
            Some(position),
        )?;
    }
    drop(db);

    // Incremental auto-sync: only newly seen/missing player IDs reach FotMob.
    // Cached, rejected and manual-review mappings are skipped by the DB query.
    match sync_portraits_for_player_ids(league_id, &portrait_ids, &state).await {
        Ok(summary) => {
            #[cfg(debug_assertions)]
            if summary.requested > 0 {
                crate::kt_debug!(
                    "[KickTrack][DEBUG][portrait:auto] source=squad requested={} cached={} review={} failed={}",
                    summary.requested, summary.cached, summary.review, summary.failed
                );
            }
        }
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][portrait:auto] source=squad failed={:?}",
                error
            );
        }
    }

    let db = KickTrackDatabase::open_default()?;
    let mut logo_cache: HashMap<String, Option<String>> = HashMap::new();

    for player in &mut squad.players {
        let enrichment = db.player_enrichment(&player.id, player.team_id.as_deref())?;
        if player.first_name.is_none() { player.first_name = sanitize_first_name(enrichment.first_name.clone(), &player.name); }
        else { player.first_name = sanitize_first_name(player.first_name.take(), &player.name); }
        player.club_name = enrichment.club_name;
        player.portrait_data_url = enrichment.portrait_data_url;

        let Some(team_id) = player.team_id.clone() else {
            continue;
        };

        if let Some(cached) = logo_cache.get(&team_id) {
            player.team_logo_data_url = cached.clone();
            continue;
        }

        let local_logo = enrichment
            .team_logo_local_path
            .as_deref()
            .and_then(file_data_url);

        let resolved = if local_logo.is_some() {
            local_logo
        } else if let Some(remote_path) = enrichment.team_logo_remote_path.as_deref() {
            match state.kickbase.get_bytes(&token, remote_path).await {
                Ok(bytes) => {
                    if let Ok(cache_path) = db.team_logo_cache_path(&team_id, remote_path) {
                        match fs::write(&cache_path, &bytes) {
                            Ok(()) => {
                                if let Err(error) = db.set_team_logo_local_path(&team_id, &cache_path) {
                                    #[cfg(debug_assertions)]
                                    crate::kt_debug!(
                                        "[KickTrack][DEBUG][squad:logos] local path write failed team={}: {:?}",
                                        team_id, error
                                    );
                                }
                            }
                            Err(error) => {
                                #[cfg(debug_assertions)]
                                crate::kt_debug!(
                                    "[KickTrack][DEBUG][squad:logos] cache file write failed team={}: {}",
                                    team_id, error
                                );
                            }
                        }
                    }
                    Some(bytes_data_url(&bytes, remote_path))
                }
                Err(_) => None,
            }
        } else {
            None
        };

        logo_cache.insert(team_id, resolved.clone());
        player.team_logo_data_url = resolved;
    }

    // The compact squad payload omits `fn` for many players. Resolve all missing
    // first names with one competition-catalog request instead of N player-detail
    // requests. This keeps the squad/sales UI complete without a request fan-out.
    if squad.players.iter().any(|player| player.first_name.is_none()) {
        if let Ok(catalog) = state.kickbase
            .get_json(&token, "/v4/competitions/1/players?position=0&sorting=1")
            .await
        {
            let names = competition_first_names(&catalog);
            for player in &mut squad.players {
                if player.first_name.is_none() {
                    player.first_name = names.get(&player.id)
                        .cloned()
                        .flatten()
                        .and_then(|first| sanitize_first_name(Some(first), &player.name));
                }
            }
        }
    }

    Ok(squad)
}

fn competition_first_names(payload: &Value) -> HashMap<String, Option<String>> {
    let items = payload
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| payload.as_array());
    let Some(items) = items else { return HashMap::new(); };

    items.iter().filter_map(|item| {
        let id = scalar_string(item, &["i", "pi", "id"])?;
        let display = scalar_string(item, &["n", "pn", "name"]).unwrap_or_default();
        let first = scalar_string(item, &["fn", "firstName"]);
        Some((id, sanitize_first_name(first, &display)))
    }).collect()
}

fn scalar_string(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| value.get(*key).and_then(|candidate| match candidate {
        Value::String(text) if !text.trim().is_empty() => Some(text.trim().to_string()),
        Value::Number(number) => Some(number.to_string()),
        _ => None,
    }))
}

fn sanitize_first_name(first_name: Option<String>, display_name: &str) -> Option<String> {
    let first = first_name?.trim().to_string();
    if first.is_empty() { return None; }
    let display = display_name.trim();
    if display.eq_ignore_ascii_case(&first)
        || display.to_lowercase().starts_with(&format!("{} ", first.to_lowercase()))
    {
        return None;
    }
    Some(first)
}


#[cfg(test)]
mod next_matchday_tests {
    use super::parse_next_matchday;
    use serde_json::json;

    #[test]
    fn parses_current_matchday_shape() {
        let payload = json!({
            "it": [
                {
                    "day": 1,
                    "it": [{ "mi": "old", "t1": "2", "t2": "3", "t1sy": "FCB", "t2sy": "BVB", "st": 2, "dt": "2026-08-28T18:30:00Z" }]
                },
                {
                    "day": 2,
                    "it": [{ "mi": "next", "t1": "4", "t2": "5", "t1sy": "B04", "t2sy": "RBL", "st": 0, "dt": "2026-09-11T18:30:00Z" }]
                }
            ]
        });

        let result = parse_next_matchday(&payload);
        assert_eq!(result.day_number, Some(2));
        assert_eq!(result.fixtures.len(), 1);
        assert_eq!(result.fixtures[0].home_team_id, "4");
        assert_eq!(result.fixtures[0].away_team_name, "RBL");
    }

    #[test]
    fn parses_alternative_ms_shape() {
        let payload = json!({
            "it": [{
                "day": 3,
                "ms": [{
                    "mi": "alt",
                    "t1i": "9",
                    "t2i": "11",
                    "t1n": "Frankfurt",
                    "t2n": "Freiburg",
                    "st": 0,
                    "md": "2026-09-18T18:30:00Z"
                }]
            }]
        });

        let result = parse_next_matchday(&payload);
        assert_eq!(result.day_number, Some(3));
        assert_eq!(result.fixtures[0].home_team_name, "Frankfurt");
        assert_eq!(result.fixtures[0].kickoff.as_deref(), Some("2026-09-18T18:30:00Z"));
    }
}
