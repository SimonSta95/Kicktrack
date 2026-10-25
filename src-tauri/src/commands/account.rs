use tauri::State;

use crate::{
    kickbase::{
        account::{
            parse_account_user, parse_league_context, parse_leagues, AccountBootstrap,
            LeagueAccountContext,
        },
        error::CommandError,
        validation::api_id,
    },
    state::AppState,
};

#[tauri::command]
pub async fn account_bootstrap(
    state: State<'_, AppState>,
) -> Result<AccountBootstrap, CommandError> {
    let token = state.active_token().await?;

    let settings = state.kickbase.get_json(&token, "/v4/user/settings").await?;
    let selection = state
        .kickbase
        .get_json(&token, "/v4/leagues/selection")
        .await?;

    Ok(AccountBootstrap {
        user: parse_account_user(&settings),
        leagues: parse_leagues(&selection)?,
    })
}

#[tauri::command]
pub async fn league_account_context(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<LeagueAccountContext, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    let token = state.active_token().await?;

    let me = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/me"))
        .await?;

    let budget = state
        .kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/me/budget"))
        .await?;

    let context = parse_league_context(league_id, &me, &budget);

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][account] context parsed budget_present={} pbaa_present={} squad={:?}/{:?}",
        context.budget.is_some(),
        context.budget_after_active_bids.is_some(),
        context.squad_size,
        context.squad_limit,
    );

    Ok(context)
}
