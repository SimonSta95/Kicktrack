use serde::Serialize;
use tauri::State;

use crate::{
    db::KickTrackDatabase,
    kickbase::{
        account::parse_league_context,
        error::CommandError,
        league::{merge_manager_dashboard, parse_league_managers},
        market::parse_market,
        squad::parse_squad,
    },
    state::AppState,
};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ForceRefreshResult {
    pub refreshed_at: String,
    pub squad_players: usize,
    pub market_players: usize,
    pub managers: usize,
    pub market_value_snapshots: usize,
}

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

#[tauri::command]
pub async fn force_refresh_league(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<ForceRefreshResult, CommandError> {
    let league_id = league_id.trim().to_owned();
    if league_id.is_empty() {
        return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich."));
    }

    let token = current_token(&state)?;

    // Important: perform all network awaits before opening SQLite. rusqlite's
    // Connection is intentionally not held across .await boundaries.
    let me = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/me"))
        .await?;
    let budget = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/me/budget"))
        .await?;
    let squad_payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/squad"))
        .await?;
    let market_payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/market"))
        .await?;
    let managers_payload = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/settings/managers"))
        .await?;
    let ranking_payload = match state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/ranking"))
        .await
    {
        Ok(payload) => payload,
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][force-refresh:ranking] optional fetch failed: {:?}",
                error
            );
            serde_json::Value::Null
        }
    };

    // Lineup is a cache-warming side request and is not persisted yet. A
    // failure must not abort an otherwise successful refresh, but it is handled
    // explicitly so it cannot disappear unnoticed during development.
    if let Err(error) = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/lineup"))
        .await
    {
        #[cfg(debug_assertions)]
        crate::kt_debug!(
            "[KickTrack][DEBUG][force-refresh:lineup] optional fetch failed: {:?}",
            error
        );
    }

    let account = parse_league_context(league_id.clone(), &me, &budget);
    let squad = parse_squad(&squad_payload)?;
    let market = parse_market(&market_payload)?;
    let mut managers = parse_league_managers(&managers_payload, &ranking_payload);

    // Keep the persisted league snapshot aligned with the same specific
    // manager resource used by the League page.
    for manager in &mut managers {
        let path = format!(
            "/v4/leagues/{league_id}/managers/{}/dashboard",
            manager.id
        );
        match state.kickbase.get_json(&token, &path).await {
            Ok(payload) => {
                merge_manager_dashboard(manager, &payload);

                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][force-refresh:manager] id={} place={:?} points={:?} tv={:?} profit={:?}",
                    manager.id,
                    manager.place,
                    manager.points,
                    manager.team_value,
                    manager.profit,
                );
            }
            Err(error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][force-refresh:manager] id={} failed={:?}",
                    manager.id, error
                );
            }
        }
    }

    let mut snapshots: Vec<(String, i64)> = Vec::new();
    for player in &squad.players {
        if let Some(value) = player.market_value.filter(|value| *value > 0) {
            snapshots.push((player.id.clone(), value));
        }
    }
    for entry in &market.entries {
        if let Some(value) = entry.market_value.filter(|value| *value > 0) {
            if !snapshots.iter().any(|(player_id, _)| player_id == &entry.player_id) {
                snapshots.push((entry.player_id.clone(), value));
            }
        }
    }

    let squad_value: i64 = squad
        .players
        .iter()
        .filter_map(|player| player.market_value)
        .filter(|value| *value > 0)
        .sum();

    let mut db = KickTrackDatabase::open_default()?;
    let snapshot_count = db.record_force_refresh_market_values(&snapshots)?;
    db.record_force_refresh_dashboard(
        &league_id,
        squad_value,
        account.budget,
    )?;
    if !managers.is_empty() {
        db.upsert_league_managers(&league_id, &managers)?;
    }

    let refreshed_at = chrono_like_now();

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][force-refresh] league={} squad={} market={} managers={} snapshots={} budget={:?} pbaa={:?}",
        league_id,
        squad.players.len(),
        market.entries.len(),
        managers.len(),
        snapshot_count,
        account.budget,
        account.budget_after_active_bids,
    );

    Ok(ForceRefreshResult {
        refreshed_at,
        squad_players: squad.players.len(),
        market_players: market.entries.len(),
        managers: managers.len(),
        market_value_snapshots: snapshot_count,
    })
}

// Avoid a new chrono dependency just for a display timestamp.
fn chrono_like_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    seconds.to_string()
}
