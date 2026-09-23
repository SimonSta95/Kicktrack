use std::collections::HashMap;

use serde::Serialize;
use serde_json::Value;

use super::error::CommandError;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SquadResponse {
    pub players: Vec<SquadPlayer>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SquadPlayer {
    pub id: String,
    pub name: String,
    pub first_name: Option<String>,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub portrait_data_url: Option<String>,
    pub team_logo_data_url: Option<String>,
    pub position: PlayerPosition,
    pub market_value: Option<i64>,
    pub market_value_change_24h: Option<i64>,
    pub market_value_gain_loss: Option<i64>,
    pub long_market_value_change: Option<i64>,
    pub points_total: Option<i64>,
    pub average_points: Option<f64>,
    pub status: Option<i64>,
    pub status_list: Vec<i64>,
    pub status_text: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PlayerPosition {
    Goalkeeper,
    Defender,
    Midfielder,
    Forward,
    Unknown,
}

pub fn parse_squad(value: &Value) -> Result<SquadResponse, CommandError> {
    let items = value
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| value.as_array())
        .ok_or_else(|| {
            CommandError::invalid_response(
                "Kickbase hat den Kader in einem unbekannten Format geliefert.",
            )
        })?;

    let players = items.iter().filter_map(parse_player).collect::<Vec<_>>();

    if !items.is_empty() && players.is_empty() {
        return Err(CommandError::invalid_response(
            "Kickbase hat Kaderspieler geliefert, die nicht gelesen werden konnten.",
        ));
    }

    Ok(SquadResponse { players })
}

pub fn parse_team_logos(value: &Value) -> HashMap<String, String> {
    value
        .get("tms")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|team| {
            let id = string_value(team, &["tid", "i", "id"])?;
            let logo = string_value(team, &["tim", "logo", "image"])?;
            Some((id, logo))
        })
        .collect()
}

fn parse_player(value: &Value) -> Option<SquadPlayer> {
    let id = string_value(value, &["i", "pi", "id"])?;
    let name = string_value(value, &["n", "pn", "name"])
        .unwrap_or_else(|| format!("Spieler {id}"));

    debug_status_payload("squad", &id, &name, value);

    Some(SquadPlayer {
        id,
        name,
        first_name: string_value(value, &["fn", "firstName"]),
        team_id: string_value(value, &["tid", "teamId"]),
        club_name: None,
        portrait_data_url: None,
        team_logo_data_url: None,
        position: parse_position(integer_value(value, &["pos", "position"])),
        market_value: integer_value(value, &["mv", "marketValue"]),
        market_value_change_24h: integer_value(value, &["tfhmvt", "marketValueChange24h"]),
        market_value_gain_loss: integer_value(value, &["mvgl", "marketValueGainLoss"]),
        long_market_value_change: integer_value(value, &["sdmvt", "longMarketValueChange"]),
        points_total: integer_value(value, &["p", "points", "pointsTotal"]),
        average_points: number_value(value, &["ap", "averagePoints"]),
        status: integer_value(value, &["st", "status"]),
        status_list: status_codes(value),
        status_text: status_text(value),
    })
}

fn parse_position(value: Option<i64>) -> PlayerPosition {
    match value {
        Some(1) => PlayerPosition::Goalkeeper,
        Some(2) => PlayerPosition::Defender,
        Some(3) => PlayerPosition::Midfielder,
        Some(4) => PlayerPosition::Forward,
        _ => PlayerPosition::Unknown,
    }
}

fn string_value(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::String(text) if !text.trim().is_empty() => Some(text.to_string()),
            Value::Number(number) => Some(number.to_string()),
            _ => None,
        })
    })
}

fn integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number.as_i64(),
            Value::String(text) => text.parse::<i64>().ok(),
            _ => None,
        })
    })
}

fn number_value(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|candidate| match candidate {
            Value::Number(number) => number.as_f64(),
            Value::String(text) => text.parse::<f64>().ok(),
            _ => None,
        })
    })
}

fn status_codes(value: &Value) -> Vec<i64> {
    for key in ["stl", "statusList"] {
        if let Some(items) = value.get(key).and_then(Value::as_array) {
            return items.iter().filter_map(|candidate| match candidate {
                Value::Number(number) => number.as_i64(),
                Value::String(text) => text.parse::<i64>().ok(),
                Value::Object(_) => integer_value(candidate, &["st", "status", "i", "id"]),
                _ => None,
            }).collect();
        }
    }
    Vec::new()
}

fn status_text(value: &Value) -> Option<String> {
    string_value(value, &["stxt", "statusText", "status_text"])
        .or_else(|| value.get("stl").and_then(Value::as_array).and_then(|items| {
            let texts = items.iter().filter_map(|candidate| string_value(candidate, &["stxt", "txt", "text", "label", "name"])).collect::<Vec<_>>();
            if texts.is_empty() { None } else { Some(texts.join(" · ")) }
        }))
}


#[cfg(debug_assertions)]
fn debug_status_payload(context: &str, player_id: &str, player_name: &str, value: &Value) {
    let status = value.get("st").or_else(|| value.get("status"));
    if status.and_then(Value::as_i64).unwrap_or(0) <= 0
        && value.get("stl").is_none()
        && value.get("stxt").is_none()
    {
        return;
    }

    let st = status.cloned().unwrap_or(Value::Null);
    let stl = value
        .get("stl")
        .or_else(|| value.get("statusList"))
        .cloned()
        .unwrap_or(Value::Null);
    let stxt = value
        .get("stxt")
        .or_else(|| value.get("statusText"))
        .cloned()
        .unwrap_or(Value::Null);

    crate::kt_debug!(
        "[KickTrack][DEBUG][status:{context}] player={player_name} ({player_id}) st={} stl={} stxt={}",
        serde_json::to_string(&st).unwrap_or_else(|_| "<unreadable>".into()),
        serde_json::to_string(&stl).unwrap_or_else(|_| "<unreadable>".into()),
        serde_json::to_string(&stxt).unwrap_or_else(|_| "<unreadable>".into()),
    );
}

#[cfg(not(debug_assertions))]
#[inline]
fn debug_status_payload(_context: &str, _player_id: &str, _player_name: &str, _value: &Value) {}
