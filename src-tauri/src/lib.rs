mod commands;
mod db;
mod kickbase;
mod logging;
mod mv_prediction;
mod portraits;
mod refresh;
mod state;
mod trading;

use state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    db::KickTrackDatabase::open_default().expect("failed to initialize KickTrack database");
    let app_state = AppState::new().expect("failed to initialize KickTrack application state");

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            commands::auth::login,
            commands::auth::session_status,
            commands::auth::logout,
            commands::account::account_bootstrap,
            commands::account::league_account_context,
            commands::squad::league_squad,
            commands::squad::league_next_matchday,
            commands::analytics::fair_value_reference,
            commands::analytics::fair_value_dataset,
            commands::analytics::fixture_outlook,
            commands::live::live_matchday,
            commands::league::league_overview,
            commands::league::manager_squad,
            commands::player::player_detail,
            commands::player::player_recent_forms,
            commands::player::market_value_histories,
            commands::player::player_performance_breakdown,
            commands::market::league_market,
            commands::market::market_place_offer,
            commands::market::market_withdraw_offer,
            commands::market::market_list_player,
            commands::market::market_unlist_player,
            commands::market::market_accept_offer,
            commands::market::market_decline_offer,
            commands::market::market_accept_kickbase_sell_offer,
            mv_prediction::mv_predictions,
            mv_prediction::rebuild_historical_models,
            portraits::portrait_manager_state,
            portraits::sync_missing_portraits,
            portraits::accept_portrait_candidate,
            portraits::reject_portrait_candidate,
            trading::trading_analysis,
            trading::league_purchase_price_stats,
            refresh::force_refresh_league,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
