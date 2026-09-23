use serde::Serialize;
use serde_json::Value;

use super::error::CommandError;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountBootstrap {
    pub user: AccountUser,
    pub leagues: Vec<LeagueSummary>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountUser {
    pub id: Option<String>,
    pub email: Option<String>,
    pub username: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeagueSummary {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LeagueAccountContext {
    pub league_id: String,
    pub league_name: String,
    pub budget: Option<i64>,
    pub budget_after_active_bids: Option<i64>,
    pub squad_size: Option<i64>,
    pub squad_limit: Option<i64>,
}

pub fn parse_account_user(value: &Value) -> AccountUser {
    let user = value.get("u").unwrap_or(value);

    AccountUser {
        id: string_value(user, &["i", "id"]),
        email: string_value(user, &["em", "email"]),
        username: string_value(user, &["unm", "username", "n", "name"]),
    }
}

pub fn parse_leagues(value: &Value) -> Result<Vec<LeagueSummary>, CommandError> {
    let items = value
        .as_array()
        .or_else(|| value.get("it").and_then(Value::as_array))
        .or_else(|| value.get("leagues").and_then(Value::as_array))
        .ok_or_else(|| {
            CommandError::invalid_response(
                "Kickbase hat die Liga-Auswahl in einem unbekannten Format geliefert.",
            )
        })?;

    let leagues = items
        .iter()
        .filter_map(|item| {
            let id = string_value(item, &["i", "id"])?;
            let name = string_value(item, &["n", "name", "lnm"])
                .unwrap_or_else(|| "Unbenannte Liga".to_string());
            Some(LeagueSummary { id, name })
        })
        .collect::<Vec<_>>();

    if leagues.is_empty() {
        return Err(CommandError::invalid_response(
            "Für diesen Kickbase-Account wurden keine nutzbaren Ligen gefunden.",
        ));
    }

    Ok(leagues)
}

pub fn parse_league_context(
    league_id: String,
    me: &Value,
    budget: &Value,
) -> LeagueAccountContext {
    LeagueAccountContext {
        league_id,
        league_name: string_value(me, &["lnm", "name", "n"])
            .unwrap_or_else(|| "Kickbase Liga".to_string()),
        budget: budget_integer_value(
            budget,
            &["b", "budget", "bdg", "amount", "balance", "cash", "availableBudget"],
        )
        .or_else(|| budget_integer_value(me, &["b", "budget", "balance", "cash"])),
        budget_after_active_bids: budget_integer_value(
            budget,
            &["pbaa", "budgetAfterActiveAuctions", "budgetAfterActiveBids"],
        ),
        squad_size: integer_value(me, &["mgc", "squadSize"]),
        squad_limit: integer_value(me, &["mgm", "squadLimit"]),
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
        value.get(*key).and_then(number_as_i64)
    })
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


fn budget_integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    // This helper is only used on the dedicated /me/budget response (or the
    // /me fallback), so it is safe to walk nested wrappers and look for the
    // exact compact/long-form budget keys. This covers responses wrapped in
    // arrays/objects without guessing unrelated field names.
    recursive_integer_value(value, keys, 0)
}

fn recursive_integer_value(value: &Value, keys: &[&str], depth: usize) -> Option<i64> {
    if depth > 8 {
        return None;
    }

    if let Some(found) = integer_value(value, keys) {
        return Some(found);
    }

    match value {
        Value::Object(map) => map
            .values()
            .find_map(|nested| recursive_integer_value(nested, keys, depth + 1)),
        Value::Array(items) => items
            .iter()
            .find_map(|nested| recursive_integer_value(nested, keys, depth + 1)),
        _ => None,
    }
}
