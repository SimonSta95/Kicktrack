use std::collections::{HashMap, VecDeque};

use serde::Serialize;
use serde_json::Value;
use tauri::State;

use crate::{db::{KickTrackDatabase, TransferEventRow}, kickbase::error::CommandError, state::AppState};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TradingSummary {
    pub closed_trades: usize,
    pub open_trades: usize,
    pub realized_pnl: i64,
    pub average_roi_pct: Option<f64>,
    pub timed_sales: usize,
    pub good_exits: usize,
    pub early_exits: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TradeCycle {
    pub cycle_type: String,
    pub player_id: String,
    pub player_name: String,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub buy_date: Option<String>,
    pub sell_date: Option<String>,
    pub buy_price: Option<i64>,
    pub sell_price: Option<i64>,
    pub current_market_value: Option<i64>,
    pub market_value_at_sale: Option<i64>,
    pub pnl: Option<i64>,
    pub roi_pct: Option<f64>,
    pub holding_days: Option<i64>,
    pub post_3d_pct: Option<f64>,
    pub post_7d_pct: Option<f64>,
    pub exit_verdict: String,
    pub verdict: String,
    pub sort_date: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TradingAnalysisResponse {
    pub summary: TradingSummary,
    pub trades: Vec<TradeCycle>,
}

#[tauri::command]
pub async fn trading_analysis(league_id: String, state: State<'_, AppState>) -> Result<TradingAnalysisResponse, CommandError> {
    let league_id = league_id.trim();
    if league_id.is_empty() { return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich.")); }
    let manager_id = {
        let db = KickTrackDatabase::open_default()?;
        db.self_manager_id(league_id)?.ok_or_else(|| CommandError::internal("Der eigene Manager konnte für die Transferanalyse nicht bestimmt werden."))?
    };

    // Never keep rusqlite across an await. Fetch first, then reopen SQLite for
    // the short persistence/analysis phase.
    let live_events = match current_token(&state) {
        Ok(token) => match fetch_manager_transfers(&state, &token, league_id, &manager_id).await {
            Ok(events) => Some(events),
            Err(error) => {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][trading] live transfer fetch failed; using cached events: {:?}",
                    error
                );
                None
            }
        },
        Err(error) => {
            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][trading] session unavailable; using cached events: {:?}",
                error
            );
            None
        }
    };
    let mut db = KickTrackDatabase::open_default()?;
    if let Some(live_events) = live_events.as_ref() {
        db.upsert_transfer_events(live_events, "kickbase_api")?;
    }
    let events = db.transfer_events(league_id, &manager_id)?;
    let trades = build_cycles(&db, events)?;
    let summary = summarize(&trades);

    #[cfg(debug_assertions)]
    crate::kt_debug!("[KickTrack][DEBUG][trading] league={} manager={} closed={} open={} pnl={}", league_id, manager_id, summary.closed_trades, summary.open_trades, summary.realized_pnl);

    Ok(TradingAnalysisResponse { summary, trades })
}

fn current_token(state: &State<'_, AppState>) -> Result<String, CommandError> {
    let session = state.session.lock().map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;
    session.as_ref().map(|session| session.token.clone()).ok_or_else(CommandError::session_expired)
}

async fn fetch_manager_transfers(state: &State<'_, AppState>, token: &str, league_id: &str, manager_id: &str) -> Result<Vec<TransferEventRow>, CommandError> {
    let mut all = Vec::new(); let mut seen = std::collections::HashSet::new(); let mut start = 0usize;
    for _ in 0..8 {
        let suffix = if start == 0 { String::new() } else { format!("?start={start}") };
        let payload = state.kickbase.get_json(token, &format!("/v4/leagues/{league_id}/managers/{manager_id}/transfer{suffix}")).await?;
        let items = items(&payload); if items.is_empty() { break; }
        let mut new_count = 0;
        for item in &items {
            let transfer_type = int_value(item.get("tty")).unwrap_or(0); if transfer_type != 1 && transfer_type != 2 { continue; }
            let player_id = string_value(item.get("pi")).unwrap_or_default(); let price = int_value(item.get("trp")).unwrap_or(0); let date = string_value(item.get("dt")).unwrap_or_default();
            if player_id.is_empty() || date.is_empty() || price <= 0 { continue; }
            let key = format!("{player_id}|{transfer_type}|{price}|{date}"); if !seen.insert(key) { continue; }
            new_count += 1;
            all.push(TransferEventRow { league_id: league_id.to_string(), manager_id: manager_id.to_string(), player_id,
                player_name: string_value(item.get("pn")).unwrap_or_else(|| "Unbekannt".into()), team_id: string_value(item.get("tid")), club_name: None,
                transfer_type: if transfer_type == 1 { "BUY".into() } else { "SELL".into() }, price, transferred_at: date });
        }
        if new_count == 0 || items.len() < 20 { break; } start += items.len();
    }
    Ok(all)
}
fn items(payload: &Value) -> Vec<Value> { if let Some(items)=payload.get("it").and_then(Value::as_array){return items.clone()} if let Some(items)=payload.as_array(){return items.clone()} Vec::new() }
fn string_value(value: Option<&Value>) -> Option<String> { match value? { Value::String(v)=>Some(v.clone()), Value::Number(v)=>Some(v.to_string()), _=>None } }
fn int_value(value: Option<&Value>) -> Option<i64> { match value? { Value::Number(v)=>v.as_i64().or_else(||v.as_f64().map(|n|n.round() as i64)), Value::String(v)=>v.parse::<i64>().ok().or_else(||v.parse::<f64>().ok().map(|n|n.round() as i64)), _=>None } }

fn build_cycles(db: &KickTrackDatabase, events: Vec<TransferEventRow>) -> Result<Vec<TradeCycle>, CommandError> {
    let mut grouped: HashMap<String, Vec<TransferEventRow>> = HashMap::new();
    for event in events { grouped.entry(event.player_id.clone()).or_default().push(event); }
    let mut cycles = Vec::new();

    for (player_id, mut player_events) in grouped {
        player_events.sort_by(|a,b| a.transferred_at.cmp(&b.transferred_at));
        let mut buys: VecDeque<TransferEventRow> = VecDeque::new();
        let first_is_sell = player_events.first().map(|event| event.transfer_type.eq_ignore_ascii_case("SELL")).unwrap_or(false);

        for event in &player_events {
            if event.transfer_type.eq_ignore_ascii_case("BUY") { buys.push_back(event.clone()); continue; }
            if !event.transfer_type.eq_ignore_ascii_case("SELL") { continue; }

            let market_value_at_sale = db.market_value_on_or_before(&player_id, &event.transferred_at)?;
            let timing_base = market_value_at_sale.or(Some(event.price));
            let post_3d = db.post_sale_market_value(&player_id, &event.transferred_at, 3)?;
            let post_7d = db.post_sale_market_value(&player_id, &event.transferred_at, 7)?;
            let post_3d_pct = pct(post_3d.zip(timing_base).map(|(value,base)| value-base), timing_base);
            let post_7d_pct = pct(post_7d.zip(timing_base).map(|(value,base)| value-base), timing_base);
            let exit_verdict = exit_verdict(post_7d_pct, post_3d_pct).to_string();

            if let Some(buy) = buys.pop_front() {
                let pnl = event.price - buy.price;
                let roi = pct(Some(pnl), Some(buy.price));
                let holding_days = db.days_between(&buy.transferred_at, Some(&event.transferred_at))?;
                cycles.push(TradeCycle {
                    cycle_type: "CLOSED_TRADE".into(), player_id: player_id.clone(), player_name: event.player_name.clone(),
                    team_id: event.team_id.clone().or(buy.team_id.clone()), club_name: event.club_name.clone().or(buy.club_name.clone()),
                    buy_date: Some(buy.transferred_at.clone()), sell_date: Some(event.transferred_at.clone()), buy_price: Some(buy.price), sell_price: Some(event.price),
                    current_market_value: db.latest_market_value(&player_id)?.map(|(_,value)| value), market_value_at_sale,
                    pnl: Some(pnl), roi_pct: roi, holding_days, post_3d_pct, post_7d_pct,
                    exit_verdict: exit_verdict.clone(), verdict: trade_verdict(roi, &exit_verdict).into(), sort_date: event.transferred_at.clone(),
                });
            } else if first_is_sell {
                // Same reconstruction principle as the Python app: a first observed SELL plus
                // older persisted MW history is strong evidence for start inventory. We never
                // invent a purchase price if no such evidence exists.
                if let Some((start_date, start_value)) = db.earliest_market_value_on_or_before(&player_id, &event.transferred_at)? {
                    let pnl = event.price - start_value;
                    let roi = pct(Some(pnl), Some(start_value));
                    let holding_days = db.days_between(&start_date, Some(&event.transferred_at))?;
                    cycles.push(TradeCycle {
                        cycle_type: "CLOSED_START_SQUAD_TRADE".into(), player_id: player_id.clone(), player_name: event.player_name.clone(),
                        team_id: event.team_id.clone(), club_name: event.club_name.clone(), buy_date: Some(start_date), sell_date: Some(event.transferred_at.clone()),
                        buy_price: Some(start_value), sell_price: Some(event.price), current_market_value: db.latest_market_value(&player_id)?.map(|(_,value)| value), market_value_at_sale,
                        pnl: Some(pnl), roi_pct: roi, holding_days, post_3d_pct, post_7d_pct,
                        exit_verdict: exit_verdict.clone(), verdict: trade_verdict(roi, &exit_verdict).into(), sort_date: event.transferred_at.clone(),
                    });
                } else {
                    cycles.push(unpaired_sale(event, market_value_at_sale, post_3d_pct, post_7d_pct, exit_verdict));
                }
            } else {
                cycles.push(unpaired_sale(event, market_value_at_sale, post_3d_pct, post_7d_pct, exit_verdict));
            }
        }

        for buy in buys {
            let latest = db.latest_market_value(&player_id)?;
            let current_value = latest.as_ref().map(|(_,value)| *value);
            let pnl = current_value.map(|value| value - buy.price);
            let roi = pct(pnl, Some(buy.price));
            cycles.push(TradeCycle {
                cycle_type: "OPEN_TRADE".into(), player_id: player_id.clone(), player_name: buy.player_name.clone(), team_id: buy.team_id.clone(), club_name: buy.club_name.clone(),
                buy_date: Some(buy.transferred_at.clone()), sell_date: None, buy_price: Some(buy.price), sell_price: None,
                current_market_value: current_value, market_value_at_sale: None, pnl, roi_pct: roi,
                holding_days: db.days_between(&buy.transferred_at, None)?, post_3d_pct: None, post_7d_pct: None,
                exit_verdict: "–".into(), verdict: live_verdict(roi).into(), sort_date: buy.transferred_at.clone(),
            });
        }
    }

    cycles.sort_by(|a,b| b.sort_date.cmp(&a.sort_date));
    Ok(cycles)
}

fn unpaired_sale(event: &TransferEventRow, market_value_at_sale: Option<i64>, post_3d_pct: Option<f64>, post_7d_pct: Option<f64>, exit_verdict: String) -> TradeCycle {
    TradeCycle {
        cycle_type: "UNPAIRED_SALE".into(), player_id: event.player_id.clone(), player_name: event.player_name.clone(), team_id: event.team_id.clone(), club_name: event.club_name.clone(),
        buy_date: None, sell_date: Some(event.transferred_at.clone()), buy_price: None, sell_price: Some(event.price), current_market_value: None, market_value_at_sale,
        pnl: None, roi_pct: None, holding_days: None, post_3d_pct, post_7d_pct, exit_verdict: exit_verdict.clone(), verdict: exit_verdict, sort_date: event.transferred_at.clone(),
    }
}

fn pct(delta: Option<i64>, base: Option<i64>) -> Option<f64> { match (delta,base) { (Some(delta),Some(base)) if base > 0 => Some(delta as f64 / base as f64 * 100.0), _ => None } }
fn exit_verdict(post_7: Option<f64>, post_3: Option<f64>) -> &'static str {
    let value = post_7.or(post_3); match value {
        None => "EXIT NOCH OFFEN", Some(value) if value <= -8.0 => "TOP-EXIT", Some(value) if value <= -2.5 => "GUTES TIMING",
        Some(value) if value >= 10.0 => "DEUTLICH ZU FRÜH", Some(value) if value >= 3.0 => "ZU FRÜH", _ => "SOLIDES TIMING",
    }
}
fn trade_verdict(roi: Option<f64>, exit: &str) -> &'static str { match roi { Some(v) if v >= 10.0 && (exit=="TOP-EXIT"||exit=="GUTES TIMING") => "TOP-TRADE", Some(v) if v >= 10.0 => "STARKER TRADE", Some(v) if v >= 3.0 => "GUTER TRADE", Some(v) if v <= -10.0 => "VERLUST-TRADE", Some(v) if v <= -3.0 => "SCHWACHER TRADE", _ => "SOLIDER TRADE" } }
fn live_verdict(roi: Option<f64>) -> &'static str { match roi { Some(v) if v >= 10.0 => "LIVE · FINANZIELL STARK", Some(v) if v <= -10.0 => "LIVE · FINANZIELL SCHWACH", _ => "LIVE · OFFEN" } }

fn summarize(trades: &[TradeCycle]) -> TradingSummary {
    let closed: Vec<_> = trades.iter().filter(|trade| matches!(trade.cycle_type.as_str(), "CLOSED_TRADE"|"CLOSED_START_SQUAD_TRADE")).collect();
    let open = trades.iter().filter(|trade| trade.cycle_type == "OPEN_TRADE").count();
    let realized_pnl = closed.iter().filter_map(|trade| trade.pnl).sum();
    let rois: Vec<f64> = closed.iter().filter_map(|trade| trade.roi_pct).collect();
    let average_roi_pct = if rois.is_empty() { None } else { Some(rois.iter().sum::<f64>() / rois.len() as f64) };
    let timed: Vec<_> = trades.iter().filter(|trade| trade.sell_date.is_some() && (trade.post_7d_pct.is_some() || trade.post_3d_pct.is_some())).collect();
    let good_exits = timed.iter().filter(|trade| matches!(trade.exit_verdict.as_str(), "TOP-EXIT"|"GUTES TIMING")).count();
    let early_exits = timed.iter().filter(|trade| matches!(trade.exit_verdict.as_str(), "ZU FRÜH"|"DEUTLICH ZU FRÜH")).count();
    TradingSummary { closed_trades: closed.len(), open_trades: open, realized_pnl, average_roi_pct, timed_sales: timed.len(), good_exits, early_exits }
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LeaguePricePlayerInput {
    pub player_id: String,
    pub market_value: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeaguePurchaseExample {
    pub player_id: String,
    pub player_name: String,
    pub transferred_at: String,
    pub market_value: i64,
    pub price: i64,
    pub premium_pct: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeaguePurchasePriceStat {
    pub player_id: String,
    pub sample_count: usize,
    pub segment_sample_count: usize,
    pub used_segment: bool,
    pub median_premium_pct: Option<f64>,
    pub average_premium_pct: Option<f64>,
    pub p25_premium_pct: Option<f64>,
    pub p75_premium_pct: Option<f64>,
    pub typical_price: Option<i64>,
    pub typical_price_low: Option<i64>,
    pub typical_price_high: Option<i64>,
    pub examples: Vec<LeaguePurchaseExample>,
}

#[derive(Debug, Clone)]
struct PurchaseSample {
    player_id: String,
    player_name: String,
    transferred_at: String,
    market_value: i64,
    price: i64,
    premium_pct: f64,
    weight: f64,
}

#[tauri::command]
pub fn league_purchase_price_stats(
    league_id: String,
    players: Vec<LeaguePricePlayerInput>,
) -> Result<Vec<LeaguePurchasePriceStat>, CommandError> {
    let league_id = league_id.trim();
    if league_id.is_empty() {
        return Err(CommandError::http(400, "Eine Liga-ID ist erforderlich."));
    }

    let db = KickTrackDatabase::open_default()?;
    let own_manager_id = db.self_manager_id(league_id)?;
    let events = db.league_buy_events(league_id)?;
    let mut samples = Vec::new();

    for event in events {
        if own_manager_id.as_deref() == Some(event.manager_id.as_str()) { continue; }
        let Some(market_value) = db.market_value_on_or_before(&event.player_id, &event.transferred_at)? else { continue; };
        if market_value <= 0 || event.price <= 0 { continue; }
        let premium_pct = (event.price as f64 / market_value as f64 - 1.0) * 100.0;
        // Only discard obviously corrupt/mismatched historical rows. Negative premiums
        // remain valid historical evidence; this is not a "must be above MW" assumption.
        if !(-50.0..=200.0).contains(&premium_pct) { continue; }
        let age_days = db.days_between(&event.transferred_at, None)?.unwrap_or(9999).max(0);
        let weight = recency_weight(age_days);
        samples.push(PurchaseSample {
            player_id: event.player_id,
            player_name: event.player_name,
            transferred_at: event.transferred_at,
            market_value,
            price: event.price,
            premium_pct,
            weight,
        });
    }

    samples.sort_by(|a,b| b.transferred_at.cmp(&a.transferred_at));

    let mut result = Vec::with_capacity(players.len());
    for input in players {
        let current_market_value = input.market_value.filter(|value| *value > 0);
        let segment: Vec<&PurchaseSample> = match current_market_value {
            Some(value) => {
                let bucket = market_value_bucket(value);
                samples.iter().filter(|sample| market_value_bucket(sample.market_value) == bucket).collect()
            }
            None => Vec::new(),
        };
        let used_segment = segment.len() >= 5;
        let selected: Vec<&PurchaseSample> = if used_segment { segment.clone() } else { samples.iter().collect() };
        let mut weighted: Vec<(f64,f64)> = selected.iter().map(|sample| (sample.premium_pct, sample.weight)).collect();
        weighted.sort_by(|a,b| a.0.total_cmp(&b.0));
        let median = weighted_quantile(&weighted, 0.50);
        let weight_sum = weighted.iter().map(|(_,w)| *w).sum::<f64>();
        let average = if weight_sum <= 0.0 { None } else { Some(weighted.iter().map(|(v,w)| v*w).sum::<f64>() / weight_sum) };
        let p25 = weighted_quantile(&weighted, 0.25);
        let p75 = weighted_quantile(&weighted, 0.75);
        let typical_price = current_market_value.zip(median).map(|(value, premium)| {
            ((value as f64) * (1.0 + premium / 100.0)).round() as i64
        });
        let typical_price_low = current_market_value.zip(p25).map(|(value, premium)| {
            ((value as f64) * (1.0 + premium / 100.0)).round() as i64
        });
        let typical_price_high = current_market_value.zip(p75).map(|(value, premium)| {
            ((value as f64) * (1.0 + premium / 100.0)).round() as i64
        });
        let examples = selected.iter().take(5).map(|sample| LeaguePurchaseExample {
            player_id: sample.player_id.clone(),
            player_name: sample.player_name.clone(),
            transferred_at: sample.transferred_at.clone(),
            market_value: sample.market_value,
            price: sample.price,
            premium_pct: sample.premium_pct,
        }).collect();

        result.push(LeaguePurchasePriceStat {
            player_id: input.player_id,
            sample_count: selected.len(),
            segment_sample_count: segment.len(),
            used_segment,
            median_premium_pct: median,
            average_premium_pct: average,
            p25_premium_pct: p25,
            p75_premium_pct: p75,
            typical_price,
            typical_price_low,
            typical_price_high,
            examples,
        });
    }

    #[cfg(debug_assertions)]
    crate::kt_debug!("[KickTrack][DEBUG][league-price] league={} buys={} market_players={}", league_id, samples.len(), result.len());

    Ok(result)
}



fn recency_weight(age_days: i64) -> f64 {
    match age_days {
        0..=30 => 1.0,
        31..=90 => 0.75,
        91..=180 => 0.50,
        _ => 0.25,
    }
}

fn weighted_quantile(sorted: &[(f64, f64)], q: f64) -> Option<f64> {
    if sorted.is_empty() { return None; }
    let total = sorted.iter().map(|(_, weight)| weight.max(0.0)).sum::<f64>();
    if total <= 0.0 { return None; }
    let threshold = total * q.clamp(0.0, 1.0);
    let mut cumulative = 0.0;
    for (value, weight) in sorted {
        cumulative += weight.max(0.0);
        if cumulative >= threshold { return Some(*value); }
    }
    sorted.last().map(|(value, _)| *value)
}

fn market_value_bucket(value: i64) -> u8 {
    match value {
        ..=1_999_999 => 0,
        2_000_000..=4_999_999 => 1,
        5_000_000..=9_999_999 => 2,
        10_000_000..=19_999_999 => 3,
        _ => 4,
    }
}
