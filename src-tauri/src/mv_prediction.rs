use std::collections::HashMap;

use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};

use crate::kickbase::{error::CommandError, validation::api_id};

const APP_DIR_NAME: &str = "KickTrack";
const DB_FILE_NAME: &str = "kicktrack.db";
const MODEL_NAME: &str = "24h-persistence-calibration";
const MODEL_VERSION: &str = "rust-v2-historical";

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PredictionInput {
    pub player_id: String,
    pub market_value: Option<i64>,
    pub market_value_change_24h: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PredictionOutput {
    pub player_id: String,
    pub delta: Option<i64>,
    pub expected_value: Option<i64>,
    pub low_delta: Option<i64>,
    pub high_delta: Option<i64>,
    pub confidence: String,
    pub sample_count: usize,
    pub history_days: usize,
    pub baseline_delta: Option<i64>,
    pub method: String,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PredictionQuality {
    pub evaluated_count: usize,
    pub direction_hit_rate: Option<f64>,
    pub mae: Option<f64>,
    pub median_abs_error: Option<i64>,
    pub within_100k_rate: Option<f64>,
    pub bias: Option<f64>,
    pub interval_coverage: Option<f64>,
    pub high_confidence_hit_rate: Option<f64>,
    pub high_confidence_count: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PredictionBatch {
    pub target_date: String,
    pub model_name: String,
    pub model_version: String,
    pub predictions: Vec<PredictionOutput>,
    pub quality: PredictionQuality,
}

#[derive(Debug, Clone)]
struct HistoricalSample {
    player_id: String,
    sample_date: String,
    market_value: i64,
    d1: i64,
    error: i64,
}

type QualityRow = (
    i64,
    i64,
    i64,
    i64,
    i64,
    Option<String>,
    Option<i64>,
    Option<i64>,
);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoricalModelSummary {
    pub model_version: String,
    pub historical_samples: usize,
    pub evaluated_samples: usize,
    pub direction_hit_rate: Option<f64>,
    pub mae: Option<f64>,
    pub interval_coverage: Option<f64>,
}

#[tauri::command]
pub async fn rebuild_historical_models(
    league_id: String,
) -> Result<HistoricalModelSummary, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    tauri::async_runtime::spawn_blocking(move || rebuild_historical_models_inner(&league_id))
        .await
        .map_err(|_| {
            CommandError::internal(
                "Das historische Modelltraining konnte nicht abgeschlossen werden.",
            )
        })?
}

#[tauri::command]
pub async fn mv_predictions(
    league_id: String,
    mut inputs: Vec<PredictionInput>,
) -> Result<PredictionBatch, CommandError> {
    let league_id = api_id(&league_id, "Liga-ID")?;
    if inputs.len() > 250 {
        return Err(CommandError::http(
            400,
            "Zu viele Spieler für eine Prognoseabfrage.",
        ));
    }
    for input in &mut inputs {
        input.player_id = api_id(&input.player_id, "Spieler-ID")?;
    }

    tauri::async_runtime::spawn_blocking(move || build_prediction_batch(&league_id, &inputs))
        .await
        .map_err(|_| {
            CommandError::internal("Die Marktwertprognose konnte nicht berechnet werden.")
        })?
}

fn build_prediction_batch(
    league_id: &str,
    inputs: &[PredictionInput],
) -> Result<PredictionBatch, CommandError> {
    let conn = open_database()?;
    ensure_schema(&conn)?;
    evaluate_pending_predictions(&conn, league_id)?;

    let target_date = prediction_target_date(&conn)?;
    let samples = historical_samples(&conn)?;
    let interval_scale = empirical_interval_scale(&conn, league_id)?;

    let mut by_sign: HashMap<i8, Vec<HistoricalSample>> = HashMap::new();
    for sample in samples {
        by_sign.entry(sign(sample.d1)).or_default().push(sample);
    }

    let mut outputs = Vec::with_capacity(inputs.len());
    for input in inputs {
        let player_id = input.player_id.trim();
        if player_id.is_empty() {
            continue;
        }
        let current = match input.market_value {
            Some(value) if value > 0 => value,
            _ => continue,
        };
        let history_days = history_days(&conn, player_id)?;
        let latest_delta = match input.market_value_change_24h {
            Some(delta) => delta,
            None => match latest_completed_delta(&conn, player_id)? {
                Some(delta) => delta,
                None => {
                    outputs.push(PredictionOutput {
                        player_id: player_id.to_owned(),
                        delta: None,
                        expected_value: None,
                        low_delta: None,
                        high_delta: None,
                        confidence: "UNSICHER".to_string(),
                        sample_count: 0,
                        history_days,
                        baseline_delta: None,
                        method: "24h persistence + historical calibration".to_string(),
                    });
                    continue;
                }
            },
        };

        let magnitude = latest_delta.abs().max(1);
        let sample_sign = sign(latest_delta);
        let bucket: &[HistoricalSample] =
            by_sign.get(&sample_sign).map(Vec::as_slice).unwrap_or(&[]);
        let mut analogs: Vec<&HistoricalSample> = bucket
            .iter()
            .filter(|sample| {
                let sample_magnitude = sample.d1.abs();
                sample_magnitude as f64 >= magnitude as f64 * 0.50
                    && sample_magnitude as f64 <= magnitude as f64 * 1.50
                    && sample.market_value as f64 >= current as f64 * 0.40
                    && sample.market_value as f64 <= current as f64 * 2.50
            })
            .collect();
        if analogs.len() < 20 {
            analogs = bucket
                .iter()
                .filter(|sample| {
                    let sample_magnitude = sample.d1.abs();
                    sample_magnitude as f64 >= magnitude as f64 * 0.40
                        && sample_magnitude as f64 <= magnitude as f64 * 1.80
                })
                .collect();
        }

        let mut errors: Vec<i64> = analogs.iter().map(|sample| sample.error).collect();
        let raw_bias = median_i64(&mut errors).unwrap_or(0);
        let bias_cap = 25_000_i64.max((magnitude as f64 * 0.20).round() as i64);
        let bias = raw_bias.clamp(-bias_cap, bias_cap);
        let prediction = latest_delta.saturating_add(bias);

        let mut abs_errors: Vec<i64> = analogs.iter().map(|sample| sample.error.abs()).collect();
        let base_radius = if abs_errors.is_empty() {
            75_000_i64.max((magnitude as f64 * 0.60).round() as i64)
        } else {
            percentile_i64(&mut abs_errors, 0.80)
        };
        let radius = ((base_radius.max(25_000) as f64) * interval_scale).round() as i64;
        let low = prediction.saturating_sub(radius);
        let high = prediction.saturating_add(radius);

        let recent = recent_market_value_deltas(&conn, player_id, 3)?;
        let same_direction = recent
            .iter()
            .filter(|delta| sign(**delta) == sample_sign)
            .count();
        let ratio = radius as f64 / (prediction.abs().max(50_000) as f64);
        let has_live_signal = input.market_value_change_24h.is_some();
        let confidence = if has_live_signal
            && history_days >= 4
            && analogs.len() >= 50
            && same_direction >= 2
            && ratio <= 0.85
        {
            "HOCH"
        } else if (has_live_signal && analogs.len() >= 20 && ratio <= 1.35)
            || (history_days >= 4 && analogs.len() >= 12 && ratio <= 1.60)
        {
            "MITTEL"
        } else {
            "UNSICHER"
        };

        outputs.push(PredictionOutput {
            player_id: player_id.to_owned(),
            delta: Some(prediction),
            expected_value: Some(current.saturating_add(prediction).max(0)),
            low_delta: Some(low),
            high_delta: Some(high),
            confidence: confidence.to_string(),
            sample_count: analogs.len(),
            history_days,
            baseline_delta: Some(latest_delta),
            method: if interval_scale > 1.01 {
                "24h persistence + historical calibration + empirical interval calibration"
                    .to_string()
            } else {
                "24h persistence + historical calibration".to_string()
            },
        });
    }

    record_predictions(&conn, league_id, &target_date, &outputs)?;
    let quality = prediction_quality(&conn, league_id)?;

    #[cfg(debug_assertions)]
    crate::kt_debug!(
        "[KickTrack][DEBUG][mv-prediction] league={} target={} players={} evaluated={} mae={:?} direction={:?}% interval={:?}% scale={:.3}",
        league_id,
        target_date,
        outputs.len(),
        quality.evaluated_count,
        quality.mae,
        quality.direction_hit_rate.map(|v| v * 100.0),
        quality.interval_coverage.map(|v| v * 100.0),
        interval_scale,
    );

    Ok(PredictionBatch {
        target_date,
        model_name: MODEL_NAME.to_string(),
        model_version: MODEL_VERSION.to_string(),
        predictions: outputs,
        quality,
    })
}

#[derive(Debug, Clone, Copy, Default)]
struct RunningStats {
    count: usize,
    sum_error: i128,
    sum_abs_error: i128,
}

impl RunningStats {
    fn add(&mut self, error: i64) {
        self.count += 1;
        self.sum_error += error as i128;
        self.sum_abs_error += error.abs() as i128;
    }

    fn mean_error(&self) -> i64 {
        if self.count == 0 {
            0
        } else {
            (self.sum_error / self.count as i128) as i64
        }
    }

    fn interval_radius(&self) -> i64 {
        if self.count == 0 {
            return 75_000;
        }
        // A robust, cheap walk-forward interval approximation. The live model
        // still uses empirical percentiles; the historical rebuild must stay O(n).
        (((self.sum_abs_error as f64 / self.count as f64) * 1.35).round() as i64).max(25_000)
    }
}

fn rebuild_historical_models_inner(
    league_id: &str,
) -> Result<HistoricalModelSummary, CommandError> {
    let mut conn = open_database()?;
    ensure_schema(&conn)?;
    let mut samples = historical_samples(&conn)?;
    samples.sort_by(|a, b| {
        a.sample_date
            .cmp(&b.sample_date)
            .then_with(|| a.player_id.cmp(&b.player_id))
    });

    conn.execute(
        "DELETE FROM vnext_market_value_predictions WHERE run_id IN (SELECT id FROM vnext_prediction_runs WHERE league_id=?1 AND model_version=?2 AND id LIKE 'backfill:%')",
        params![league_id, MODEL_VERSION],
    ).map_err(|_| CommandError::internal("Alte historische Backtests konnten nicht entfernt werden."))?;
    conn.execute(
        "DELETE FROM vnext_prediction_runs WHERE league_id=?1 AND model_version=?2 AND id LIKE 'backfill:%'",
        params![league_id, MODEL_VERSION],
    ).map_err(|_| CommandError::internal("Alte historische Backtest-Runs konnten nicht entfernt werden."))?;

    let tx = conn.transaction().map_err(|_| {
        CommandError::internal("Historisches Training konnte nicht gestartet werden.")
    })?;
    let mut learned: HashMap<(i8, i32, i32), RunningStats> = HashMap::new();
    let mut by_sign: HashMap<i8, RunningStats> = HashMap::new();
    let mut evaluated = 0usize;
    let mut index = 0usize;

    while index < samples.len() {
        let day = samples[index].sample_date.clone();
        let mut end = index + 1;
        while end < samples.len() && samples[end].sample_date == day {
            end += 1;
        }

        let run_id = format!("backfill:{}:{}:{}", MODEL_VERSION, league_id, day);
        tx.execute(
            "INSERT OR REPLACE INTO vnext_prediction_runs(id,league_id,model_name,model_version,target_date,created_at,parameters_json) VALUES(?1,?2,?3,?4,?5,datetime('now'),'{\"validation\":\"walk-forward\",\"no_future_data\":true,\"aggregation\":\"running-buckets\"}')",
            params![run_id, league_id, MODEL_NAME, MODEL_VERSION, day],
        ).map_err(|_| CommandError::internal("Historischer Prediction-Run konnte nicht gespeichert werden."))?;

        for sample in &samples[index..end] {
            let key = analog_key(sample.d1, sample.market_value);
            let bucket = learned.get(&key).copied().unwrap_or_default();
            let fallback = by_sign.get(&sign(sample.d1)).copied().unwrap_or_default();
            let stats = if bucket.count >= 20 { bucket } else { fallback };
            if stats.count < 12 {
                continue;
            }

            let magnitude = sample.d1.abs().max(1);
            let raw_bias = stats.mean_error();
            let bias_cap = 25_000_i64.max((magnitude as f64 * 0.20).round() as i64);
            let predicted_delta = sample
                .d1
                .saturating_add(raw_bias.clamp(-bias_cap, bias_cap));
            let actual_delta = sample.d1.saturating_add(sample.error);
            let radius = stats.interval_radius();
            let low = predicted_delta.saturating_sub(radius);
            let high = predicted_delta.saturating_add(radius);
            let absolute_error = predicted_delta.saturating_sub(actual_delta).abs();
            let signed_error = predicted_delta.saturating_sub(actual_delta);
            let direction_hit = if sign(predicted_delta) == sign(actual_delta) {
                1
            } else {
                0
            };
            let confidence = if stats.count >= 75
                && radius as f64 / predicted_delta.abs().max(50_000) as f64 <= 0.9
            {
                "HOCH"
            } else if stats.count >= 30 {
                "MITTEL"
            } else {
                "UNSICHER"
            };
            let target_value = sample.market_value.saturating_add(actual_delta).max(0);

            tx.execute(
                "INSERT OR REPLACE INTO vnext_market_value_predictions(run_id,league_id,player_id,target_date,predicted_at,baseline_value,baseline_delta,predicted_delta,expected_value,low_delta,high_delta,confidence,sample_count,history_days,method,actual_value,actual_delta,absolute_error,signed_error,direction_hit,evaluated_at) VALUES(?1,?2,?3,?4,datetime('now'),?5,?6,?7,?8,?9,?10,?11,?12,0,'walk-forward historical calibration',?13,?14,?15,?16,?17,datetime('now'))",
                params![run_id, league_id, sample.player_id, sample.sample_date, sample.market_value, sample.d1, predicted_delta, sample.market_value.saturating_add(predicted_delta).max(0), low, high, confidence, stats.count as i64, target_value, actual_delta, absolute_error, signed_error, direction_hit],
            ).map_err(|_| CommandError::internal("Historische Prediction konnte nicht gespeichert werden."))?;
            evaluated += 1;
        }

        // Learn a day only after all predictions for that day were produced.
        // This is the crucial no-future-data boundary of the walk-forward test.
        for sample in &samples[index..end] {
            learned
                .entry(analog_key(sample.d1, sample.market_value))
                .or_default()
                .add(sample.error);
            by_sign
                .entry(sign(sample.d1))
                .or_default()
                .add(sample.error);
        }
        index = end;
    }

    tx.commit().map_err(|_| {
        CommandError::internal("Historisches Training konnte nicht gespeichert werden.")
    })?;
    let quality = prediction_quality(&conn, league_id)?;

    #[cfg(debug_assertions)]
    crate::kt_debug!("[KickTrack][DEBUG][model-rebuild] league={} samples={} evaluated={} direction={:?}% mae={:?}", league_id, samples.len(), evaluated, quality.direction_hit_rate.map(|v| v*100.0), quality.mae);

    Ok(HistoricalModelSummary {
        model_version: MODEL_VERSION.to_string(),
        historical_samples: samples.len(),
        evaluated_samples: evaluated,
        direction_hit_rate: quality.direction_hit_rate,
        mae: quality.mae,
        interval_coverage: quality.interval_coverage,
    })
}

fn analog_key(delta: i64, market_value: i64) -> (i8, i32, i32) {
    let magnitude_bucket = (delta.abs() / 100_000).min(40) as i32;
    let value_bucket = (market_value / 5_000_000).min(40) as i32;
    (sign(delta), magnitude_bucket, value_bucket)
}

fn open_database() -> Result<Connection, CommandError> {
    let base = dirs::data_dir().ok_or_else(|| {
        CommandError::internal("Der Windows AppData-Ordner konnte nicht ermittelt werden.")
    })?;
    let db_path = base.join(APP_DIR_NAME).join(DB_FILE_NAME);
    let conn = Connection::open(db_path).map_err(|_| {
        CommandError::internal(
            "Die KickTrack-Datenbank konnte für die Prognose nicht geöffnet werden.",
        )
    })?;
    conn.busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|_| {
            CommandError::internal("SQLite konnte für die Prognose nicht initialisiert werden.")
        })?;
    Ok(conn)
}

fn ensure_schema(conn: &Connection) -> Result<(), CommandError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS vnext_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
         );
         CREATE TABLE IF NOT EXISTS vnext_prediction_runs (
            id TEXT PRIMARY KEY,
            league_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            target_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            parameters_json TEXT
         );
         CREATE INDEX IF NOT EXISTS idx_vnext_prediction_runs_target
         ON vnext_prediction_runs(league_id, target_date DESC);
         CREATE TABLE IF NOT EXISTS vnext_market_value_predictions (
            run_id TEXT NOT NULL,
            league_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            target_date TEXT NOT NULL,
            predicted_at TEXT NOT NULL,
            baseline_value INTEGER NOT NULL,
            baseline_delta INTEGER,
            predicted_delta INTEGER NOT NULL,
            expected_value INTEGER NOT NULL,
            low_delta INTEGER,
            high_delta INTEGER,
            confidence TEXT,
            sample_count INTEGER,
            history_days INTEGER,
            method TEXT,
            actual_value INTEGER,
            actual_delta INTEGER,
            absolute_error INTEGER,
            signed_error INTEGER,
            direction_hit INTEGER,
            evaluated_at TEXT,
            PRIMARY KEY(run_id, player_id),
            FOREIGN KEY(run_id) REFERENCES vnext_prediction_runs(id) ON DELETE CASCADE
         );
         CREATE INDEX IF NOT EXISTS idx_vnext_mv_predictions_eval
         ON vnext_market_value_predictions(league_id, evaluated_at, target_date DESC);",
    )
    .map_err(|_| {
        CommandError::internal("Das Prediction-Schema konnte nicht vorbereitet werden.")
    })?;

    let migration_exists: Option<i64> = conn
        .query_row(
            "SELECT version FROM vnext_schema_migrations WHERE version = 4",
            [],
            |row| row.get(0),
        )
        .optional()
        .map_err(|_| {
            CommandError::internal("Der Prediction-Migrationsstand konnte nicht gelesen werden.")
        })?;

    if migration_exists.is_none() {
        let legacy_exists: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='mv_predictions'",
                [],
                |row| row.get(0),
            )
            .unwrap_or(0);
        if legacy_exists > 0 {
            conn.execute_batch(
                "INSERT OR IGNORE INTO vnext_prediction_runs(id, league_id, model_name, model_version, target_date, created_at, parameters_json)
                 SELECT 'legacy:' || league_id || ':' || target_date,
                        league_id,
                        '24h-persistence-calibration',
                        'python-v1',
                        target_date,
                        MIN(predicted_at),
                        '{\"source\":\"legacy mv_predictions\"}'
                 FROM mv_predictions
                 GROUP BY league_id, target_date;

                 INSERT OR IGNORE INTO vnext_market_value_predictions(
                    run_id, league_id, player_id, target_date, predicted_at,
                    baseline_value, baseline_delta, predicted_delta, expected_value,
                    low_delta, high_delta, confidence, sample_count, history_days, method,
                    actual_value, actual_delta, absolute_error, signed_error, direction_hit, evaluated_at
                 )
                 SELECT 'legacy:' || league_id || ':' || target_date,
                        league_id, player_id, target_date, predicted_at,
                        baseline_value, baseline_delta, predicted_delta, expected_value,
                        low_delta, high_delta, confidence, sample_count, history_days, method,
                        actual_value, actual_delta, absolute_error, signed_error, direction_hit, evaluated_at
                 FROM mv_predictions;",
            )
            .map_err(|_| CommandError::internal("Die historischen Prognosen konnten nicht in vNext übernommen werden."))?;
        }
        conn.execute(
            "INSERT INTO vnext_schema_migrations(version, applied_at) VALUES(4, datetime('now'))",
            [],
        )
        .map_err(|_| {
            CommandError::internal("Die Prediction-Migration konnte nicht abgeschlossen werden.")
        })?;
    }
    Ok(())
}

fn historical_samples(conn: &Connection) -> Result<Vec<HistoricalSample>, CommandError> {
    let mut stmt = conn.prepare(
        "WITH daily AS (
           SELECT player_id, snapshot_date, value,
                  LAG(snapshot_date) OVER(PARTITION BY player_id ORDER BY snapshot_date) AS prev_date,
                  LAG(value) OVER(PARTITION BY player_id ORDER BY snapshot_date) AS prev_value,
                  LEAD(snapshot_date) OVER(PARTITION BY player_id ORDER BY snapshot_date) AS next_date,
                  LEAD(value) OVER(PARTITION BY player_id ORDER BY snapshot_date) AS next_value
           FROM market_values
           WHERE snapshot_date IS NOT NULL AND value > 0
         ), newest AS (SELECT MAX(snapshot_date) AS newest_day FROM market_values)
         SELECT player_id, snapshot_date, value, value - prev_value AS d1, (next_value - value) - (value - prev_value) AS error
         FROM daily, newest
         WHERE prev_value IS NOT NULL AND next_value IS NOT NULL
           AND julianday(snapshot_date) - julianday(prev_date) = 1
           AND julianday(next_date) - julianday(snapshot_date) = 1
           AND next_date <> newest_day"
    ).map_err(|_| CommandError::internal("Die historische Prediction-Basis konnte nicht vorbereitet werden."))?;
    let rows = stmt
        .query_map([], |row| {
            Ok(HistoricalSample {
                player_id: row.get(0)?,
                sample_date: row.get(1)?,
                market_value: row.get(2)?,
                d1: row.get(3)?,
                error: row.get(4)?,
            })
        })
        .map_err(|_| {
            CommandError::internal("Die historische Prediction-Basis konnte nicht gelesen werden.")
        })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(|_| {
        CommandError::internal("Die historische Prediction-Basis konnte nicht gelesen werden.")
    })
}

fn history_days(conn: &Connection, player_id: &str) -> Result<usize, CommandError> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(DISTINCT snapshot_date) FROM market_values WHERE player_id=?1 AND snapshot_date IS NOT NULL AND value>0",
        [player_id],
        |row| row.get(0),
    ).map_err(|_| CommandError::internal("Die Historientiefe konnte nicht gelesen werden."))?;
    Ok(count.max(0) as usize)
}

fn latest_completed_delta(conn: &Connection, player_id: &str) -> Result<Option<i64>, CommandError> {
    conn.query_row(
        "WITH daily AS (
           SELECT snapshot_date, value,
                  LAG(snapshot_date) OVER(ORDER BY snapshot_date) AS prev_date,
                  LAG(value) OVER(ORDER BY snapshot_date) AS prev_value
           FROM market_values WHERE player_id=?1 AND snapshot_date IS NOT NULL AND value>0
         )
         SELECT value-prev_value FROM daily
         WHERE prev_value IS NOT NULL AND julianday(snapshot_date)-julianday(prev_date)=1
         ORDER BY snapshot_date DESC LIMIT 1",
        [player_id],
        |row| row.get(0),
    )
    .optional()
    .map_err(|_| {
        CommandError::internal("Der letzte abgeschlossene MW-Schritt konnte nicht gelesen werden.")
    })
}

fn recent_market_value_deltas(
    conn: &Connection,
    player_id: &str,
    limit: usize,
) -> Result<Vec<i64>, CommandError> {
    let mut stmt = conn
        .prepare(
            "WITH daily AS (
           SELECT snapshot_date, value,
                  LAG(snapshot_date) OVER(ORDER BY snapshot_date) AS prev_date,
                  LAG(value) OVER(ORDER BY snapshot_date) AS prev_value
           FROM market_values WHERE player_id=?1 AND snapshot_date IS NOT NULL AND value>0
         )
         SELECT value-prev_value FROM daily
         WHERE prev_value IS NOT NULL AND julianday(snapshot_date)-julianday(prev_date)=1
         ORDER BY snapshot_date DESC LIMIT ?2",
        )
        .map_err(|_| {
            CommandError::internal("Die letzten MW-Schritte konnten nicht vorbereitet werden.")
        })?;
    let rows = stmt
        .query_map(params![player_id, limit as i64], |row| row.get::<_, i64>(0))
        .map_err(|_| {
            CommandError::internal("Die letzten MW-Schritte konnten nicht gelesen werden.")
        })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(|_| {
        CommandError::internal("Die letzten MW-Schritte konnten nicht gelesen werden.")
    })
}

fn prediction_target_date(conn: &Connection) -> Result<String, CommandError> {
    conn.query_row(
        "SELECT CASE WHEN CAST(strftime('%H','now','localtime') AS INTEGER) < 22
                     THEN date('now','localtime') ELSE date('now','localtime','+1 day') END",
        [],
        |row| row.get(0),
    )
    .map_err(|_| {
        CommandError::internal(
            "Das Ziel des nächsten 22-Uhr-Refreshs konnte nicht bestimmt werden.",
        )
    })
}

fn evaluation_through_date(conn: &Connection) -> Result<String, CommandError> {
    conn.query_row(
        "SELECT CASE WHEN CAST(strftime('%H','now','localtime') AS INTEGER) >= 22
                     THEN date('now','localtime') ELSE date('now','localtime','-1 day') END",
        [],
        |row| row.get(0),
    )
    .map_err(|_| {
        CommandError::internal("Der letzte abgeschlossene Refresh konnte nicht bestimmt werden.")
    })
}

fn record_predictions(
    conn: &Connection,
    league_id: &str,
    target_date: &str,
    outputs: &[PredictionOutput],
) -> Result<(), CommandError> {
    let run_id = format!("{}:{}:{}", MODEL_VERSION, league_id, target_date);
    conn.execute(
        "INSERT INTO vnext_prediction_runs(id, league_id, model_name, model_version, target_date, created_at, parameters_json)
         VALUES(?1,?2,?3,?4,?5,datetime('now'),'{\"calibration\":\"historical analogs\"}')
         ON CONFLICT(id) DO UPDATE SET created_at=datetime('now')",
        params![run_id, league_id, MODEL_NAME, MODEL_VERSION, target_date],
    ).map_err(|_| CommandError::internal("Der Prediction-Run konnte nicht gespeichert werden."))?;

    for output in outputs {
        let (delta, expected) = match (output.delta, output.expected_value) {
            (Some(delta), Some(expected)) => (delta, expected),
            _ => continue,
        };
        let baseline_value = expected.saturating_sub(delta);
        conn.execute(
            "INSERT INTO vnext_market_value_predictions(
               run_id,league_id,player_id,target_date,predicted_at,
               baseline_value,baseline_delta,predicted_delta,expected_value,
               low_delta,high_delta,confidence,sample_count,history_days,method
             ) VALUES(?1,?2,?3,?4,datetime('now'),?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)
             ON CONFLICT(run_id,player_id) DO UPDATE SET
               predicted_at=datetime('now'), baseline_value=excluded.baseline_value,
               baseline_delta=excluded.baseline_delta, predicted_delta=excluded.predicted_delta,
               expected_value=excluded.expected_value, low_delta=excluded.low_delta,
               high_delta=excluded.high_delta, confidence=excluded.confidence,
               sample_count=excluded.sample_count, history_days=excluded.history_days,
               method=excluded.method, actual_value=NULL, actual_delta=NULL,
               absolute_error=NULL, signed_error=NULL, direction_hit=NULL, evaluated_at=NULL",
            params![
                run_id,
                league_id,
                output.player_id,
                target_date,
                baseline_value,
                output.baseline_delta,
                delta,
                expected,
                output.low_delta,
                output.high_delta,
                output.confidence,
                output.sample_count as i64,
                output.history_days as i64,
                output.method,
            ],
        )
        .map_err(|_| {
            CommandError::internal("Die Marktwertprognose konnte nicht gespeichert werden.")
        })?;
    }
    Ok(())
}

fn evaluate_pending_predictions(conn: &Connection, league_id: &str) -> Result<(), CommandError> {
    let through = evaluation_through_date(conn)?;
    let mut stmt = conn
        .prepare(
            "SELECT run_id, player_id, target_date, baseline_value, predicted_delta
         FROM vnext_market_value_predictions
         WHERE league_id=?1 AND evaluated_at IS NULL AND target_date<=?2",
        )
        .map_err(|_| {
            CommandError::internal("Offene Prognosen konnten nicht vorbereitet werden.")
        })?;
    let rows = stmt
        .query_map(params![league_id, through], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, i64>(4)?,
            ))
        })
        .map_err(|_| CommandError::internal("Offene Prognosen konnten nicht gelesen werden."))?;
    let pending = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| CommandError::internal("Offene Prognosen konnten nicht gelesen werden."))?;

    for (run_id, player_id, target_date, baseline, predicted_delta) in pending {
        let actual: Option<i64> = conn.query_row(
            "SELECT value FROM market_values WHERE player_id=?1 AND snapshot_date=?2 ORDER BY recorded_at DESC,id DESC LIMIT 1",
            params![player_id, target_date],
            |row| row.get(0),
        ).optional().map_err(|_| CommandError::internal("Der tatsächliche Marktwert konnte nicht gelesen werden."))?;
        let Some(actual_value) = actual.filter(|value| *value > 0) else {
            continue;
        };
        let actual_delta = actual_value.saturating_sub(baseline);
        let signed_error = predicted_delta.saturating_sub(actual_delta);
        let absolute_error = signed_error.abs();
        let direction_hit = if sign(predicted_delta) == sign(actual_delta) {
            1
        } else {
            0
        };
        conn.execute(
            "UPDATE vnext_market_value_predictions SET actual_value=?1,actual_delta=?2,absolute_error=?3,signed_error=?4,direction_hit=?5,evaluated_at=datetime('now') WHERE run_id=?6 AND player_id=?7",
            params![actual_value, actual_delta, absolute_error, signed_error, direction_hit, run_id, player_id],
        ).map_err(|_| CommandError::internal("Eine Prognose konnte nicht ausgewertet werden."))?;
    }
    Ok(())
}

fn prediction_quality(
    conn: &Connection,
    league_id: &str,
) -> Result<PredictionQuality, CommandError> {
    let mut stmt = conn.prepare(
        "SELECT predicted_delta,actual_delta,absolute_error,signed_error,direction_hit,confidence,low_delta,high_delta
         FROM vnext_market_value_predictions p
         JOIN vnext_prediction_runs r ON r.id=p.run_id
         WHERE p.league_id=?1 AND p.evaluated_at IS NOT NULL AND r.model_name=?2 AND r.model_version=?3
         ORDER BY p.target_date DESC"
    ).map_err(|_| CommandError::internal("Die Modellgüte konnte nicht vorbereitet werden."))?;
    let rows = stmt
        .query_map(params![league_id, MODEL_NAME, MODEL_VERSION], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<i64>>(6)?,
                row.get::<_, Option<i64>>(7)?,
            ))
        })
        .map_err(|_| CommandError::internal("Die Modellgüte konnte nicht gelesen werden."))?;
    let data = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| CommandError::internal("Die Modellgüte konnte nicht gelesen werden."))?;
    if data.is_empty() {
        return Ok(PredictionQuality::default());
    }

    let n = data.len();
    let direction_hits = data.iter().filter(|row| row.4 == 1).count();
    let mae = data.iter().map(|row| row.2 as f64).sum::<f64>() / n as f64;
    let mut abs_errors: Vec<i64> = data.iter().map(|row| row.2).collect();
    let median_abs_error = median_i64(&mut abs_errors);
    let within_100k = data.iter().filter(|row| row.2 <= 100_000).count();
    let bias = data.iter().map(|row| row.3 as f64).sum::<f64>() / n as f64;
    let interval_rows: Vec<&QualityRow> = data
        .iter()
        .filter(|row| row.6.is_some() && row.7.is_some())
        .collect();
    let interval_hits = interval_rows
        .iter()
        .filter(|row| {
            let low = row.6.unwrap_or(i64::MIN);
            let high = row.7.unwrap_or(i64::MAX);
            row.1 >= low && row.1 <= high
        })
        .count();
    let high_rows: Vec<_> = data
        .iter()
        .filter(|row| row.5.as_deref() == Some("HOCH"))
        .collect();
    let high_hits = high_rows.iter().filter(|row| row.4 == 1).count();

    Ok(PredictionQuality {
        evaluated_count: n,
        direction_hit_rate: Some(direction_hits as f64 / n as f64),
        mae: Some(mae),
        median_abs_error,
        within_100k_rate: Some(within_100k as f64 / n as f64),
        bias: Some(bias),
        interval_coverage: if interval_rows.is_empty() {
            None
        } else {
            Some(interval_hits as f64 / interval_rows.len() as f64)
        },
        high_confidence_hit_rate: if high_rows.is_empty() {
            None
        } else {
            Some(high_hits as f64 / high_rows.len() as f64)
        },
        high_confidence_count: high_rows.len(),
    })
}

fn empirical_interval_scale(conn: &Connection, league_id: &str) -> Result<f64, CommandError> {
    let quality = prediction_quality(conn, league_id)?;
    if quality.evaluated_count < 100 {
        return Ok(1.0);
    }
    let Some(coverage) = quality.interval_coverage else {
        return Ok(1.0);
    };
    if coverage >= 0.78 {
        return Ok(1.0);
    }
    Ok((0.80 / coverage.max(0.50)).clamp(1.0, 1.40))
}

fn sign(value: i64) -> i8 {
    if value > 0 {
        1
    } else if value < 0 {
        -1
    } else {
        0
    }
}

fn median_i64(values: &mut [i64]) -> Option<i64> {
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    let mid = values.len() / 2;
    if values.len() % 2 == 1 {
        Some(values[mid])
    } else {
        Some(((values[mid - 1] as i128 + values[mid] as i128) / 2) as i64)
    }
}

fn percentile_i64(values: &mut [i64], q: f64) -> i64 {
    if values.is_empty() {
        return 0;
    }
    values.sort_unstable();
    if values.len() == 1 {
        return values[0];
    }
    let pos = q.clamp(0.0, 1.0) * (values.len() - 1) as f64;
    let lo = pos.floor() as usize;
    let hi = (lo + 1).min(values.len() - 1);
    let frac = pos - lo as f64;
    (values[lo] as f64 * (1.0 - frac) + values[hi] as f64 * frac).round() as i64
}
