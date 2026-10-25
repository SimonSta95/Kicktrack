use tauri::State;

use crate::{
    db::{file_data_url, KickTrackDatabase},
    kickbase::{
        error::CommandError,
        league::{merge_manager_dashboard, parse_league_managers, LeagueOverviewResponse},
        squad::{parse_squad, SquadResponse},
        validation::api_id,
    },
    portraits::sync_portraits_for_player_ids,
    state::AppState,
};

#[tauri::command]
pub async fn league_overview(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<LeagueOverviewResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let token = state.active_token().await?;

    let managers_payload = state
        .kickbase
        .get_json(
            &token,
            &format!("/v4/leagues/{league_id}/settings/managers"),
        )
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
                "[KickTrack][DEBUG][league:ranking] optional ranking fetch failed: {:?}",
                error
            );
            serde_json::Value::Null
        }
    };

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][league] manager_settings_loaded=true ranking_loaded={}",
        !ranking_payload.is_null()
    );

    let mut live = parse_league_managers(&managers_payload, &ranking_payload);

    // settings/managers and ranking are compact resources and can lag or omit
    // values. Resolve each manager dashboard before touching the DB so stored
    // snapshots are fallback-only, never the source of apparently "fresh" data.
    for manager in &mut live {
        let manager_id = match api_id(&manager.id, "Manager-ID") {
            Ok(manager_id) => manager_id,
            Err(_) => continue,
        };
        let path = format!("/v4/leagues/{league_id}/managers/{manager_id}/dashboard");

        match state.kickbase.get_json(&token, &path).await {
            Ok(payload) => {
                merge_manager_dashboard(manager, &payload);

                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][league:dashboard] manager={} loaded=true",
                    manager.id
                );
            }
            Err(error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][league:dashboard] manager={} failed={:?}",
                    manager.id,
                    error
                );
            }
        }
    }

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][league:resolved] managers={}",
        live.len()
    );

    let mut db = KickTrackDatabase::open_default()?;
    let stored = db.league_managers(&league_id)?;

    // The API is context-dependent and may omit some metrics. Preserve live
    // values, but fill missing fields from the latest stored snapshot.
    for manager in &mut live {
        if let Some(previous) = stored.iter().find(|candidate| candidate.id == manager.id) {
            if manager.name.starts_with("Manager ") {
                manager.name = previous.name.clone();
            }
            manager.profile_image_path = manager
                .profile_image_path
                .clone()
                .or_else(|| previous.profile_image_path.clone());
            manager.is_self |= previous.is_self;
            manager.team_value = manager.team_value.or(previous.team_value);
            manager.profit = manager.profit.or(previous.profit);
            manager.points = manager.points.or(previous.points);
            manager.average_points = manager.average_points.or(previous.average_points);
            manager.matchday_wins = manager.matchday_wins.or(previous.matchday_wins);
            manager.place = manager.place.or(previous.place);
        }
    }

    if live.is_empty() {
        live = stored;
    } else {
        db.upsert_league_managers(&league_id, &live)?;
    }

    live.sort_by(|a, b| {
        a.place
            .unwrap_or(i64::MAX)
            .cmp(&b.place.unwrap_or(i64::MAX))
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });

    Ok(LeagueOverviewResponse { managers: live })
}

#[tauri::command]
pub async fn manager_squad(
    league_id: String,
    manager_id: String,
    state: State<'_, AppState>,
) -> Result<SquadResponse, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let manager_id = api_id(&manager_id, "Manager-ID")?;
    let token = state.active_token().await?;
    let payload = state
        .kickbase
        .get_json(
            &token,
            &format!("/v4/leagues/{league_id}/managers/{manager_id}/squad"),
        )
        .await?;

    let mut squad = parse_squad(&payload)?;

    // Manager squads can be the first place where a newly transferred player
    // appears. Persist these live references as well, then resolve only missing
    // portraits so the league view is not tied to the historical DB snapshot.
    let portrait_ids = squad
        .players
        .iter()
        .map(|player| player.id.clone())
        .collect::<Vec<_>>();
    {
        let db = KickTrackDatabase::open_default()?;
        for player in &squad.players {
            let full_name = player.first_name.as_deref().map(|first| {
                let first = first.trim();
                if first.is_empty()
                    || player
                        .name
                        .to_lowercase()
                        .starts_with(&format!("{} ", first.to_lowercase()))
                {
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
    }

    match sync_portraits_for_player_ids(&league_id, &portrait_ids, &state).await {
        Ok(summary) =>
        {
            #[cfg(debug_assertions)]
            if summary.requested > 0 {
                crate::kt_debug!(
                    "[KickTrack][DEBUG][portrait:auto] source=manager-squad manager={} requested={} cached={} review={} failed={}",
                    manager_id, summary.requested, summary.cached, summary.review, summary.failed
                );
            }
        }
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][portrait:auto] source=manager-squad manager={} failed={:?}",
                manager_id,
                error
            );
        }
    }

    let db = KickTrackDatabase::open_default()?;

    // Manager squads use the same canonical player/asset enrichment as the
    // own squad. Existing legacy data remains read-only source material here.
    for player in &mut squad.players {
        let enrichment = db.player_enrichment(&player.id, player.team_id.as_deref())?;
        player.club_name = enrichment.club_name;
        player.portrait_data_url = enrichment.portrait_data_url;
        player.team_logo_data_url = enrichment
            .team_logo_local_path
            .as_deref()
            .and_then(file_data_url);
    }

    Ok(squad)
}
