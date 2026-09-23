use std::collections::{BTreeMap, HashMap};
use serde::Serialize;
use tauri::State;
use crate::{db::KickTrackDatabase, kickbase::{error::CommandError, player::{parse_breakdown, parse_market_value_history, parse_performance, parse_player_detail, PerformanceBreakdown, PerformanceEntry, PlayerDetail}}, state::AppState};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all="camelCase")]
pub struct MarketValuePoint { pub date:String, pub value:i64 }
#[derive(Debug, Serialize)]
#[serde(rename_all="camelCase")]
pub struct PlayerDetailResponse { pub player:PlayerDetail, pub market_values:Vec<MarketValuePoint>, pub performance:Vec<PerformanceEntry> }

fn token(state:&State<'_,AppState>)->Result<String,CommandError>{let session=state.session.lock().map_err(|_|CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;session.as_ref().map(|s|s.token.clone()).ok_or_else(CommandError::session_expired)}

#[tauri::command]
pub async fn player_detail(league_id:String,player_id:String,state:State<'_,AppState>)->Result<PlayerDetailResponse,CommandError>{
    let token=token(&state)?; let league_id=league_id.trim(); let player_id=player_id.trim();
    if league_id.is_empty()||player_id.is_empty(){return Err(CommandError::http(400,"Liga- und Spieler-ID sind erforderlich."));}
    let detail_payload=state.kickbase.get_json(&token,&format!("/v4/leagues/{league_id}/players/{player_id}")).await?;
    let performance_payload=state.kickbase.get_json(&token,&format!("/v4/leagues/{league_id}/players/{player_id}/performance")).await.ok();
    let remote_market_values = match state.kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/players/{player_id}/marketValue/365"))
        .await
    {
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

    let mut player=parse_player_detail(&detail_payload,player_id)?;
    let db=KickTrackDatabase::open_default()?;
    let enrichment=db.player_enrichment(player_id,player.team_id.as_deref())?;
    if player.first_name.is_none() { player.first_name = enrichment.first_name.clone(); }
    if player.team_id.is_none() { player.team_id = enrichment.team_id.clone(); }
    player.club_name=enrichment.club_name; player.portrait_data_url=enrichment.portrait_data_url;

    let local_market_values = db.market_value_history(player_id)?
        .into_iter()
        .map(|(date,value)| MarketValuePoint{date,value})
        .collect::<Vec<_>>();
    let remote_market_values = remote_market_values
        .into_iter()
        .map(|entry| MarketValuePoint { date: entry.date, value: entry.value })
        .collect();
    let market_values = merge_market_value_history(local_market_values, remote_market_values);

    let performance=performance_payload.as_ref().map(parse_performance).unwrap_or_default();
    Ok(PlayerDetailResponse{player,market_values,performance})
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
pub async fn market_value_histories(player_ids:Vec<String>)->Result<HashMap<String,Vec<MarketValuePoint>>,CommandError>{
    if player_ids.len()>250{return Err(CommandError::http(400,"Zu viele Spieler für eine Historienabfrage."));}
    let db=KickTrackDatabase::open_default()?;
    let mut result=HashMap::new();
    for raw_id in player_ids {
        let player_id=raw_id.trim();
        if player_id.is_empty(){continue;}
        let history=db.market_value_history(player_id)?;
        let skip=history.len().saturating_sub(10);
        let points=history.into_iter().skip(skip).map(|(date,value)|MarketValuePoint{date,value}).collect();
        result.insert(player_id.to_owned(),points);
    }
    Ok(result)
}

#[tauri::command]
pub async fn player_performance_breakdown(league_id:String,player_id:String,day_number:i64,state:State<'_,AppState>)->Result<PerformanceBreakdown,CommandError>{
    let token=token(&state)?; if !(1..=40).contains(&day_number){return Err(CommandError::http(400,"Ungültiger Spieltag."));}
    // Keep the total shown in the breakdown anchored to the same current-season
    // performance entry that produced the selected bar. playercenter contains
    // nested point subtotals which are not safe to use as the match total.
    let performance_payload = state.kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/players/{player_id}/performance"))
        .await
        .ok();
    let expected_total = performance_payload
        .as_ref()
        .map(parse_performance)
        .and_then(|entries| entries.into_iter().find(|entry| entry.day_number == day_number))
        .and_then(|entry| entry.points);

    let payload=state.kickbase.get_json(&token,&format!("/v4/competitions/1/playercenter/{player_id}?leagueId={league_id}&dayNumber={day_number}")).await?;
    let eventtypes=state.kickbase.get_json(&token,"/v4/live/eventtypes").await.unwrap_or(serde_json::Value::Null);
    Ok(parse_breakdown(&payload,&eventtypes,day_number,expected_total))
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remote_market_value_history_fills_local_gaps() {
        let local = vec![
            MarketValuePoint { date: "2026-08-29".to_owned(), value: 14_329_446 },
            MarketValuePoint { date: "2026-09-17".to_owned(), value: 17_089_548 },
        ];
        let remote = vec![
            MarketValuePoint { date: "2026-09-16".to_owned(), value: 17_400_000 },
            MarketValuePoint { date: "2026-09-17".to_owned(), value: 17_000_000 },
            MarketValuePoint { date: "2026-09-18".to_owned(), value: 16_700_000 },
        ];

        assert_eq!(
            merge_market_value_history(local, remote),
            vec![
                MarketValuePoint { date: "2026-08-29".to_owned(), value: 14_329_446 },
                MarketValuePoint { date: "2026-09-16".to_owned(), value: 17_400_000 },
                MarketValuePoint { date: "2026-09-17".to_owned(), value: 17_000_000 },
                MarketValuePoint { date: "2026-09-18".to_owned(), value: 16_700_000 },
            ]
        );
    }
}
