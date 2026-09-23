use std::collections::HashSet;

use serde::Serialize;
use serde_json::json;
use tauri::State;

use crate::{
    db::KickTrackDatabase,
    kickbase::{
        account::parse_league_context,
        error::CommandError,
        market::{parse_market, parse_visible_offers, transfer_offer_count, MarketOffer, MarketResponse},
        squad::parse_squad,
    },
    portraits::sync_portraits_for_player_ids,
    state::AppState,
};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketActionResult { pub ok: bool }

const DEFAULT_SQUAD_LIMIT: i64 = 18;
const KICKBASE_CREDIT_RATIO: f64 = 0.33;

fn current_token(state: &State<'_, AppState>) -> Result<String, CommandError> {
    let session = state.session.lock()
        .map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;
    session.as_ref().map(|session| session.token.clone()).ok_or_else(CommandError::session_expired)
}

#[tauri::command]
pub async fn league_market(
    league_id: String,
    state: State<'_, AppState>,
) -> Result<MarketResponse, CommandError> {
    if league_id.trim().is_empty() { return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich.")); }
    let token = current_token(&state)?;
    let league_id = league_id.trim();
    let payload = state.kickbase.get_json(&token, &format!("/v4/leagues/{league_id}/market")).await?;
    let mut market = parse_market(&payload)?;

    // The compact /market payload is not a reliable authority for tfhmvt.
    // In observed responses it can be missing or 0 while the canonical
    // league-player resource already carries the real 24h movement.
    //
    // Only suspicious rows are enriched, so a normal market load does not
    // fan out one request per player.
    let suspicious_ids: Vec<String> = market.entries
        .iter()
        .filter(|entry| entry.market_value_change_24h.unwrap_or(0) == 0)
        .map(|entry| entry.player_id.clone())
        .collect();

    for player_id in suspicious_ids {
        let path = format!("/v4/leagues/{league_id}/players/{player_id}");
        let detail = match state.kickbase.get_json(&token, &path).await {
            Ok(detail) => detail,
            Err(error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][market:24h-enrich] player={} detail fetch failed: {:?}",
                    player_id, error
                );
                continue;
            }
        };

        let exact_change = json_i64(&detail, &["tfhmvt", "marketValueChange24h", "dailyChange"]);
        if let Some(entry) = market.entries.iter_mut().find(|entry| entry.player_id == player_id) {
            let compact_change = entry.market_value_change_24h;
            if let Some(exact) = exact_change {
                entry.market_value_change_24h = Some(exact);

                #[cfg(debug_assertions)]
                if compact_change != Some(exact) {
                    crate::kt_debug!(
                        "[KickTrack][DEBUG][market:24h-enrich] player={} compact={:?} detail={}",
                        player_id, compact_change, exact
                    );
                }
            }
        }
    }

    // `/market` is enough for the public market table, but it is not a reliable
    // source for offers on our own listings. The dedicated live transfer state
    // is authoritative for that and is exactly what the sales drawer / budget
    // planner need. Only our currently listed squad players are enriched, so
    // this stays bounded by the (18 player) squad limit.
    let own_player_ids: HashSet<String> = match state.kickbase
        .get_json(&token, &format!("/v4/leagues/{league_id}/squad"))
        .await
        .and_then(|payload| parse_squad(&payload))
    {
        Ok(squad) => squad.players.into_iter().map(|player| player.id).collect(),
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!("[KickTrack][DEBUG][market:offers-enrich] squad fetch failed: {:?}", error);
            HashSet::new()
        }
    };

    let own_listing_ids = market.entries
        .iter()
        .filter(|entry| own_player_ids.contains(&entry.player_id))
        .map(|entry| entry.player_id.clone())
        .collect::<Vec<_>>();

    for player_id in own_listing_ids {
        let path = format!("/v4/leagues/{league_id}/players/{player_id}/transfers");
        match state.kickbase.get_json(&token, &path).await {
            Ok(transfer_state) => {
                let live_offers = parse_visible_offers(&transfer_state);
                let live_count = transfer_offer_count(&transfer_state);
                if let Some(entry) = market.entries.iter_mut().find(|entry| entry.player_id == player_id) {
                    if !live_offers.is_empty() || entry.offers.is_empty() {
                        entry.offers = live_offers;
                    }
                    // Kickbase's own direct-sale option is NOT part of `ofs[]`/`ofc`.
                    // The official app exposes it separately and sells at the current
                    // market value through POST /market/{playerId}/sell. Normalize that
                    // deterministic option into the same UI model, while keeping
                    // `offer_count` as the real manager-offer count reported by Kickbase.
                    if let Some(market_value) = entry.market_value.filter(|value| *value > 0) {
                        if !entry.offers.iter().any(|offer| offer.is_kickbase) {
                            entry.offers.push(MarketOffer {
                                id: None,
                                user_id: None,
                                user_name: Some("Kickbase".to_string()),
                                price: Some(market_value),
                                is_kickbase: true,
                            });
                        }
                    }

                    if let Some(count) = live_count {
                        entry.offer_count = Some(count);
                    } else {
                        let manager_offer_count = entry.offers.iter().filter(|offer| !offer.is_kickbase).count() as i64;
                        entry.offer_count = Some(manager_offer_count);
                    }

                    #[cfg(debug_assertions)]
                    crate::kt_debug!(
                        "[KickTrack][DEBUG][market:offers-enrich] player={} manager_count={:?} visible={} kickbase={} best={:?}",
                        player_id,
                        entry.offer_count,
                        entry.offers.len(),
                        entry.offers.iter().any(|offer| offer.is_kickbase),
                        entry.offers.iter().filter_map(|offer| offer.price).max(),
                    );
                }
            }
            Err(error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][market:offers-enrich] player={} transfers fetch failed: {:?}",
                    player_id, error
                );
            }
        }
    }

    // Register live market players before reading local enrichment. This is
    // especially important after the real transfer window: new Bundesliga
    // arrivals do not exist in an old local DB snapshot yet.
    let portrait_ids = market.entries.iter().map(|entry| entry.player_id.clone()).collect::<Vec<_>>();
    {
        let db = KickTrackDatabase::open_default()?;
        for entry in &market.entries {
            let full_name = entry.first_name.as_deref().map(|first| {
                let first = first.trim();
                if first.is_empty() || entry.name.to_lowercase().starts_with(&format!("{} ", first.to_lowercase())) {
                    entry.name.clone()
                } else {
                    format!("{first} {}", entry.name)
                }
            });
            let position = match &entry.position {
                crate::kickbase::squad::PlayerPosition::Goalkeeper => "TW",
                crate::kickbase::squad::PlayerPosition::Defender => "ABW",
                crate::kickbase::squad::PlayerPosition::Midfielder => "MF",
                crate::kickbase::squad::PlayerPosition::Forward => "ST",
                crate::kickbase::squad::PlayerPosition::Unknown => "UNKNOWN",
            };
            db.upsert_player_reference(
                &entry.player_id,
                &entry.name,
                full_name.as_deref(),
                entry.team_id.as_deref(),
                Some(position),
            )?;
        }
    }

    match sync_portraits_for_player_ids(league_id, &portrait_ids, &state).await {
        Ok(summary) => {
            #[cfg(debug_assertions)]
            if summary.requested > 0 {
                crate::kt_debug!(
                    "[KickTrack][DEBUG][portrait:auto] source=market requested={} cached={} review={} failed={}",
                    summary.requested, summary.cached, summary.review, summary.failed
                );
            }
        }
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][portrait:auto] source=market failed={:?}",
                error
            );
        }
    }

    let db = KickTrackDatabase::open_default()?;
    let managers = db.league_managers(league_id).unwrap_or_default();

    for entry in &mut market.entries {
        let enrichment = db.player_enrichment(&entry.player_id, entry.team_id.as_deref())?;
        if entry.first_name.is_none() { entry.first_name = sanitize_first_name(enrichment.first_name, &entry.name); }
        entry.club_name = enrichment.club_name;
        entry.portrait_data_url = enrichment.portrait_data_url;
        if entry.seller_name.is_none() {
            if let Some(seller_id) = entry.seller_id.as_deref() {
                entry.seller_name = managers.iter().find(|manager| manager.id == seller_id).map(|manager| manager.name.clone());
            }
        }
    }
    Ok(market)
}

#[tauri::command]
pub async fn market_place_offer(
    league_id: String,
    player_id: String,
    price: i64,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    let league_id = league_id.trim();
    let player_id = player_id.trim();
    if league_id.is_empty() || player_id.is_empty() {
        return Err(CommandError::http(400, "Liga- und Spieler-ID sind erforderlich."));
    }
    if price <= 0 {
        return Err(CommandError::http(400, "Das Gebot muss größer als 0 € sein."));
    }

    let token = current_token(&state)?;

    // Hard preflight directly before the write request. The frontend performs
    // the same calculation for immediate UX feedback, but this native guard is
    // authoritative for KickTrack and cannot be bypassed by stale UI state.
    validate_bid_preflight(&state, &token, league_id, player_id, price).await?;

    let path = format!("/v4/leagues/{league_id}/market/{player_id}/offers");
    state.kickbase
        .post_json(&token, &path, Some(json!({ "price": price })))
        .await?;
    Ok(MarketActionResult { ok: true })
}

fn json_i64(value: &serde_json::Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            serde_json::Value::Number(number) => number
                .as_i64()
                .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok()))
                .or_else(|| number.as_f64().map(|value| value.round() as i64)),
            serde_json::Value::String(text) => text
                .parse::<i64>()
                .ok()
                .or_else(|| text.parse::<f64>().ok().map(|value| value.round() as i64)),
            _ => None,
        })
    })
}

async fn validate_bid_preflight(
    state: &State<'_, AppState>,
    token: &str,
    league_id: &str,
    player_id: &str,
    price: i64,
) -> Result<(), CommandError> {
    let me = state.kickbase
        .get_json(token, &format!("/v4/leagues/{league_id}/me"))
        .await?;
    let budget = state.kickbase
        .get_json(token, &format!("/v4/leagues/{league_id}/me/budget"))
        .await?;
    let squad_payload = state.kickbase
        .get_json(token, &format!("/v4/leagues/{league_id}/squad"))
        .await?;
    let market_payload = state.kickbase
        .get_json(token, &format!("/v4/leagues/{league_id}/market"))
        .await?;

    let account = parse_league_context(league_id.to_string(), &me, &budget);
    let squad = parse_squad(&squad_payload)?;
    let market = parse_market(&market_payload)?;
    let entry = market.entries.iter()
        .find(|entry| entry.player_id == player_id)
        .ok_or_else(|| CommandError::http(409, "Der Spieler ist nicht mehr auf dem Transfermarkt."))?;

    if let Some(market_value) = entry.market_value {
        if price < market_value {
            return Err(CommandError::http(
                400,
                format!(
                    "Das Gebot muss mindestens dem aktuellen Marktwert von {} € entsprechen.",
                    market_value
                ),
            ));
        }
    }

    let squad_size = account.squad_size.unwrap_or(squad.players.len() as i64);
    let squad_limit = account.squad_limit.unwrap_or(DEFAULT_SQUAD_LIMIT);
    if squad_size >= squad_limit {
        return Err(CommandError::http(
            409,
            format!("Dein Kader ist voll ({squad_size}/{squad_limit})."),
        ));
    }

    let visible_active_bid_total: i64 = market.entries.iter()
        .filter_map(|market_entry| market_entry.own_offer)
        .map(|value| value.max(0))
        .sum();
    let balance_after_bids = account.budget_after_active_bids
        .or_else(|| account.budget.map(|budget| budget.saturating_sub(visible_active_bid_total)))
        .ok_or_else(|| {
            CommandError::invalid_response("Die aktuelle Gebotsgrenze konnte weder aus Kickbase noch aus Budget und aktiven Geboten ermittelt werden.")
        })?;
    let existing_bid = entry.own_offer.unwrap_or(0).max(0);
    let squad_value: i64 = squad.players.iter()
        .filter_map(|player| player.market_value)
        .map(|value| value.max(0))
        .sum();

    let effective_balance = balance_after_bids.saturating_add(existing_bid);
    let adjusted_squad_value = (squad_value.saturating_add(effective_balance.min(0))).max(0);
    let minimum_balance = -((adjusted_squad_value as f64 * KICKBASE_CREDIT_RATIO).floor() as i64);
    let maximum_bid = effective_balance.saturating_sub(minimum_balance).max(0);

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][bid-preflight] player={} bid={} mv={:?} squad={}/{} squad_value={} after_bids={} source={} visible_active_bids={} existing={} min_balance={} max_bid={}",
        player_id,
        price,
        entry.market_value,
        squad_size,
        squad_limit,
        squad_value,
        balance_after_bids,
        if account.budget_after_active_bids.is_some() { "api" } else { "market-fallback" },
        visible_active_bid_total,
        existing_bid,
        minimum_balance,
        maximum_bid,
    );

    if price > maximum_bid {
        return Err(CommandError::http(
            409,
            format!(
                "Das Gebot überschreitet deine aktuelle {:.0}%-Gebotsgrenze. Maximal möglich: {} €.",
                KICKBASE_CREDIT_RATIO * 100.0,
                maximum_bid
            ),
        ));
    }

    Ok(())
}

#[tauri::command]
pub async fn market_withdraw_offer(
    league_id: String,
    player_id: String,
    offer_id: String,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    if league_id.trim().is_empty() || player_id.trim().is_empty() || offer_id.trim().is_empty() {
        return Err(CommandError::http(400, "Liga-, Spieler- und Angebots-ID sind erforderlich."));
    }
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market/{}/offers/{}", league_id.trim(), player_id.trim(), offer_id.trim());
    state.kickbase.delete_json(&token, &path).await?;
    Ok(MarketActionResult { ok: true })
}

#[tauri::command]
pub async fn market_list_player(
    league_id: String,
    player_id: String,
    price: i64,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    if league_id.trim().is_empty() || player_id.trim().is_empty() {
        return Err(CommandError::http(400, "Liga- und Spieler-ID sind erforderlich."));
    }
    if price <= 0 {
        return Err(CommandError::http(400, "Der Verkaufspreis muss größer als 0 € sein."));
    }
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market", league_id.trim());
    state.kickbase.post_json(&token, &path, Some(json!({ "pi": player_id.trim(), "prc": price }))).await?;
    Ok(MarketActionResult { ok: true })
}

#[tauri::command]
pub async fn market_unlist_player(
    league_id: String,
    player_id: String,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    if league_id.trim().is_empty() || player_id.trim().is_empty() {
        return Err(CommandError::http(400, "Liga- und Spieler-ID sind erforderlich."));
    }
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market/{}", league_id.trim(), player_id.trim());
    state.kickbase.delete_json(&token, &path).await?;
    Ok(MarketActionResult { ok: true })
}

#[tauri::command]
pub async fn market_accept_offer(
    league_id: String,
    player_id: String,
    offer_id: String,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    validate_offer_action(&league_id, &player_id, &offer_id)?;
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market/{}/offers/{}/accept", league_id.trim(), player_id.trim(), offer_id.trim());
    state.kickbase.post_json(&token, &path, None).await?;
    Ok(MarketActionResult { ok: true })
}

#[tauri::command]
pub async fn market_decline_offer(
    league_id: String,
    player_id: String,
    offer_id: String,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    validate_offer_action(&league_id, &player_id, &offer_id)?;
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market/{}/offers/{}/decline", league_id.trim(), player_id.trim(), offer_id.trim());
    state.kickbase.post_json(&token, &path, None).await?;
    Ok(MarketActionResult { ok: true })
}

#[tauri::command]
pub async fn market_accept_kickbase_sell_offer(
    league_id: String,
    player_id: String,
    state: State<'_, AppState>,
) -> Result<MarketActionResult, CommandError> {
    if league_id.trim().is_empty() || player_id.trim().is_empty() {
        return Err(CommandError::http(400, "Liga- und Spieler-ID sind erforderlich."));
    }
    let token = current_token(&state)?;
    let path = format!("/v4/leagues/{}/market/{}/sell", league_id.trim(), player_id.trim());
    state.kickbase.post_json(&token, &path, None).await?;
    Ok(MarketActionResult { ok: true })
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

fn validate_offer_action(league_id: &str, player_id: &str, offer_id: &str) -> Result<(), CommandError> {
    if league_id.trim().is_empty() || player_id.trim().is_empty() || offer_id.trim().is_empty() {
        return Err(CommandError::http(400, "Liga-, Spieler- und Angebots-ID sind erforderlich."));
    }
    Ok(())
}
