use serde::Serialize;
use serde_json::Value;

use super::error::CommandError;
use super::squad::PlayerPosition;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketResponse {
    pub entries: Vec<MarketEntry>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketEntry {
    pub player_id: String,
    pub name: String,
    pub first_name: Option<String>,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub portrait_data_url: Option<String>,
    pub position: PlayerPosition,
    pub market_value: Option<i64>,
    pub market_value_change_24h: Option<i64>,
    pub price: Option<i64>,
    pub price_difference: Option<i64>,
    pub points_total: Option<i64>,
    pub average_points: Option<f64>,
    pub status: Option<i64>,
    pub status_list: Vec<i64>,
    pub status_text: Option<String>,
    pub seller_id: Option<String>,
    pub seller_name: Option<String>,
    pub is_kickbase_seller: bool,
    pub own_offer_id: Option<String>,
    pub own_offer: Option<i64>,
    pub offer_count: Option<i64>,
    pub offers: Vec<MarketOffer>,
    pub expires_in_seconds: Option<i64>,
    pub is_new: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketOffer {
    pub id: Option<String>,
    pub user_id: Option<String>,
    pub user_name: Option<String>,
    pub price: Option<i64>,
    pub is_kickbase: bool,
}

pub fn parse_market(value: &Value) -> Result<MarketResponse, CommandError> {
    let items = value
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| value.as_array())
        .ok_or_else(|| CommandError::invalid_response("Kickbase hat den Markt in einem unbekannten Format geliefert."))?;

    let entries = items.iter().filter_map(parse_entry).collect::<Vec<_>>();
    if !items.is_empty() && entries.is_empty() {
        return Err(CommandError::invalid_response("Kickbase hat Markteinträge geliefert, die nicht gelesen werden konnten."));
    }

    Ok(MarketResponse { entries })
}

fn parse_entry(value: &Value) -> Option<MarketEntry> {
    let player_id = string_value(value, &["pi", "i", "playerId", "id"])?;
    let name = string_value(value, &["pn", "n", "name"])
        .or_else(|| {
            let first = string_value(value, &["fn", "firstName"])?;
            let last = string_value(value, &["ln", "lastName"]);
            Some(match last { Some(last) => format!("{first} {last}"), None => first })
        })
        .unwrap_or_else(|| format!("Spieler {player_id}"));

    let market_value = integer_value(value, &["mv", "marketValue"]);
    let price = integer_value(value, &["prc", "price"]);
    let (seller_id, seller_name, is_kickbase_seller) = parse_seller(value.get("u"));

    Some(MarketEntry {
        player_id,
        first_name: sanitized_first_name(string_value(value, &["fn", "firstName"]), &name),
        name,
        team_id: string_value(value, &["tid", "teamId"]),
        club_name: None,
        portrait_data_url: None,
        position: parse_position(integer_value(value, &["pos", "position"])),
        market_value,
        market_value_change_24h: integer_value(value, &["tfhmvt", "marketValueChange24h"]),
        price,
        price_difference: match (price, market_value) { (Some(price), Some(mv)) => Some(price - mv), _ => None },
        points_total: integer_value(value, &["p", "points", "pointsTotal"]),
        average_points: number_value(value, &["ap", "averagePoints"]),
        status: integer_value(value, &["st", "status"]),
        status_list: integer_array(value, &["stl", "statusList"]),
        status_text: string_value(value, &["stxt", "statusText"]),
        seller_id,
        seller_name,
        is_kickbase_seller,
        own_offer_id: string_value(value, &["uoid", "ownOfferId"]),
        own_offer: integer_value(value, &["uop", "ownOffer", "ownOfferPrice"]),
        offer_count: integer_value(value, &["ofc", "offerCount"]),
        offers: parse_visible_offers(value),
        expires_in_seconds: integer_value(value, &["exs", "expiresInSeconds"]),
        is_new: bool_value(value, &["isn", "isNew"]).unwrap_or(false),
    })
}


pub fn parse_visible_offers(value: &Value) -> Vec<MarketOffer> {
    let Some(items) = find_offer_array(value, 0) else { return Vec::new(); };
    let mut offers = items.iter().filter_map(parse_offer).collect::<Vec<_>>();

    // Compact responses can repeat the same bid in several aliases. Keep one
    // canonical row per bidder/offer + price so UI and budget math never double count.
    offers.dedup_by(|a, b| a.id == b.id && a.user_id == b.user_id && a.price == b.price && a.is_kickbase == b.is_kickbase);
    offers
}

pub fn transfer_offer_count(value: &Value) -> Option<i64> {
    find_integer_recursive(value, &["ofc", "offerCount"], 0)
        .or_else(|| {
            let count = parse_visible_offers(value).len();
            if count > 0 { Some(count as i64) } else { None }
        })
}

fn parse_offer(value: &Value) -> Option<MarketOffer> {
    if !value.is_object() { return None; }

    let (nested_user_id, nested_user_name) = match value.get("u") {
        Some(Value::Object(_)) => (
            string_value(value.get("u")?, &["i", "ui", "u", "id", "userId"]),
            string_value(value.get("u")?, &["unm", "n", "name", "username"]),
        ),
        _ => (None, None),
    };

    let user_id = string_value(value, &["uoid", "ui", "userId", "uid"])
        .or(nested_user_id)
        .or_else(|| match value.get("u") {
            Some(Value::String(text)) if !text.trim().is_empty() => Some(text.clone()),
            Some(Value::Number(number)) => Some(number.to_string()),
            _ => None,
        });
    let user_name = string_value(value, &["unm", "userName", "username"]).or(nested_user_name);
    let price = integer_value(value, &["uop", "prc", "price", "amount", "bid", "p"]);

    // For manager offers Kickbase commonly expects the bidder/user id in the
    // accept/decline route. Prefer that over opaque row ids when both exist.
    let id = user_id.clone().or_else(|| string_value(value, &["oi", "offerId", "i", "id"]));
    let is_kickbase = user_id.is_none()
        && user_name.as_deref().map(|name| name.eq_ignore_ascii_case("kickbase")).unwrap_or(true);

    // Rows without any usable price are not actionable and must not influence
    // the budget planner.
    if price.is_none() { return None; }

    Some(MarketOffer { id, user_id, user_name, price, is_kickbase })
}

fn find_offer_array(value: &Value, depth: usize) -> Option<&Vec<Value>> {
    if depth > 5 { return None; }
    match value {
        Value::Object(map) => {
            for key in ["ofs", "offers"] {
                if let Some(items) = map.get(key).and_then(Value::as_array) { return Some(items); }
            }
            for child in map.values() {
                if let Some(items) = find_offer_array(child, depth + 1) { return Some(items); }
            }
            None
        }
        Value::Array(items) => items.iter().find_map(|child| find_offer_array(child, depth + 1)),
        _ => None,
    }
}

fn find_integer_recursive(value: &Value, keys: &[&str], depth: usize) -> Option<i64> {
    if depth > 5 { return None; }
    if let Some(found) = integer_value(value, keys) { return Some(found); }
    match value {
        Value::Object(map) => map.values().find_map(|child| find_integer_recursive(child, keys, depth + 1)),
        Value::Array(items) => items.iter().find_map(|child| find_integer_recursive(child, keys, depth + 1)),
        _ => None,
    }
}


fn sanitized_first_name(first_name: Option<String>, display_name: &str) -> Option<String> {
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

fn parse_seller(value: Option<&Value>) -> (Option<String>, Option<String>, bool) {
    let Some(value) = value else { return (None, Some("Kickbase".to_string()), true); };
    if value.is_null() { return (None, Some("Kickbase".to_string()), true); }

    match value {
        Value::Object(_) => {
            let id = string_value(value, &["i", "u", "ui", "id", "userId", "managerId"]);
            let name = string_value(value, &["unm", "n", "name", "username"]);
            (id, name, false)
        }
        Value::String(text) if !text.trim().is_empty() => (Some(text.clone()), None, false),
        Value::Number(number) => (Some(number.to_string()), None, false),
        _ => (None, None, false),
    }
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
    keys.iter().find_map(|key| value.get(*key).and_then(|candidate| match candidate {
        Value::String(text) if !text.trim().is_empty() => Some(text.to_string()),
        Value::Number(number) => Some(number.to_string()),
        _ => None,
    }))
}

fn integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| value.get(*key).and_then(number_as_i64))
}

fn number_as_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok()))
            .or_else(|| number.as_f64().map(|value| value.round() as i64)),
        Value::String(text) => text
            .parse::<i64>()
            .ok()
            .or_else(|| text.parse::<f64>().ok().map(|value| value.round() as i64)),
        _ => None,
    }
}

fn number_value(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| value.get(*key).and_then(|candidate| match candidate {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.parse::<f64>().ok(),
        _ => None,
    }))
}

fn bool_value(value: &Value, keys: &[&str]) -> Option<bool> {
    keys.iter().find_map(|key| value.get(*key).and_then(|candidate| match candidate {
        Value::Bool(flag) => Some(*flag),
        Value::Number(number) => number.as_i64().map(|number| number != 0),
        Value::String(text) => match text.as_str() { "true" | "1" => Some(true), "false" | "0" => Some(false), _ => None },
        _ => None,
    }))
}

fn integer_array(value: &Value, keys: &[&str]) -> Vec<i64> {
    keys.iter().find_map(|key| value.get(*key).and_then(Value::as_array).map(|items| {
        items.iter().filter_map(|candidate| match candidate {
            Value::Number(number) => number.as_i64(),
            Value::String(text) => text.parse::<i64>().ok(),
            _ => None,
        }).collect::<Vec<_>>()
    })).unwrap_or_default()
}
