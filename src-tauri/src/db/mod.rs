use std::{collections::HashMap, fs, path::{Path, PathBuf}};

use base64::{engine::general_purpose::STANDARD, Engine as _};
use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use crate::kickbase::{error::CommandError, league::LeagueManager};

const DB_FILE_NAME: &str = "kicktrack.db";
const APP_DIR_NAME: &str = "KickTrack";

mod migrations;
mod portraits;
mod transfers;

#[derive(Debug, Clone)]
pub struct PlayerEnrichment {
    pub first_name: Option<String>,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub portrait_data_url: Option<String>,
    pub team_logo_remote_path: Option<String>,
    pub team_logo_local_path: Option<String>,
}

#[derive(Debug, Clone)]
pub struct PortraitPlayer {
    pub player_id: String,
    pub display_name: String,
    pub full_name: Option<String>,
    pub club_name: Option<String>,
    pub fotmob_id: Option<String>,
    pub portrait_url: Option<String>,
    pub portrait_path: Option<String>,
    pub portrait_state: String,
    pub portrait_confidence: Option<i64>,
    pub portrait_reason: Option<String>,
    pub candidate_name: Option<String>,
    pub candidate_team: Option<String>,
    pub candidate_position: Option<String>,
    pub candidate_shirt_number: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PortraitReviewItem {
    pub player_id: String,
    pub player_name: String,
    pub club_name: Option<String>,
    pub fotmob_id: Option<String>,
    pub portrait_url: Option<String>,
    pub confidence: Option<i64>,
    pub reason: Option<String>,
    pub candidate_name: Option<String>,
    pub candidate_team: Option<String>,
    pub candidate_position: Option<String>,
    pub candidate_shirt_number: Option<String>,
}

#[derive(Debug, Clone)]
pub struct TransferEventRow {
    pub league_id: String,
    pub manager_id: String,
    pub player_id: String,
    pub player_name: String,
    pub team_id: Option<String>,
    pub club_name: Option<String>,
    pub transfer_type: String,
    pub price: i64,
    pub transferred_at: String,
}

pub struct KickTrackDatabase {
    conn: Connection,
    app_dir: PathBuf,
}

impl KickTrackDatabase {
    pub fn open_default() -> Result<Self, CommandError> {
        let base = dirs::data_dir().ok_or_else(|| {
            CommandError::internal("Der Windows AppData-Ordner konnte nicht ermittelt werden.")
        })?;
        let app_dir = base.join(APP_DIR_NAME);
        fs::create_dir_all(&app_dir)
            .map_err(|_| CommandError::internal("Der KickTrack-Datenordner konnte nicht geöffnet werden."))?;

        let db_path = app_dir.join(DB_FILE_NAME);
        let conn = Connection::open(&db_path)
            .map_err(|_| CommandError::internal("Die bestehende KickTrack-Datenbank konnte nicht geöffnet werden."))?;
        conn.pragma_update(None, "foreign_keys", "ON")
            .map_err(|_| CommandError::internal("SQLite konnte nicht initialisiert werden."))?;
        conn.busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|_| CommandError::internal("SQLite konnte nicht initialisiert werden."))?;

        let mut db = Self { conn, app_dir };
        db.run_migrations()?;
        Ok(db)
    }


    pub fn league_managers(&self, league_id: &str) -> Result<Vec<LeagueManager>, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT m.id, m.name, m.profile_image_remote_path, m.is_self,\n                    s.team_value, s.profit, s.points, s.average_points, s.matchday_wins, s.place\n             FROM vnext_managers m\n             LEFT JOIN vnext_manager_snapshots s\n               ON s.league_id = m.league_id AND s.manager_id = m.id\n              AND s.snapshot_date = (\n                SELECT MAX(s2.snapshot_date) FROM vnext_manager_snapshots s2\n                WHERE s2.league_id = m.league_id AND s2.manager_id = m.id\n              )\n             WHERE m.league_id = ?1\n             ORDER BY COALESCE(s.place, 999999), lower(m.name)"
        ).map_err(|_| CommandError::internal("Liga-Manager konnten nicht aus der Datenbank gelesen werden."))?;

        let rows = stmt.query_map([league_id], |row| {
            Ok(LeagueManager {
                id: row.get(0)?,
                name: row.get(1)?,
                profile_image_path: row.get(2)?,
                is_self: row.get::<_, i64>(3)? != 0,
                team_value: row.get(4)?,
                profit: row.get(5)?,
                points: row.get(6)?,
                current_matchday_points: None,
                average_points: row.get(7)?,
                matchday_wins: row.get(8)?,
                place: row.get(9)?,
            })
        }).map_err(|_| CommandError::internal("Liga-Manager konnten nicht aus der Datenbank gelesen werden."))?;

        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Liga-Manager konnten nicht aus der Datenbank gelesen werden."))
    }

    pub fn upsert_league_managers(&mut self, league_id: &str, managers: &[LeagueManager]) -> Result<(), CommandError> {
        let tx = self.conn.transaction()
            .map_err(|_| CommandError::internal("Liga-Daten konnten nicht gespeichert werden."))?;

        for manager in managers {
            tx.execute(
                "INSERT INTO vnext_managers (league_id, id, name, profile_image_remote_path, is_self, updated_at)\n                 VALUES (?1, ?2, ?3, ?4, ?5, datetime('now'))\n                 ON CONFLICT(league_id, id) DO UPDATE SET\n                   name = excluded.name,\n                   profile_image_remote_path = COALESCE(excluded.profile_image_remote_path, vnext_managers.profile_image_remote_path),\n                   is_self = MAX(vnext_managers.is_self, excluded.is_self),\n                   updated_at = datetime('now')",
                params![league_id, manager.id, manager.name, manager.profile_image_path, if manager.is_self { 1 } else { 0 }],
            ).map_err(|_| CommandError::internal("Liga-Manager konnten nicht gespeichert werden."))?;

            tx.execute(
                "INSERT INTO vnext_manager_snapshots\n                   (league_id, manager_id, snapshot_date, team_value, profit, points, average_points, matchday_wins, place, recorded_at)\n                 VALUES (?1, ?2, date('now'), ?3, ?4, ?5, ?6, ?7, ?8, datetime('now'))\n                 ON CONFLICT(league_id, manager_id, snapshot_date) DO UPDATE SET\n                   team_value = COALESCE(excluded.team_value, vnext_manager_snapshots.team_value),\n                   profit = COALESCE(excluded.profit, vnext_manager_snapshots.profit),\n                   points = COALESCE(excluded.points, vnext_manager_snapshots.points),\n                   average_points = COALESCE(excluded.average_points, vnext_manager_snapshots.average_points),\n                   matchday_wins = COALESCE(excluded.matchday_wins, vnext_manager_snapshots.matchday_wins),\n                   place = COALESCE(excluded.place, vnext_manager_snapshots.place),\n                   recorded_at = datetime('now')",
                params![league_id, manager.id, manager.team_value, manager.profit, manager.points, manager.average_points, manager.matchday_wins, manager.place],
            ).map_err(|_| CommandError::internal("Liga-Snapshots konnten nicht gespeichert werden."))?;
        }

        tx.commit().map_err(|_| CommandError::internal("Liga-Daten konnten nicht gespeichert werden."))?;
        Ok(())
    }

        pub fn upsert_team_logos(&mut self, logos: &HashMap<String, String>) -> Result<(), CommandError> {
        let tx = self.conn.transaction()
            .map_err(|_| CommandError::internal("Die Teamdaten konnten nicht aktualisiert werden."))?;

        for (team_id, remote_path) in logos {
            tx.execute(
                "INSERT INTO vnext_teams (id, name, logo_remote_path, updated_at)\n                 VALUES (?1, NULL, ?2, datetime('now'))\n                 ON CONFLICT(id) DO UPDATE SET\n                   logo_remote_path = excluded.logo_remote_path,\n                   updated_at = datetime('now')",
                params![team_id, remote_path],
            )
            .map_err(|_| CommandError::internal("Die Teamlogos konnten nicht gespeichert werden."))?;
        }

        tx.commit()
            .map_err(|_| CommandError::internal("Die Teamlogos konnten nicht gespeichert werden."))?;
        Ok(())
    }

    pub fn set_team_logo_local_path(&self, team_id: &str, local_path: &Path) -> Result<(), CommandError> {
        self.conn.execute(
            "UPDATE vnext_teams SET logo_local_path = ?2, updated_at = datetime('now') WHERE id = ?1",
            params![team_id, local_path.to_string_lossy().to_string()],
        )
        .map_err(|_| CommandError::internal("Der lokale Teamlogo-Pfad konnte nicht gespeichert werden."))?;
        Ok(())
    }

    pub fn player_enrichment(&self, player_id: &str, live_team_id: Option<&str>) -> Result<PlayerEnrichment, CommandError> {
        let player = self.conn
            .query_row(
                "SELECT p.display_name, p.full_name, p.team_id, COALESCE(pm.portrait_path, p.portrait_path)
                 FROM vnext_players p
                 LEFT JOIN vnext_portrait_mappings pm ON pm.player_id = p.id
                 WHERE p.id = ?1",
                [player_id],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?, row.get::<_, Option<String>>(2)?, row.get::<_, Option<String>>(3)?)),
            )
            .optional()
            .map_err(|_| CommandError::internal("Spieler-Stammdaten konnten nicht gelesen werden."))?;

        let (display_name, full_name, stored_team_id, portrait_path) = player.unwrap_or_else(|| (String::new(), None, None, None));
        let first_name = infer_first_name(full_name.as_deref(), &display_name);
        let team_id = live_team_id.map(str::to_owned).or(stored_team_id);

        let team = if let Some(ref team_id) = team_id {
            self.conn
                .query_row(
                    "SELECT name, logo_remote_path, logo_local_path FROM vnext_teams WHERE id = ?1",
                    [team_id],
                    |row| Ok((row.get::<_, Option<String>>(0)?, row.get::<_, Option<String>>(1)?, row.get::<_, Option<String>>(2)?)),
                )
                .optional()
                .map_err(|_| CommandError::internal("Team-Stammdaten konnten nicht gelesen werden."))?
        } else {
            None
        };

        let (club_name, team_logo_remote_path, team_logo_local_path) = team.unwrap_or((None, None, None));

        Ok(PlayerEnrichment {
            first_name,
            team_id,
            club_name,
            portrait_data_url: portrait_path.as_deref().and_then(file_data_url),
            team_logo_remote_path,
            team_logo_local_path,
        })
    }

    pub fn market_value_history(&self, player_id: &str) -> Result<Vec<(String, i64)>, CommandError> {
        if !self.table_exists("market_values")? { return Ok(Vec::new()); }
        let mut stmt = self.conn.prepare(
            "SELECT mv.snapshot_date, mv.value
             FROM market_values mv
             INNER JOIN (
               SELECT snapshot_date, MAX(id) AS latest_id
               FROM market_values
               WHERE player_id = ?1 AND snapshot_date IS NOT NULL
               GROUP BY snapshot_date
             ) daily ON daily.latest_id = mv.id
             ORDER BY mv.snapshot_date ASC"
        ).map_err(|_| CommandError::internal("Marktwert-Historie konnte nicht gelesen werden."))?;
        let rows = stmt.query_map([player_id], |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)))
            .map_err(|_| CommandError::internal("Marktwert-Historie konnte nicht gelesen werden."))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Marktwert-Historie konnte nicht gelesen werden."))
    }

    pub fn team_logo_cache_path(&self, team_id: &str, remote_path: &str) -> Result<PathBuf, CommandError> {
        let logos_dir = self.app_dir.join("team_logos");
        fs::create_dir_all(&logos_dir)
            .map_err(|_| CommandError::internal("Der Teamlogo-Cache konnte nicht erstellt werden."))?;

        let ext = Path::new(remote_path)
            .extension()
            .and_then(|value| value.to_str())
            .filter(|value| !value.is_empty())
            .unwrap_or("png");
        Ok(logos_dir.join(format!("{team_id}.{ext}")))
    }

    pub fn record_force_refresh_market_values(
        &mut self,
        snapshots: &[(String, i64)],
    ) -> Result<usize, CommandError> {
        if snapshots.is_empty() || !self.table_exists("market_values")? {
            return Ok(0);
        }

        let local_hour: i64 = self.conn.query_row(
            "SELECT CAST(strftime('%H','now','localtime') AS INTEGER)",
            [],
            |row| row.get(0),
        )
        .map_err(|_| CommandError::internal("Die lokale Refresh-Zeit konnte nicht bestimmt werden."))?;

        // A manual refresh during the day is live state, not a completed
        // Kickbase 22:00 market-value refresh. Do not let it overwrite the
        // canonical daily history used by 24H dynamics and the prediction
        // model. Also repair rows written by the older force-refresh code.
        if local_hour < 22 {
            self.conn.execute(
                "DELETE FROM market_values
                 WHERE snapshot_date = date('now','localtime')
                   AND source = 'force_refresh'",
                [],
            )
            .map_err(|_| CommandError::internal("Alte Force-Refresh-MW-Werte konnten nicht bereinigt werden."))?;

            #[cfg(debug_assertions)]
            crate::kt_debug!(
                "[KickTrack][DEBUG][force-refresh] local_hour={} -> canonical MW history unchanged",
                local_hour
            );
            return Ok(0);
        }

        let tx = self.conn.transaction()
            .map_err(|_| CommandError::internal("MW-Snapshots konnten nicht vorbereitet werden."))?;

        let mut written = 0usize;
        for (player_id, value) in snapshots {
            if player_id.trim().is_empty() || *value <= 0 {
                continue;
            }

            tx.execute(
                "INSERT INTO market_values
                   (player_id, value, recorded_at, snapshot_date, source)
                 VALUES (?1, ?2, datetime('now','localtime'), date('now','localtime'), 'force_refresh')
                 ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                   value = excluded.value,
                   recorded_at = excluded.recorded_at,
                   source = excluded.source",
                params![player_id, value],
            )
            .map_err(|error| {
                #[cfg(debug_assertions)]
                crate::kt_debug!(
                    "[KickTrack][DEBUG][force-refresh] MW snapshot failed player={} value={} error={}",
                    player_id, value, error
                );
                CommandError::internal("MW-Snapshot konnte nicht gespeichert werden.")
            })?;
            written += 1;
        }

        tx.commit()
            .map_err(|_| CommandError::internal("MW-Snapshots konnten nicht gespeichert werden."))?;

        Ok(written)
    }

    pub fn record_force_refresh_dashboard(
        &self,
        league_id: &str,
        team_value: i64,
        budget: Option<i64>,
    ) -> Result<(), CommandError> {
        if !self.table_exists("dashboard_snapshots")? || league_id.trim().is_empty() {
            return Ok(());
        }

        let total_assets = budget.map(|value| value.saturating_add(team_value));
        self.conn.execute(
            "INSERT INTO dashboard_snapshots
               (league_id, snapshot_date, team_value, budget, total_assets, recorded_at)
             VALUES (?1, date('now'), ?2, ?3, ?4, datetime('now'))
             ON CONFLICT(league_id, snapshot_date) DO UPDATE SET
               team_value = excluded.team_value,
               budget = excluded.budget,
               total_assets = excluded.total_assets,
               recorded_at = excluded.recorded_at",
            params![league_id, team_value, budget, total_assets],
        )
        .map_err(|_| CommandError::internal("Dashboard-Snapshot konnte nicht gespeichert werden."))?;
        Ok(())
    }

}

fn infer_first_name(full_name: Option<&str>, display_name: &str) -> Option<String> {
    let full = full_name?.trim();
    if full.is_empty() { return None; }
    let display = display_name.trim();
    if !display.is_empty() {
        if let Some(prefix) = full.strip_suffix(display) {
            let prefix = prefix.trim_matches(|c: char| c.is_whitespace() || c == ',' || c == '-');
            if !prefix.is_empty() { return Some(prefix.to_string()); }
        }
    }
    let first = full.split_whitespace().next()?;
    if first.eq_ignore_ascii_case(display) { None } else { Some(first.to_string()) }
}

pub fn file_data_url(path: &str) -> Option<String> {
    let path = Path::new(path);
    let bytes = fs::read(path).ok()?;
    let mime = mime_for_path(path);
    Some(format!("data:{mime};base64,{}", STANDARD.encode(bytes)))
}

pub fn bytes_data_url(bytes: &[u8], source_path: &str) -> String {
    let mime = mime_for_path(Path::new(source_path));
    format!("data:{mime};base64,{}", STANDARD.encode(bytes))
}

fn mime_for_path(path: &Path) -> &'static str {
    match path.extension().and_then(|value| value.to_str()).map(|value| value.to_ascii_lowercase()) {
        Some(ext) if ext == "svg" => "image/svg+xml",
        Some(ext) if ext == "jpg" || ext == "jpeg" || ext == "jpe" => "image/jpeg",
        Some(ext) if ext == "webp" => "image/webp",
        _ => "image/png",
    }
}
