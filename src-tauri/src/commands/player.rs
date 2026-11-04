use crate::{
    db::KickTrackDatabase,
    kickbase::{
        error::CommandError,
        player::{
            parse_breakdown, parse_market_value_history, parse_performance, parse_player_detail,
            PerformanceBreakdown, PerformanceEntry, PlayerDetail,
        },
        validation::api_id,
    },
    state::AppState,
};
use serde::Serialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    time::Duration,
};
use tauri::State;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketValuePoint {
    pub date: String,
    pub value: i64,
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerDetailResponse {
    pub player: PlayerDetail,
    pub market_values: Vec<MarketValuePoint>,
    pub performance: Vec<PerformanceEntry>,
    pub transfers: Vec<PlayerTransfer>,
    pub transfers_available: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerTransfer {
    pub manager_id: Option<String>,
    pub manager_name: Option<String>,
    pub date: String,
    pub price: i64,
    pub transfer_type: Option<i64>,
}

#[tauri::command]
pub async fn player_detail(
    league_id: String,
    player_id: String,
    state: State<'_, AppState>,
) -> Result<PlayerDetailResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let player_id = api_id(&player_id, "Spieler-ID")?;
    let token = state.active_token().await?;
    let detail_path = format!("/v4/leagues/{league_id}/players/{player_id}");
    let performance_path = format!("/v4/leagues/{league_id}/players/{player_id}/performance");
    let market_value_path = format!("/v4/leagues/{league_id}/players/{player_id}/marketValue/365");
    let transfer_path = format!("/v4/leagues/{league_id}/players/{player_id}/transferHistory");
    let detail_payload = state.kickbase.get_json(&token, &detail_path).await?;
    let performance_payload = state
        .kickbase
        .get_json(&token, &performance_path)
        .await
        .ok();
    let remote_market_values = match state.kickbase.get_json(&token, &market_value_path).await {
        Ok(payload) => parse_market_value_history(&payload),
        Err(_error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][player-detail] market-value history fallback player={} error={:?}",
                player_id, _error
            );
            Vec::new()
        }
    };
    let (transfers, transfers_available) = match state
        .kickbase
        .get_json(&token, &transfer_path)
        .await
    {
        Ok(payload) => (parse_player_transfers(&payload), true),
        Err(_error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][player-detail] transfer history unavailable player={} error={:?}",
                player_id,
                _error
            );
            (Vec::new(), false)
        }
    };

    let mut player = parse_player_detail(&detail_payload, &player_id)?;
    let mut db = KickTrackDatabase::open_default()?;
    let enrichment = db.player_enrichment(&player_id, player.team_id.as_deref())?;
    if player.first_name.is_none() {
        player.first_name = enrichment.first_name.clone();
    }
    if player.team_id.is_none() {
        player.team_id = enrichment.team_id.clone();
    }
    player.club_name = enrichment.club_name;
    player.portrait_data_url = enrichment.portrait_data_url;

    // Persist authoritative remote history for subsequent market-table sparklines.
    // No synthetic "today" point: the chart must only show dated observations.
    if !remote_market_values.is_empty() {
        let remote_rows = remote_market_values
            .iter()
            .map(|point| (point.date.clone(), point.value))
            .collect::<Vec<_>>();
        db.save_remote_market_value_history(&player_id, &remote_rows)?;
    }
    let local_market_values = db
        .market_value_history(&player_id)?
        .into_iter()
        .map(|(date, value)| MarketValuePoint { date, value })
        .collect::<Vec<_>>();
    let remote_market_values = remote_market_values
        .into_iter()
        .map(|entry| MarketValuePoint {
            date: entry.date,
            value: entry.value,
        })
        .collect();
    let market_values = merge_market_value_history(local_market_values, remote_market_values);

    let performance = performance_payload
        .as_ref()
        .map(parse_performance)
        .unwrap_or_default();
    Ok(PlayerDetailResponse {
        player,
        market_values,
        performance,
        transfers,
        transfers_available,
    })
}

fn parse_player_transfers(payload: &Value) -> Vec<PlayerTransfer> {
    let items = payload
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| payload.as_array())
        .cloned()
        .unwrap_or_default();
    let mut transfers = items
        .into_iter()
        .filter_map(|item| {
            let date = json_string(item.get("dt"))?;
            let price = json_i64(item.get("trp"))?;
            if date.trim().is_empty() || price <= 0 {
                return None;
            }
            Some(PlayerTransfer {
                manager_id: json_string(item.get("u")),
                manager_name: json_string(item.get("unm")),
                date,
                price,
                transfer_type: json_i64(item.get("t")),
            })
        })
        .collect::<Vec<_>>();
    transfers.sort_by(|a, b| b.date.cmp(&a.date));
    transfers
        .dedup_by(|a, b| a.manager_id == b.manager_id && a.date == b.date && a.price == b.price);
    transfers
}

fn json_string(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::String(value) => Some(value.clone()),
        Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn json_i64(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_f64().map(|number| number.round() as i64)),
        Value::String(value) => value.parse::<i64>().ok().or_else(|| {
            value
                .parse::<f64>()
                .ok()
                .map(|number| number.round() as i64)
        }),
        _ => None,
    }
}

fn merge_market_value_history(
    local: Vec<MarketValuePoint>,
    remote: Vec<MarketValuePoint>,
) -> Vec<MarketValuePoint> {
    let mut by_date = BTreeMap::<String, i64>::new();
    for point in local {
        if !point.date.trim().is_empty() && point.value > 0 {
            by_date.insert(point.date, point.value);
        }
    }
    // Kickbase's history is authoritative for overlapping dates. Local data is
    // retained outside the 365-day API window so the "Gesamt" view does not
    // lose older history.
    for point in remote {
        if !point.date.trim().is_empty() && point.value > 0 {
            by_date.insert(point.date, point.value);
        }
    }
    by_date
        .into_iter()
        .map(|(date, value)| MarketValuePoint { date, value })
        .collect()
}

#[tauri::command]
pub async fn market_value_histories(
    league_id: String,
    player_ids: Vec<String>,
    state: State<'_, AppState>,
) -> Result<HashMap<String, Vec<MarketValuePoint>>, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    if player_ids.len() > 250 {
        return Err(CommandError::http(
            400,
            "Zu viele Spieler für eine Historienabfrage.",
        ));
    }
    let player_ids = player_ids
        .into_iter()
        .map(|id| api_id(&id, "Spieler-ID"))
        .collect::<Result<HashSet<_>, _>>()?;
    let refresh_ids = {
        let db = KickTrackDatabase::open_default()?;
        let mut refresh_ids = Vec::new();
        for player_id in &player_ids {
            if db.market_value_history_needs_refresh(player_id)? {
                refresh_ids.push(player_id.clone());
            }
        }
        refresh_ids
    };
    let _refresh_requested = refresh_ids.len();
    let mut _refresh_succeeded = 0usize;

    if !refresh_ids.is_empty() {
        let token = state.active_token().await?;
        let semaphore = state.player_request_limit.clone();
        let mut tasks = tokio::task::JoinSet::new();
        for player_id in refresh_ids {
            let client = state.kickbase.clone();
            let league_id = league_id.clone();
            let token = token.clone();
            let semaphore = semaphore.clone();
            tasks.spawn(async move {
                let points = match semaphore.acquire_owned().await {
                    Ok(_permit) => {
                        let path =
                            format!("/v4/leagues/{league_id}/players/{player_id}/marketValue/365");
                        let mut attempt = 0u32;
                        loop {
                            match client.get_json(&token, &path).await {
                                Ok(payload) => break Ok(parse_market_value_history(&payload)),
                                Err(error)
                                    if attempt < 3
                                        && matches!(error.status, Some(429) | Some(500..=599)) =>
                                {
                                    attempt += 1;
                                    tokio::time::sleep(Duration::from_millis(
                                        500 * u64::from(attempt),
                                    ))
                                    .await;
                                }
                                Err(error) => break Err(error),
                            }
                        }
                    }
                    Err(_) => Err(CommandError::internal(
                        "Die Historienabfrage wurde abgebrochen.",
                    )),
                };
                (player_id, points)
            });
        }

        let mut remote = Vec::new();
        while let Some(task) = tasks.join_next().await {
            match task {
                Ok((player_id, Ok(points))) if !points.is_empty() => {
                    #[cfg(debug_assertions)]
                    crate::kt_debug!(
                        "[KickTrack][DEBUG][market-history] player={} api_points={}",
                        player_id,
                        points.len()
                    );
                    remote.push((player_id, points));
                }
                Ok((_player_id, Ok(_))) => {
                    #[cfg(debug_assertions)]
                    crate::kt_debug!(
                        "[KickTrack][DEBUG][market-history] player={} api_points=0",
                        _player_id
                    );
                }
                Ok((_player_id, Err(_error))) => {
                    #[cfg(debug_assertions)]
                    crate::kt_debug!(
                        "[KickTrack][DEBUG][market-history] player={} error={:?}",
                        _player_id,
                        _error
                    );
                }
                Err(_error) => {
                    #[cfg(debug_assertions)]
                    crate::kt_debug!("[KickTrack][DEBUG][market-history] task_error={:?}", _error);
                }
            }
        }
        if !remote.is_empty() {
            let mut db = KickTrackDatabase::open_default()?;
            for (player_id, points) in remote {
                let rows = points
                    .into_iter()
                    .map(|point| (point.date, point.value))
                    .collect::<Vec<_>>();
                db.save_remote_market_value_history(&player_id, &rows)?;
                _refresh_succeeded += 1;
            }
        }
    }

    let db = KickTrackDatabase::open_default()?;
    let mut result = HashMap::new();
    for player_id in player_ids {
        let history = db.market_value_history(&player_id)?;
        // Preserve the full recent calendar window, not 10 arbitrary snapshots.
        let skip = history.len().saturating_sub(60);
        let points = history
            .into_iter()
            .skip(skip)
            .map(|(date, value)| MarketValuePoint { date, value })
            .collect();
        result.insert(player_id, points);
    }
    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][market-history] players={} refresh_requested={} refresh_succeeded={}",
        result.len(),
        _refresh_requested,
        _refresh_succeeded
    );
    Ok(result)
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecentFormsResponse {
    pub forms: HashMap<String, Vec<PerformanceEntry>>,
    pub unavailable_player_ids: Vec<String>,
}

#[tauri::command]
pub async fn player_recent_forms(
    league_id: String,
    player_ids: Vec<String>,
    state: State<'_, AppState>,
) -> Result<RecentFormsResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    if player_ids.len() > 250 {
        return Err(CommandError::http(
            400,
            "Zu viele Spieler für eine Formabfrage.",
        ));
    }
    let player_ids = player_ids
        .into_iter()
        .map(|id| api_id(&id, "Spieler-ID"))
        .collect::<Result<HashSet<_>, _>>()?;
    let token = state.active_token().await?;
    let semaphore = state.player_request_limit.clone();
    let mut tasks = tokio::task::JoinSet::new();
    for player_id in player_ids {
        let client = state.kickbase.clone();
        let token = token.clone();
        let league_id = league_id.clone();
        let semaphore = semaphore.clone();
        tasks.spawn(async move {
            let entries = match semaphore.acquire_owned().await {
                Ok(_permit) => {
                    let path = format!("/v4/leagues/{league_id}/players/{player_id}/performance");
                    let mut attempt = 0u32;
                    loop {
                        match client.get_json(&token, &path).await {
                            Ok(payload) => break Ok(parse_performance(&payload)),
                            Err(error)
                                if attempt < 2
                                    && matches!(error.status, Some(429) | Some(500..=599)) =>
                            {
                                attempt += 1;
                                tokio::time::sleep(Duration::from_millis(500 * u64::from(attempt)))
                                    .await;
                            }
                            Err(error) => break Err(error),
                        }
                    }
                }
                Err(_) => Err(CommandError::internal("Die Formabfrage wurde abgebrochen.")),
            };
            (player_id, entries)
        });
    }
    let mut forms = HashMap::new();
    let mut unavailable_player_ids = Vec::new();
    while let Some(result) = tasks.join_next().await {
        match result {
            Ok((player_id, Ok(entries))) => {
                forms.insert(player_id, entries);
            }
            Ok((player_id, Err(_))) => {
                unavailable_player_ids.push(player_id);
            }
            Err(_) => {}
        }
    }
    // Missing keys explicitly describe partial results without failing all rows.
    // Preserve deterministic ordering for the frontend and diagnostics.
    unavailable_player_ids.sort();
    Ok(RecentFormsResponse {
        forms,
        unavailable_player_ids,
    })
}

#[tauri::command]
pub async fn player_performance_breakdown(
    league_id: String,
    player_id: String,
    day_number: i64,
    state: State<'_, AppState>,
) -> Result<PerformanceBreakdown, CommandError> {
    if !(1..=40).contains(&day_number) {
        return Err(CommandError::http(400, "Ungültiger Spieltag."));
    }
    let league_id = api_id(&league_id, "Liga-ID")?;
    let player_id = api_id(&player_id, "Spieler-ID")?;
    let token = state.active_token().await?;
    // Keep the total shown in the breakdown anchored to the same current-season
    // performance entry that produced the selected bar. playercenter contains
    // nested point subtotals which are not safe to use as the match total.
    let performance_payload = state
        .kickbase
        .get_json(
            &token,
            &format!("/v4/leagues/{league_id}/players/{player_id}/performance"),
        )
        .await
        .ok();
    let expected_total = performance_payload
        .as_ref()
        .map(parse_performance)
        .and_then(|entries| {
            entries
                .into_iter()
                .find(|entry| entry.day_number == day_number)
        })
        .and_then(|entry| entry.points);

    let payload=state.kickbase.get_json(&token,&format!("/v4/competitions/1/playercenter/{player_id}?leagueId={league_id}&dayNumber={day_number}")).await?;
    let eventtypes = state
        .kickbase
        .get_json(&token, "/v4/live/eventtypes")
        .await
        .unwrap_or(serde_json::Value::Null);
    Ok(parse_breakdown(
        &payload,
        &eventtypes,
        day_number,
        expected_total,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remote_market_value_history_fills_local_gaps() {
        let local = vec![
            MarketValuePoint {
                date: "2026-08-29".to_owned(),
                value: 14_329_446,
            },
            MarketValuePoint {
                date: "2026-09-17".to_owned(),
                value: 17_089_548,
            },
        ];
        let remote = vec![
            MarketValuePoint {
                date: "2026-09-16".to_owned(),
                value: 17_400_000,
            },
            MarketValuePoint {
                date: "2026-09-17".to_owned(),
                value: 17_000_000,
            },
            MarketValuePoint {
                date: "2026-09-18".to_owned(),
                value: 16_700_000,
            },
        ];

        assert_eq!(
            merge_market_value_history(local, remote),
            vec![
                MarketValuePoint {
                    date: "2026-08-29".to_owned(),
                    value: 14_329_446
                },
                MarketValuePoint {
                    date: "2026-09-16".to_owned(),
                    value: 17_400_000
                },
                MarketValuePoint {
                    date: "2026-09-17".to_owned(),
                    value: 17_000_000
                },
                MarketValuePoint {
                    date: "2026-09-18".to_owned(),
                    value: 16_700_000
                },
            ]
        );
    }

    #[test]
    fn player_transfer_history_filters_invalid_rows_and_sorts_newest_first() {
        let payload = serde_json::json!({
            "it": [
                { "u": "manager-1", "unm": "Anna", "dt": "2026-09-01T20:00:00Z", "trp": 12_500_000, "t": 2 },
                { "u": 42, "unm": "Ben", "dt": "2026-10-02T20:00:00Z", "trp": 14_000_000.0, "t": "2" },
                { "u": "manager-3", "dt": "", "trp": 15_000_000 },
                { "u": "manager-4", "dt": "2026-10-03T20:00:00Z", "trp": 0 }
            ]
        });

        assert_eq!(
            parse_player_transfers(&payload),
            vec![
                PlayerTransfer {
                    manager_id: Some("42".to_owned()),
                    manager_name: Some("Ben".to_owned()),
                    date: "2026-10-02T20:00:00Z".to_owned(),
                    price: 14_000_000,
                    transfer_type: Some(2),
                },
                PlayerTransfer {
                    manager_id: Some("manager-1".to_owned()),
                    manager_name: Some("Anna".to_owned()),
                    date: "2026-09-01T20:00:00Z".to_owned(),
                    price: 12_500_000,
                    transfer_type: Some(2),
                },
            ]
        );
    }
}
