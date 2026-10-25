use super::error::CommandError;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerDetail {
    pub id: String,
    pub name: String,
    pub first_name: Option<String>,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub portrait_data_url: Option<String>,
    pub position: Option<i64>,
    pub market_value: Option<i64>,
    pub market_value_change_24h: Option<i64>,
    pub market_value_gain_loss: Option<i64>,
    pub points_total: Option<i64>,
    pub average_points: Option<f64>,
    pub status: Option<i64>,
    pub status_list: Vec<i64>,
    pub status_text: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PerformanceEntry {
    pub day_number: i64,
    pub points: Option<i64>,
    pub minutes: Option<i64>,
    pub status: Option<i64>,
    pub home_team_id: Option<String>,
    pub away_team_id: Option<String>,
    pub home_goals: Option<i64>,
    pub away_goals: Option<i64>,
    pub player_team_id: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BreakdownItem {
    pub id: String,
    pub label: String,
    pub points: i64,
    pub count: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PerformanceBreakdown {
    pub day_number: i64,
    pub total_points: Option<i64>,
    pub items: Vec<BreakdownItem>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarketValueHistoryEntry {
    pub date: String,
    pub value: i64,
}

pub fn parse_market_value_history(value: &Value) -> Vec<MarketValueHistoryEntry> {
    let items = value
        .get("it")
        .and_then(Value::as_array)
        .or_else(|| value.as_array());

    let mut by_date = BTreeMap::<String, i64>::new();
    for item in items.into_iter().flatten() {
        let Some(value) = integer_value(item, &["mv", "marketValue", "value"]) else {
            continue;
        };
        if value <= 0 {
            continue;
        }
        let Some(date) = market_value_date(item) else {
            continue;
        };
        by_date.insert(date, value);
    }

    by_date
        .into_iter()
        .map(|(date, value)| MarketValueHistoryEntry { date, value })
        .collect()
}

fn market_value_date(item: &Value) -> Option<String> {
    for key in ["date", "snapshotDate"] {
        if let Some(raw) = item.get(key).and_then(Value::as_str) {
            if let Some(date) = iso_date_prefix(raw) {
                return Some(date.to_owned());
            }
        }
    }

    let raw = item.get("dt")?;
    match raw {
        Value::Number(number) => number.as_i64().and_then(unix_day_to_iso),
        Value::String(text) => text
            .parse::<i64>()
            .ok()
            .and_then(unix_day_to_iso)
            .or_else(|| iso_date_prefix(text).map(str::to_owned)),
        _ => None,
    }
}

fn iso_date_prefix(value: &str) -> Option<&str> {
    let date = value.get(..10)?;
    let bytes = date.as_bytes();
    if bytes.len() == 10
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| matches!(index, 4 | 7) || byte.is_ascii_digit())
    {
        Some(date)
    } else {
        None
    }
}

// Kickbase's `dt` market-value field is the number of whole days since
// 1970-01-01. Convert it without adding a date/time dependency just for this
// single compact API representation. Algorithm based on civil-from-days.
fn unix_day_to_iso(days: i64) -> Option<String> {
    if !(-719_162..=2_932_896).contains(&days) {
        return None;
    }

    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let day_of_era = z - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_prime + 2) / 5 + 1;
    let month = month_prime + if month_prime < 10 { 3 } else { -9 };
    year += if month <= 2 { 1 } else { 0 };

    Some(format!("{year:04}-{month:02}-{day:02}"))
}

pub fn parse_player_detail(value: &Value, player_id: &str) -> Result<PlayerDetail, CommandError> {
    let root = value.get("p").filter(|v| v.is_object()).unwrap_or(value);
    Ok(PlayerDetail {
        id: string_value(root, &["i", "pi", "id"]).unwrap_or_else(|| player_id.to_string()),
        name: string_value(root, &["pn", "n", "name"])
            .or_else(|| {
                let first = string_value(root, &["fn", "firstName"]);
                let last = string_value(root, &["ln", "lastName"]);
                match (first, last) {
                    (Some(f), Some(l)) => Some(format!("{f} {l}")),
                    (None, Some(l)) => Some(l),
                    (Some(f), None) => Some(f),
                    _ => None,
                }
            })
            .unwrap_or_else(|| format!("Spieler {player_id}")),
        first_name: string_value(root, &["fn", "firstName"]),
        team_id: string_value(root, &["tid", "ti", "teamId"]),
        club_name: None,
        portrait_data_url: None,
        position: integer_value(root, &["pos", "position"]),
        market_value: integer_value(root, &["mv", "marketValue"]),
        market_value_change_24h: integer_value(root, &["tfhmvt", "marketValueChange24h"]),
        market_value_gain_loss: integer_value(root, &["mvgl", "marketValueGainLoss"]),
        points_total: integer_value(root, &["p", "tp", "points", "totalPoints"]),
        average_points: number_value(root, &["ap", "averagePoints"]),
        status: integer_value(root, &["st", "status"]),
        status_list: status_codes(root),
        status_text: status_text(root),
    })
}

fn status_codes(value: &Value) -> Vec<i64> {
    for key in ["stl", "statusList"] {
        if let Some(items) = value.get(key).and_then(Value::as_array) {
            return items
                .iter()
                .filter_map(|candidate| match candidate {
                    Value::Number(number) => number.as_i64(),
                    Value::String(text) => text.parse::<i64>().ok(),
                    Value::Object(_) => integer_value(candidate, &["st", "status", "i", "id"]),
                    _ => None,
                })
                .collect();
        }
    }
    Vec::new()
}

fn status_text(value: &Value) -> Option<String> {
    string_value(value, &["stxt", "statusText", "status_text"]).or_else(|| {
        value
            .get("stl")
            .and_then(Value::as_array)
            .and_then(|items| {
                let texts = items
                    .iter()
                    .filter_map(|candidate| {
                        string_value(candidate, &["stxt", "txt", "text", "label", "name"])
                    })
                    .collect::<Vec<_>>();
                if texts.is_empty() {
                    None
                } else {
                    Some(texts.join(" · "))
                }
            })
    })
}

pub fn parse_performance(value: &Value) -> Vec<PerformanceEntry> {
    let Some((history, current_day, matchday_status)) = current_season_context(value) else {
        return Vec::new();
    };

    // Kickbase exposes all 34 matchdays in `ph`, including future fixtures with
    // zero-ish placeholder values. `cur` is the current/next matchday and `mdst`
    // describes whether that matchday is upcoming (0), running (1) or finished (2).
    // Only return matchdays that have actually become active.
    let active_through = match (current_day, matchday_status) {
        (Some(day), Some(0)) => day.saturating_sub(1),
        (Some(day), _) => day,
        (None, _) => i64::MAX,
    };

    let mut out = history
        .iter()
        .filter_map(|item| {
            let day = integer_value(item, &["day", "md", "dayNumber"])?;
            if day <= 0 || day > active_through {
                return None;
            }
            Some(PerformanceEntry {
                day_number: day,
                points: integer_value(item, &["p", "points"]),
                minutes: integer_value(item, &["mp", "minutes"]),
                status: integer_value(item, &["st", "status"]),
                home_team_id: string_value(item, &["t1", "homeTeamId"]),
                away_team_id: string_value(item, &["t2", "awayTeamId"]),
                home_goals: integer_value(item, &["t1g", "homeGoals"]),
                away_goals: integer_value(item, &["t2g", "awayGoals"]),
                player_team_id: string_value(item, &["pt", "playerTeamId"]),
            })
        })
        .collect::<Vec<_>>();

    // Fallback for payloads without `cur`: do not surface obvious future fixture
    // placeholders after the last matchday with real activity.
    if current_day.is_none() {
        if let Some(last_active) = out
            .iter()
            .filter(|entry| entry.minutes.unwrap_or(0) > 0 || entry.points.unwrap_or(0) != 0)
            .map(|entry| entry.day_number)
            .max()
        {
            out.retain(|entry| entry.day_number <= last_active);
        }
    }

    out.sort_by_key(|entry| entry.day_number);
    out.dedup_by_key(|entry| entry.day_number);
    out
}

type SeasonHistoryCandidate<'a> = (&'a Vec<Value>, Option<i64>, bool, Option<i64>, Option<i64>);

fn current_season_context(value: &Value) -> Option<(&Vec<Value>, Option<i64>, Option<i64>)> {
    let mut candidates: Vec<SeasonHistoryCandidate<'_>> = Vec::new();
    collect_season_histories(value, &mut candidates);
    if candidates.is_empty() {
        return None;
    }

    candidates.sort_by(|a, b| {
        b.2.cmp(&a.2)
            .then_with(|| b.1.unwrap_or(i64::MIN).cmp(&a.1.unwrap_or(i64::MIN)))
    });
    let (history, _, _, current_day, matchday_status) = candidates[0];
    Some((history, current_day, matchday_status))
}

fn collect_season_histories<'a>(value: &'a Value, out: &mut Vec<SeasonHistoryCandidate<'a>>) {
    match value {
        Value::Object(map) => {
            if let Some(history) = map.get("ph").and_then(Value::as_array) {
                let season = integer_value(value, &["ti", "season", "seasonId"]).or_else(|| {
                    string_value(value, &["ti", "season", "seasonId"]).and_then(|s| {
                        let digits: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
                        digits.parse::<i64>().ok()
                    })
                });
                let current_day = integer_value(value, &["cur", "currentMatchday", "currentDay"]);
                let matchday_status = integer_value(value, &["mdst", "matchdayStatus"]);
                let looks_current = current_day.is_some() || matchday_status.is_some();
                out.push((history, season, looks_current, current_day, matchday_status));
            }
            for child in map.values() {
                collect_season_histories(child, out);
            }
        }
        Value::Array(items) => {
            for child in items {
                collect_season_histories(child, out);
            }
        }
        _ => {}
    }
}

pub fn parse_breakdown(
    value: &Value,
    eventtypes: &Value,
    day_number: i64,
    expected_total_points: Option<i64>,
) -> PerformanceBreakdown {
    let labels = event_type_labels(eventtypes);

    // The authoritative total for the selected bar is the value from the
    // player's current-season `/performance` entry. `playercenter` contains
    // several nested point values and recursively picking the first `p` can
    // produce an off-by-one (or even a completely unrelated subtotal).
    let total_points = expected_total_points;

    let mut raw = Vec::new();
    collect_scoring_events(value, &labels, &mut raw, 0);

    let mut grouped: HashMap<(String, String), BreakdownItem> = HashMap::new();
    for item in raw {
        let key = (item.id.clone(), item.label.clone());
        let slot = grouped.entry(key).or_insert(BreakdownItem {
            id: item.id.clone(),
            label: item.label.clone(),
            points: 0,
            count: Some(0),
        });
        slot.points += item.points;
        slot.count = Some(slot.count.unwrap_or(0) + item.count.unwrap_or(1));
    }

    let mut items = grouped.into_values().collect::<Vec<_>>();
    items.sort_by(|a, b| {
        b.points
            .abs()
            .cmp(&a.points.abs())
            .then(a.label.cmp(&b.label))
    });
    PerformanceBreakdown {
        day_number,
        total_points,
        items,
    }
}

fn event_type_labels(value: &Value) -> HashMap<String, String> {
    let mut out = HashMap::new();
    collect_eventtypes(value, &mut out);
    out
}

fn collect_eventtypes(value: &Value, out: &mut HashMap<String, String>) {
    match value {
        Value::Object(map) => {
            // Current Kickbase event-types payloads are commonly represented by
            // the compact pair `i` / `ti`. Depending on API revision `ti` may be
            // the human-readable title rather than another id. Normalize both
            // compact and verbose variants here.
            let compact_i = string_value(value, &["i"]);
            let compact_ti = string_value(value, &["ti"]);
            let explicit_label = string_value(value, &["n", "name", "txt", "label", "title"]);

            if let Some(label) = explicit_label {
                if let Some(id) = compact_i
                    .clone()
                    .or_else(|| string_value(value, &["id", "typeId"]))
                {
                    out.entry(id).or_insert(label.clone());
                }
                if let Some(id) = compact_ti.clone().filter(|v| looks_like_id(v)) {
                    out.entry(id).or_insert(label);
                }
            } else if let (Some(i), Some(ti)) = (compact_i, compact_ti) {
                match (looks_like_id(&i), looks_like_id(&ti)) {
                    (true, false) => {
                        out.entry(i).or_insert(ti);
                    }
                    (false, true) => {
                        out.entry(ti).or_insert(i);
                    }
                    _ => {}
                }
            }

            for child in map.values() {
                collect_eventtypes(child, out);
            }
        }
        Value::Array(items) => {
            for child in items {
                collect_eventtypes(child, out);
            }
        }
        _ => {}
    }
}

fn collect_scoring_events(
    value: &Value,
    labels: &HashMap<String, String>,
    out: &mut Vec<BreakdownItem>,
    depth: usize,
) {
    if depth > 10 {
        return;
    }

    match value {
        Value::Object(map) => {
            // `i` is important here: playercenter event rows can use the event
            // type id directly as `i`. We only accept it when it resolves
            // against `/v4/live/eventtypes`, so player ids / match ids cannot
            // accidentally become scoring events.
            let event_id = string_value(value, &["eti", "et", "eventTypeId", "typeId", "ti", "i"])
                .filter(|id| labels.contains_key(id));

            if let Some(event_id) = event_id {
                if let Some(points) =
                    integer_value(value, &["p", "pts", "points", "score", "v", "pt"])
                {
                    // A single component can legitimately be sizeable, while a
                    // complete match total must never be parsed as an event.
                    if points.abs() <= 250 {
                        out.push(BreakdownItem {
                            label: labels
                                .get(&event_id)
                                .cloned()
                                .unwrap_or_else(|| event_id.clone()),
                            id: event_id,
                            points,
                            count: integer_value(value, &["c", "cnt", "count", "amount", "n"])
                                .or(Some(1)),
                        });
                    }
                }
            }

            for child in map.values() {
                collect_scoring_events(child, labels, out, depth + 1);
            }
        }
        Value::Array(items) => {
            for child in items {
                collect_scoring_events(child, labels, out, depth + 1);
            }
        }
        _ => {}
    }
}

fn looks_like_id(value: &str) -> bool {
    !value.is_empty() && value.chars().all(|c| c.is_ascii_digit() || c == '-')
}
fn string_value(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|v| match v {
            Value::String(s) if !s.trim().is_empty() => Some(s.clone()),
            Value::Number(n) => Some(n.to_string()),
            _ => None,
        })
    })
}
fn integer_value(value: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|v| match v {
            Value::Number(n) => n.as_i64().or_else(|| integral_f64(n.as_f64()?)),
            Value::String(s) => s
                .parse::<i64>()
                .ok()
                .or_else(|| s.parse::<f64>().ok().and_then(integral_f64)),
            _ => None,
        })
    })
}
fn integral_f64(value: f64) -> Option<i64> {
    if value.is_finite()
        && value.fract() == 0.0
        && value >= i64::MIN as f64
        && value <= i64::MAX as f64
    {
        Some(value as i64)
    } else {
        None
    }
}
fn number_value(value: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|key| {
        value.get(*key).and_then(|v| match v {
            Value::Number(n) => n.as_f64(),
            Value::String(s) => s.parse().ok(),
            _ => None,
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_market_value_history_from_kickbase_days() {
        let payload = json!({
            "it": [
                { "dt": 20717, "mv": 16_018_000 },
                { "dt": 20718, "mv": 15_573_086 },
                { "dt": 20718, "mv": 15_573_000 },
                { "dt": "invalid", "mv": 12_000_000 },
                { "dt": 20719, "mv": 0 }
            ]
        });

        let parsed = parse_market_value_history(&payload);
        assert_eq!(
            parsed,
            vec![
                MarketValueHistoryEntry {
                    date: "2026-09-21".to_owned(),
                    value: 16_018_000
                },
                MarketValueHistoryEntry {
                    date: "2026-09-22".to_owned(),
                    value: 15_573_000
                },
            ]
        );
    }

    #[test]
    fn accepts_iso_dates_when_kickbase_changes_date_encoding() {
        let payload = json!({
            "it": [
                { "date": "2026-09-23T22:00:00Z", "mv": 15_100_000 }
            ]
        });

        assert_eq!(
            parse_market_value_history(&payload),
            vec![MarketValueHistoryEntry {
                date: "2026-09-23".to_owned(),
                value: 15_100_000
            }]
        );
    }

    #[test]
    fn accepts_integral_float_market_values_from_the_live_api() {
        let payload = json!({
            "it": [
                { "dt": 20751, "mv": 23_154_618.0 },
                { "dt": 20750, "mv": 0.0 }
            ]
        });

        assert_eq!(
            parse_market_value_history(&payload),
            vec![MarketValueHistoryEntry {
                date: "2026-10-25".to_owned(),
                value: 23_154_618
            }]
        );
    }
}
