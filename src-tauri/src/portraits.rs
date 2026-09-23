use std::{collections::HashMap, fs, time::Duration};

use reqwest::header;
use serde::Serialize;
use serde_json::Value;
use tauri::State;

use crate::{
    db::{KickTrackDatabase, PortraitPlayer, PortraitReviewItem},
    kickbase::error::CommandError,
    state::AppState,
};

const FOTMOB_SEARCH_URL: &str = "https://apigw.fotmob.com/searchapi/suggest";
const FOTMOB_IMAGE_BASE: &str = "https://images.fotmob.com/image_resources/playerimages";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PortraitSyncSummary {
    pub requested: usize,
    pub cached: usize,
    pub review: usize,
    pub failed: usize,
    pub skipped: usize,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PortraitManagerState {
    pub cached: i64,
    pub review: i64,
    pub failed: i64,
    pub rejected: i64,
    pub missing: i64,
    pub review_items: Vec<PortraitReviewItem>,
}

#[derive(Debug, Clone)]
struct FotMobCandidate {
    id: String,
    name: String,
    team: String,
    position: String,
    shirt_number: String,
}

fn current_token(state: &State<'_, AppState>) -> Result<String, CommandError> {
    let session = state.session.lock().map_err(|_| CommandError::internal("Die lokale Session konnte nicht gelesen werden."))?;
    session.as_ref().map(|session| session.token.clone()).ok_or_else(CommandError::session_expired)
}

fn fotmob_client() -> Result<reqwest::Client, CommandError> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(8))
        .timeout(Duration::from_secs(12))
        .redirect(reqwest::redirect::Policy::limited(4))
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        .default_headers({
            let mut headers = header::HeaderMap::new();
            headers.insert(header::ACCEPT, header::HeaderValue::from_static("application/json,text/plain,*/*"));
            headers.insert(header::ACCEPT_LANGUAGE, header::HeaderValue::from_static("de-DE,de;q=0.9,en;q=0.7"));
            headers.insert(header::REFERER, header::HeaderValue::from_static("https://www.fotmob.com/"));
            headers
        })
        .build()
        .map_err(|_| CommandError::internal("Der Portrait-Resolver konnte nicht initialisiert werden."))
}

#[tauri::command]
pub fn portrait_manager_state() -> Result<PortraitManagerState, CommandError> {
    let db = KickTrackDatabase::open_default()?;
    let repaired = db.revalidate_portrait_cache()?;
    #[cfg(debug_assertions)]
    if repaired > 0 {
        crate::kt_debug!("[KickTrack][DEBUG][portrait] {} fehlende Cache-Dateien zurück auf MISSING gesetzt", repaired);
    }
    let review_items = db.portrait_review_items()?;
    let counts = db.portrait_state_counts()?;
    Ok(PortraitManagerState {
        cached: *counts.get("CACHED").unwrap_or(&0),
        review: *counts.get("NEEDS_REVIEW").unwrap_or(&0),
        failed: *counts.get("FAILED").unwrap_or(&0),
        rejected: *counts.get("REJECTED").unwrap_or(&0),
        missing: *counts.get("MISSING").unwrap_or(&0),
        review_items,
    })
}

#[tauri::command]
pub async fn sync_missing_portraits(
    league_id: String,
    limit: Option<usize>,
    retry_failed: Option<bool>,
    state: State<'_, AppState>,
) -> Result<PortraitSyncSummary, CommandError> {
    let token = current_token(&state)?;
    let client = fotmob_client()?;
    {
        let db = KickTrackDatabase::open_default()?;
        db.revalidate_portrait_cache()?;
    }

    // Never keep rusqlite across an await. Fetch first, then open the DB only for
    // the short synchronous write. This keeps Tauri command futures Send.
    if let Ok(catalog) = state.kickbase.get_json(&token, "/v4/competitions/1/players?position=0&sorting=1").await {
        let db = KickTrackDatabase::open_default()?;
        seed_player_catalog(&db, &catalog)?;
    }

    let candidates = {
        let db = KickTrackDatabase::open_default()?;
        db.portrait_candidates(limit.unwrap_or(1000).clamp(1, 1000), retry_failed.unwrap_or(false))?
    };
    let requested = candidates.len();
    let mut summary = PortraitSyncSummary { requested, cached: 0, review: 0, failed: 0, skipped: 0 };

    for mut player in candidates {
        if player.portrait_state == "CACHED" {
            if let Some(path) = player.portrait_path.as_deref() {
                if std::path::Path::new(path).exists() {
                    summary.skipped += 1;
                    continue;
                }
            }
        }

        if needs_identity_enrichment(&player) {
            if let Ok(payload) = state.kickbase.get_json(&token, &format!("/v4/competitions/1/players/{}?leagueId={}", player.player_id, league_id.trim())).await {
                if let Some(full_name) = extract_full_name(&payload) {
                    player.full_name = Some(full_name);
                }
            }
        }

        let fallback_player = player.clone();
        let resolved = if let Some(fotmob_id) = player.fotmob_id.clone() {
            download_known_mapping(&client, player, &fotmob_id).await
        } else {
            resolve_and_maybe_download(&client, player).await
        };

        let result = match resolved {
            Ok(result) => result,
            Err(error) => {
                let mut failed = fallback_player;
                failed.player_id = error.player_id;
                failed.portrait_state = "FAILED".into();
                failed.portrait_path = None;
                failed.portrait_reason = Some(error.message.chars().take(240).collect());
                failed
            }
        };

        #[cfg(debug_assertions)]
        crate::kt_debug!("[KickTrack][DEBUG][portrait] player={} state={} confidence={:?} reason={:?}", result.player_id, result.portrait_state, result.portrait_confidence, result.portrait_reason);

        {
            let db = KickTrackDatabase::open_default()?;
            db.save_portrait_mapping(&result)?;
        }
        match result.portrait_state.as_str() {
            "CACHED" => summary.cached += 1,
            "NEEDS_REVIEW" => summary.review += 1,
            "FAILED" => summary.failed += 1,
            _ => summary.skipped += 1,
        }
    }

    Ok(summary)
}

/// Incrementally resolve portraits for players that were just seen in a live
/// Kickbase resource. Existing cached/rejected/review mappings are untouched;
/// FAILED mappings are not retried automatically on every page load.
pub async fn sync_portraits_for_player_ids(
    league_id: &str,
    player_ids: &[String],
    state: &State<'_, AppState>,
) -> Result<PortraitSyncSummary, CommandError> {
    if player_ids.is_empty() {
        return Ok(PortraitSyncSummary { requested: 0, cached: 0, review: 0, failed: 0, skipped: 0 });
    }

    let token = current_token(state)?;
    let client = fotmob_client()?;
    let candidates = {
        let db = KickTrackDatabase::open_default()?;
        db.portrait_candidates_for_ids(player_ids, false)?
    };

    let requested = candidates.len();
    let mut summary = PortraitSyncSummary { requested, cached: 0, review: 0, failed: 0, skipped: 0 };

    for mut player in candidates {
        if needs_identity_enrichment(&player) {
            if let Ok(payload) = state.kickbase
                .get_json(&token, &format!("/v4/competitions/1/players/{}?leagueId={}", player.player_id, league_id.trim()))
                .await
            {
                if let Some(full_name) = extract_full_name(&payload) {
                    player.full_name = Some(full_name);
                }
            }
        }

        let fallback_player = player.clone();
        let resolved = if let Some(fotmob_id) = player.fotmob_id.clone() {
            download_known_mapping(&client, player, &fotmob_id).await
        } else {
            resolve_and_maybe_download(&client, player).await
        };

        let result = match resolved {
            Ok(result) => result,
            Err(error) => {
                let mut failed = fallback_player;
                failed.player_id = error.player_id;
                failed.portrait_state = "FAILED".into();
                failed.portrait_path = None;
                failed.portrait_reason = Some(error.message.chars().take(240).collect());
                failed
            }
        };

        {
            let db = KickTrackDatabase::open_default()?;
            db.save_portrait_mapping(&result)?;
        }

        match result.portrait_state.as_str() {
            "CACHED" => summary.cached += 1,
            "NEEDS_REVIEW" => summary.review += 1,
            "FAILED" => summary.failed += 1,
            _ => summary.skipped += 1,
        }

        #[cfg(debug_assertions)]
        crate::kt_debug!(
            "[KickTrack][DEBUG][portrait:auto] player={} state={} confidence={:?} reason={:?}",
            result.player_id, result.portrait_state, result.portrait_confidence, result.portrait_reason
        );
    }

    Ok(summary)
}

#[tauri::command]
pub async fn accept_portrait_candidate(player_id: String) -> Result<bool, CommandError> {
    let player = {
        let db = KickTrackDatabase::open_default()?;
        let mut player = db
            .portrait_candidates(1000, true)?
            .into_iter()
            .find(|row| row.player_id == player_id.trim());

        if player.is_none() {
            player = db
                .portrait_review_items()?
                .into_iter()
                .find(|row| row.player_id == player_id.trim())
                .map(|row| PortraitPlayer {
                    player_id: row.player_id,
                    display_name: row.player_name.clone(),
                    full_name: Some(row.player_name),
                    club_name: row.club_name,
                    fotmob_id: row.fotmob_id,
                    portrait_url: row.portrait_url,
                    portrait_path: None,
                    portrait_state: "NEEDS_REVIEW".into(),
                    portrait_confidence: row.confidence,
                    portrait_reason: row.reason,
                    candidate_name: row.candidate_name,
                    candidate_team: row.candidate_team,
                    candidate_position: row.candidate_position,
                    candidate_shirt_number: row.candidate_shirt_number,
                });
        }

        player.ok_or_else(|| CommandError::http(404, "Der Portrait-Prüffall wurde nicht gefunden."))?
    };

    let fotmob_id = player
        .fotmob_id
        .clone()
        .ok_or_else(|| CommandError::http(400, "Für diesen Prüffall ist keine FotMob-ID gespeichert."))?;
    let client = fotmob_client()?;
    let result = download_known_mapping(&client, player, &fotmob_id)
        .await
        .map_err(|error| CommandError::internal(error.message))?;

    {
        let db = KickTrackDatabase::open_default()?;
        db.save_portrait_mapping(&result)?;
    }

    Ok(result.portrait_state == "CACHED")
}

#[tauri::command]
pub fn reject_portrait_candidate(player_id: String) -> Result<bool, CommandError> {
    let db = KickTrackDatabase::open_default()?;
    db.reject_portrait(player_id.trim())?;
    Ok(true)
}

#[derive(Debug)]
struct PortraitResolveError { player_id: String, message: String }

impl PortraitResolveError {
    fn new(player_id: &str, message: impl Into<String>) -> Self { Self { player_id: player_id.to_string(), message: message.into() } }
}

async fn resolve_and_maybe_download(client: &reqwest::Client, mut player: PortraitPlayer) -> Result<PortraitPlayer, PortraitResolveError> {
    let search_name = player.full_name.as_deref().filter(|name| !name.trim().is_empty()).unwrap_or(&player.display_name).trim().to_string();
    if search_name.is_empty() { return Err(PortraitResolveError::new(&player.player_id, "Spielername fehlt")); }

    let response = client.get(FOTMOB_SEARCH_URL).query(&[("term", search_name.as_str()), ("lang", "en")]).send().await
        .map_err(|_| PortraitResolveError::new(&player.player_id, "FotMob-Suche nicht erreichbar"))?;
    if !response.status().is_success() { return Err(PortraitResolveError::new(&player.player_id, format!("FotMob-Suche HTTP {}", response.status().as_u16()))); }
    let payload: Value = response.json().await.map_err(|_| PortraitResolveError::new(&player.player_id, "FotMob-Suche lieferte ungültiges JSON"))?;
    let candidates = extract_candidates(&payload);
    if candidates.is_empty() { return Err(PortraitResolveError::new(&player.player_id, "Kein FotMob-Spielertreffer")); }

    let mut ranked: Vec<(i64, String, FotMobCandidate)> = candidates.into_iter().map(|candidate| {
        let (score, reason) = candidate_score(&player, &candidate);
        (score, reason, candidate)
    }).collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0));
    let (score, mut reason, best) = ranked[0].clone();
    let runner_up = ranked.get(1).map(|row| row.0).unwrap_or(-1);
    let unambiguous = ranked.len() == 1 || score - runner_up >= 8;
    let surname_collision = surname_club_collision(&player, &best, &ranked);

    player.fotmob_id = Some(best.id.clone());
    player.portrait_url = Some(format!("{FOTMOB_IMAGE_BASE}/{}.png", best.id));
    player.portrait_confidence = Some(score);
    player.candidate_name = some_text(best.name);
    player.candidate_team = some_text(best.team);
    player.candidate_position = some_text(best.position);
    player.candidate_shirt_number = some_text(best.shirt_number);

    if surname_collision { reason.push_str(" · gleicher Nachname mehrfach im selben Verein"); }
    else if score >= 78 && !unambiguous { reason.push_str(" · mehrere ähnlich starke Treffer"); }
    player.portrait_reason = Some(reason);

    if score >= 78 && unambiguous && !surname_collision {
        download_known_mapping(client, player, &best.id).await
    } else {
        player.portrait_state = "NEEDS_REVIEW".into();
        player.portrait_path = None;
        Ok(player)
    }
}

async fn download_known_mapping(client: &reqwest::Client, mut player: PortraitPlayer, fotmob_id: &str) -> Result<PortraitPlayer, PortraitResolveError> {
    let url = player.portrait_url.clone().unwrap_or_else(|| format!("{FOTMOB_IMAGE_BASE}/{fotmob_id}.png"));
    let response = client.get(&url).send().await.map_err(|_| PortraitResolveError::new(&player.player_id, "FotMob-Portrait konnte nicht geladen werden"))?;
    if response.status().as_u16() == 404 { return Err(PortraitResolveError::new(&player.player_id, "FotMob-Portrait nicht vorhanden")); }
    if !response.status().is_success() { return Err(PortraitResolveError::new(&player.player_id, format!("Portrait HTTP {}", response.status().as_u16()))); }
    let content_type = response.headers().get(header::CONTENT_TYPE).and_then(|value| value.to_str().ok()).unwrap_or("").to_ascii_lowercase();
    let bytes = response.bytes().await.map_err(|_| PortraitResolveError::new(&player.player_id, "Portrait konnte nicht gelesen werden"))?;
    if !content_type.contains("image") && !bytes.starts_with(&[0x89, b'P', b'N', b'G']) {
        return Err(PortraitResolveError::new(&player.player_id, "FotMob-Antwort war kein Bild"));
    }
    let destination = {
        let db = KickTrackDatabase::open_default()
            .map_err(|e| PortraitResolveError::new(&player.player_id, e.message))?;
        db.portrait_cache_path(&player.player_id)
            .map_err(|e| PortraitResolveError::new(&player.player_id, e.message))?
    };
    fs::write(&destination, &bytes).map_err(|_| PortraitResolveError::new(&player.player_id, "Portrait konnte nicht lokal gespeichert werden"))?;
    player.fotmob_id = Some(fotmob_id.to_string());
    player.portrait_url = Some(url);
    player.portrait_path = Some(destination.to_string_lossy().to_string());
    player.portrait_state = "CACHED".into();
    if player.portrait_reason.is_none() { player.portrait_reason = Some("Vorhandenes FotMob-Mapping".into()); }
    Ok(player)
}

fn needs_identity_enrichment(player: &PortraitPlayer) -> bool {
    let full = player.full_name.as_deref().unwrap_or(&player.display_name);
    normalize(full).split_whitespace().count() <= 1
}

fn extract_full_name(payload: &Value) -> Option<String> {
    for key in ["fullName", "full_name", "fnm", "pn", "n"] {
        if let Some(value) = payload.get(key).and_then(Value::as_str).map(str::trim).filter(|value| value.split_whitespace().count() >= 2) {
            return Some(value.to_string());
        }
    }
    if let (Some(first), Some(last)) = (payload.get("fn").and_then(Value::as_str), payload.get("ln").and_then(Value::as_str)) {
        let combined = format!("{} {}", first.trim(), last.trim()).trim().to_string();
        if !combined.is_empty() { return Some(combined); }
    }
    None
}

fn seed_player_catalog(db: &KickTrackDatabase, payload: &Value) -> Result<(), CommandError> {
    let items = payload.get("it").and_then(Value::as_array).or_else(|| payload.as_array());
    let Some(items) = items else { return Ok(()); };
    for item in items {
        let id = ["i","pi","id"].iter().find_map(|key| item.get(*key).and_then(scalar_string));
        let display_name = ["n","pn","name"].iter().find_map(|key| item.get(*key).and_then(Value::as_str)).map(str::trim).filter(|name| !name.is_empty());
        let (Some(id),Some(display_name)) = (id,display_name) else { continue; };
        let first = item.get("fn").and_then(Value::as_str).map(str::trim).filter(|value| !value.is_empty());
        let last = item.get("ln").and_then(Value::as_str).map(str::trim).filter(|value| !value.is_empty());
        let full_name = match (first,last) { (Some(first),Some(last)) => Some(format!("{first} {last}")), (Some(first),None) if !display_name.starts_with(first) => Some(format!("{first} {display_name}")), _ => None };
        let team_id = item.get("tid").and_then(scalar_string);
        let position = item.get("pos").and_then(|value| value.as_i64().or_else(||value.as_f64().map(|v|v.round() as i64))).map(|pos| match pos {1=>"TW",2=>"ABW",3=>"MF",4=>"ST",_=>"UNKNOWN"});
        db.upsert_player_reference(&id, display_name, full_name.as_deref(), team_id.as_deref(), position)?;
    }
    Ok(())
}

fn extract_candidates(payload: &Value) -> Vec<FotMobCandidate> {
    let mut found = Vec::new();
    if let Some(groups) = payload.get("squadMemberSuggest").and_then(Value::as_array) {
        for group in groups {
            if let Some(options) = group.get("options").and_then(Value::as_array) {
                for option in options {
                    if let Some(candidate) = candidate_from_option(option) { found.push(candidate); }
                }
            }
        }
    }
    walk_candidates(payload, "", &mut found);
    let mut unique = HashMap::new();
    for candidate in found { unique.entry(candidate.id.clone()).or_insert(candidate); }
    unique.into_values().collect()
}

fn candidate_from_option(option: &Value) -> Option<FotMobCandidate> {
    let payload = option.get("payload")?.as_object()?;
    let id = scalar_string(payload.get("id")?)?;
    let text = option.get("text").and_then(Value::as_str).unwrap_or("");
    let name = text.split('|').next().unwrap_or("").trim().to_string();
    if name.is_empty() { return None; }
    Some(FotMobCandidate { id, name, team: payload.get("teamName").and_then(scalar_string).unwrap_or_default(),
        position: payload.get("position").or_else(|| payload.get("positionName")).or_else(|| payload.get("role")).and_then(scalar_string).unwrap_or_default(),
        shirt_number: payload.get("shirtNumber").or_else(|| payload.get("jerseyNumber")).or_else(|| payload.get("number")).and_then(scalar_string).unwrap_or_default() })
}

fn walk_candidates(node: &Value, inherited_type: &str, found: &mut Vec<FotMobCandidate>) {
    match node {
        Value::Array(items) => for item in items { walk_candidates(item, inherited_type, found); },
        Value::Object(map) => {
            let result_type = ["type","resultType","category"].iter().find_map(|key| map.get(*key).and_then(Value::as_str)).unwrap_or(inherited_type).to_ascii_lowercase();
            let id = ["id","playerId","player_id","entityId"].iter().find_map(|key| map.get(*key).and_then(scalar_string));
            let name = ["name","title","playerName"].iter().find_map(|key| map.get(*key).and_then(Value::as_str)).map(str::to_string);
            let looks_player = result_type.contains("player") || map.contains_key("playerId") || map.contains_key("player_id");
            if looks_player {
                if let (Some(id), Some(name)) = (id, name) {
                    found.push(FotMobCandidate { id, name,
                        team: ["teamName","team","subtitle","secondaryText"].iter().find_map(|key| map.get(*key).and_then(value_or_object_name)).unwrap_or_default(),
                        position: ["position","positionName","role"].iter().find_map(|key| map.get(*key).and_then(scalar_string)).unwrap_or_default(),
                        shirt_number: ["shirtNumber","jerseyNumber","number"].iter().find_map(|key| map.get(*key).and_then(scalar_string)).unwrap_or_default() });
                }
            }
            for (key, value) in map {
                if value.is_object() || value.is_array() { walk_candidates(value, if key.to_ascii_lowercase().contains("player") { "player" } else { &result_type }, found); }
            }
        }
        _ => {}
    }
}

fn candidate_score(player: &PortraitPlayer, candidate: &FotMobCandidate) -> (i64, String) {
    let full = player.full_name.as_deref().unwrap_or(&player.display_name);
    let short = &player.display_name;
    let expected_full = normalize(full); let expected_short = normalize(short); let candidate_name = normalize(&candidate.name);
    let mut score = 0; let mut reasons = Vec::new();
    if !candidate_name.is_empty() && candidate_name == expected_full { score += 80; reasons.push("Name exakt"); }
    else if !candidate_name.is_empty() && candidate_name == expected_short { score += 72; reasons.push("Kurzname exakt"); }
    else {
        let expected = tokens(full).into_iter().chain(tokens(short)).collect::<std::collections::HashSet<_>>();
        let short_tokens = tokens(short); let candidate_tokens = tokens(&candidate.name);
        let short_token_match = short_tokens.len() == 1 && short_tokens.iter().next().map(|token| candidate_tokens.contains(token)).unwrap_or(false);
        let suffix_match = !expected_short.is_empty() && (candidate_name == expected_short || candidate_name.ends_with(&format!(" {expected_short}")));
        if short_token_match || suffix_match { score += 68; reasons.push("Nachname/Kurzname exakt"); }
        else if !expected.is_empty() && !candidate_tokens.is_empty() {
            let overlap = expected.intersection(&candidate_tokens).count() as f64 / expected.len().max(candidate_tokens.len()) as f64;
            if overlap >= 0.99 { score += 68; reasons.push("Name vollständig"); }
            else if overlap >= 0.66 { score += 50; reasons.push("Name sehr ähnlich"); }
            else if overlap >= 0.5 { score += 35; reasons.push("Name ähnlich"); }
        }
    }
    if let Some(club) = player.club_name.as_deref() {
        let club_norm = normalize(club); let team_norm = normalize(&candidate.team);
        if !club_norm.is_empty() && club_norm == team_norm { score += 22; reasons.push("Verein exakt"); }
        else if !tokens(club).is_disjoint(&tokens(&candidate.team)) { score += 12; reasons.push("Verein ähnlich"); }
    }
    (score.min(100), if reasons.is_empty() { "kein sicherer Match".into() } else { reasons.join(" · ") })
}

fn surname_club_collision(player: &PortraitPlayer, best: &FotMobCandidate, ranked: &[(i64,String,FotMobCandidate)]) -> bool {
    let short = tokens(&player.display_name); if short.len() != 1 { return false; }
    let token = short.iter().next().unwrap(); let best_team = normalize(&best.team); if best_team.is_empty() { return false; }
    ranked.iter().filter(|(_,_,candidate)| tokens(&candidate.name).contains(token) && {
        let team = normalize(&candidate.team); team == best_team || !tokens(&candidate.team).is_disjoint(&tokens(&best.team))
    }).count() >= 2
}

fn normalize(value: &str) -> String {
    let mut out = String::new();
    for ch in value.trim().to_lowercase().chars() {
        match ch {
            'ä'|'á'|'à'|'â'|'ã'|'å' => out.push('a'), 'ö'|'ó'|'ò'|'ô'|'õ'|'ø' => out.push('o'),
            'ü'|'ú'|'ù'|'û' => out.push('u'), 'é'|'è'|'ê'|'ë' => out.push('e'), 'í'|'ì'|'î'|'ï' => out.push('i'),
            'ç' => out.push('c'), 'ñ' => out.push('n'), 'ß' => out.push_str("ss"),
            c if c.is_ascii_alphanumeric() => out.push(c), _ => out.push(' '),
        }
    }
    out.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn tokens(value: &str) -> std::collections::HashSet<String> { normalize(value).split_whitespace().map(str::to_string).collect() }
fn some_text(value: String) -> Option<String> { if value.trim().is_empty() { None } else { Some(value) } }
fn scalar_string(value: &Value) -> Option<String> { match value { Value::String(value) => Some(value.clone()), Value::Number(value) => Some(value.to_string()), _ => None } }
fn value_or_object_name(value: &Value) -> Option<String> { if let Some(value) = scalar_string(value) { return Some(value); } value.as_object().and_then(|map| map.get("name").or_else(|| map.get("title"))).and_then(scalar_string) }

