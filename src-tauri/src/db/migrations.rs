use super::*;

impl KickTrackDatabase {
    pub(super) fn run_migrations(&mut self) -> Result<(), CommandError> {
        self.conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS vnext_schema_migrations (\n                version INTEGER PRIMARY KEY,\n                applied_at TEXT NOT NULL\n             );\n\n             CREATE TABLE IF NOT EXISTS vnext_teams (\n                id TEXT PRIMARY KEY,\n                name TEXT,\n                logo_remote_path TEXT,\n                logo_local_path TEXT,\n                updated_at TEXT NOT NULL\n             );\n\n             CREATE TABLE IF NOT EXISTS vnext_players (\n                id TEXT PRIMARY KEY,\n                display_name TEXT NOT NULL,\n                full_name TEXT,\n                team_id TEXT,\n                position TEXT,\n                portrait_path TEXT,\n                legacy_fotmob_id TEXT,\n                updated_at TEXT NOT NULL,\n                FOREIGN KEY (team_id) REFERENCES vnext_teams(id)\n             );",
        )
        .map_err(|_| CommandError::internal("Das neue KickTrack-Datenbankschema konnte nicht vorbereitet werden."))?;

        self.conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS vnext_managers (\n                league_id TEXT NOT NULL,\n                id TEXT NOT NULL,\n                name TEXT NOT NULL,\n                profile_image_remote_path TEXT,\n                is_self INTEGER NOT NULL DEFAULT 0,\n                updated_at TEXT NOT NULL,\n                PRIMARY KEY (league_id, id)\n             );\n\n             CREATE TABLE IF NOT EXISTS vnext_manager_snapshots (\n                league_id TEXT NOT NULL,\n                manager_id TEXT NOT NULL,\n                snapshot_date TEXT NOT NULL,\n                team_value INTEGER,\n                profit INTEGER,\n                points INTEGER,\n                average_points REAL,\n                matchday_wins INTEGER,\n                place INTEGER,\n                recorded_at TEXT NOT NULL,\n                PRIMARY KEY (league_id, manager_id, snapshot_date),\n                FOREIGN KEY (league_id, manager_id) REFERENCES vnext_managers(league_id, id) ON DELETE CASCADE\n             );\n\n             CREATE INDEX IF NOT EXISTS idx_vnext_manager_snapshots_place\n             ON vnext_manager_snapshots(league_id, snapshot_date DESC, place);"
        )
        .map_err(|_| CommandError::internal("Das Liga-Datenbankschema konnte nicht vorbereitet werden."))?;

        self.conn
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS vnext_portrait_mappings (
                player_id TEXT PRIMARY KEY,
                fotmob_id TEXT,
                portrait_url TEXT,
                portrait_path TEXT,
                state TEXT NOT NULL DEFAULT 'MISSING',
                confidence INTEGER,
                reason TEXT,
                candidate_name TEXT,
                candidate_team TEXT,
                candidate_position TEXT,
                candidate_shirt_number TEXT,
                checked_at TEXT,
                FOREIGN KEY(player_id) REFERENCES vnext_players(id) ON DELETE CASCADE
             );
             CREATE INDEX IF NOT EXISTS idx_vnext_portraits_state
             ON vnext_portrait_mappings(state, checked_at);

             CREATE TABLE IF NOT EXISTS vnext_transfer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id TEXT NOT NULL,
                manager_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team_id TEXT,
                club_name TEXT,
                transfer_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                transferred_at TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL,
                UNIQUE(league_id, manager_id, player_id, transfer_type, price, transferred_at)
             );
             CREATE INDEX IF NOT EXISTS idx_vnext_transfer_manager_date
             ON vnext_transfer_events(league_id, manager_id, transferred_at DESC);
             CREATE INDEX IF NOT EXISTS idx_vnext_transfer_player_date
             ON vnext_transfer_events(player_id, transferred_at DESC);",
            )
            .map_err(|_| {
                CommandError::internal(
                    "Das Analyse-Datenbankschema konnte nicht vorbereitet werden.",
                )
            })?;

        let applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 1",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Datenbank-Migrationsstand konnte nicht gelesen werden.")
            })?;

        if applied.is_none() {
            self.import_legacy_reference_data()?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations (version, applied_at) VALUES (1, datetime('now'))",
                [],
            )
            .map_err(|_| CommandError::internal("Die Datenbankmigration konnte nicht abgeschlossen werden."))?;
        }

        let logo_seed_applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 2",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Datenbank-Migrationsstand konnte nicht gelesen werden.")
            })?;

        if logo_seed_applied.is_none() {
            self.import_legacy_team_logos()?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations (version, applied_at) VALUES (2, datetime('now'))",
                [],
            )
            .map_err(|_| CommandError::internal("Die Teamlogo-Migration konnte nicht abgeschlossen werden."))?;
        }

        let manager_seed_applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 3",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Datenbank-Migrationsstand konnte nicht gelesen werden.")
            })?;

        if manager_seed_applied.is_none() {
            self.import_legacy_managers()?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations (version, applied_at) VALUES (3, datetime('now'))",
                [],
            )
            .map_err(|_| CommandError::internal("Die Manager-Migration konnte nicht abgeschlossen werden."))?;
        }

        let portrait_seed_applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 4",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Portrait-Migrationsstand konnte nicht gelesen werden.")
            })?;
        if portrait_seed_applied.is_none() {
            self.import_legacy_portrait_mappings()?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations(version, applied_at) VALUES(4, datetime('now'))",
                [],
            )
            .map_err(|_| CommandError::internal("Die Portrait-Migration konnte nicht abgeschlossen werden."))?;
        }

        let transfer_seed_applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 5",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Transfer-Migrationsstand konnte nicht gelesen werden.")
            })?;
        if transfer_seed_applied.is_none() {
            self.import_legacy_transfer_events()?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations(version, applied_at) VALUES(5, datetime('now'))",
                [],
            )
                .map_err(|_| CommandError::internal("Die Transfer-Migration konnte nicht abgeschlossen werden."))?;
        }

        let history_schema_applied: Option<i64> = self
            .conn
            .query_row(
                "SELECT version FROM vnext_schema_migrations WHERE version = 6",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Der Historien-Migrationsstand konnte nicht gelesen werden.")
            })?;
        if history_schema_applied.is_none() {
            self.conn
                .execute_batch(
                    "CREATE TABLE IF NOT EXISTS market_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id TEXT NOT NULL,
                    value INTEGER NOT NULL CHECK(value > 0),
                    recorded_at TEXT NOT NULL,
                    snapshot_date TEXT,
                    source TEXT,
                    UNIQUE(player_id, recorded_at)
                 );
                 CREATE INDEX IF NOT EXISTS idx_market_values_player_date
                 ON market_values(player_id, snapshot_date DESC);

                 CREATE TABLE IF NOT EXISTS dashboard_snapshots (
                    league_id TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    team_value INTEGER NOT NULL,
                    budget INTEGER,
                    total_assets INTEGER,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(league_id, snapshot_date)
                 );
                 CREATE INDEX IF NOT EXISTS idx_dashboard_snapshots_league_date
                 ON dashboard_snapshots(league_id, snapshot_date DESC);",
                )
                .map_err(|_| {
                    CommandError::internal(
                        "Das Historien-Datenbankschema konnte nicht vorbereitet werden.",
                    )
                })?;
            self.conn.execute(
                "INSERT INTO vnext_schema_migrations(version, applied_at) VALUES(6, datetime('now'))",
                [],
            ).map_err(|_| CommandError::internal("Die Historien-Migration konnte nicht abgeschlossen werden."))?;
        }

        Ok(())
    }

    fn import_legacy_reference_data(&mut self) -> Result<(), CommandError> {
        if !self.table_exists("player_master")? {
            return Ok(());
        }

        let tx = self.conn.transaction().map_err(|_| {
            CommandError::internal("Die historischen Stammdaten konnten nicht migriert werden.")
        })?;

        {
            let mut team_stmt = tx
                .prepare(
                    "SELECT DISTINCT team_id, club\n                     FROM player_master\n                     WHERE team_id IS NOT NULL AND trim(team_id) <> ''",
                )
                .map_err(|_| CommandError::internal("Historische Teamdaten konnten nicht gelesen werden."))?;
            let rows = team_stmt
                .query_map([], |row| {
                    Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
                })
                .map_err(|_| {
                    CommandError::internal("Historische Teamdaten konnten nicht gelesen werden.")
                })?;

            for row in rows {
                let (team_id, club) = row.map_err(|_| {
                    CommandError::internal("Historische Teamdaten konnten nicht gelesen werden.")
                })?;
                tx.execute(
                    "INSERT INTO vnext_teams (id, name, updated_at) VALUES (?1, ?2, datetime('now'))\n                     ON CONFLICT(id) DO UPDATE SET\n                       name = COALESCE(excluded.name, vnext_teams.name),\n                       updated_at = datetime('now')",
                    params![team_id, club],
                )
                .map_err(|_| CommandError::internal("Historische Teamdaten konnten nicht migriert werden."))?;
            }
        }

        {
            let mut player_stmt = tx
                .prepare(
                    "SELECT player_id, name, full_name, team_id, position, portrait_path, fotmob_id\n                     FROM player_master",
                )
                .map_err(|_| CommandError::internal("Historische Spielerdaten konnten nicht gelesen werden."))?;
            let rows = player_stmt
                .query_map([], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, Option<String>>(2)?,
                        row.get::<_, Option<String>>(3)?,
                        row.get::<_, Option<String>>(4)?,
                        row.get::<_, Option<String>>(5)?,
                        row.get::<_, Option<String>>(6)?,
                    ))
                })
                .map_err(|_| {
                    CommandError::internal("Historische Spielerdaten konnten nicht gelesen werden.")
                })?;

            for row in rows {
                let (id, name, full_name, team_id, position, portrait_path, fotmob_id) = row
                    .map_err(|_| {
                        CommandError::internal(
                            "Historische Spielerdaten konnten nicht gelesen werden.",
                        )
                    })?;
                tx.execute(
                    "INSERT INTO vnext_players\n                       (id, display_name, full_name, team_id, position, portrait_path, legacy_fotmob_id, updated_at)\n                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, datetime('now'))\n                     ON CONFLICT(id) DO UPDATE SET\n                       display_name = excluded.display_name,\n                       full_name = excluded.full_name,\n                       team_id = excluded.team_id,\n                       position = excluded.position,\n                       portrait_path = excluded.portrait_path,\n                       legacy_fotmob_id = excluded.legacy_fotmob_id,\n                       updated_at = datetime('now')",
                    params![id, name, full_name, team_id, position, portrait_path, fotmob_id],
                )
                .map_err(|_| CommandError::internal("Historische Spielerdaten konnten nicht migriert werden."))?;
            }
        }

        tx.commit().map_err(|_| {
            CommandError::internal("Die historischen Stammdaten konnten nicht migriert werden.")
        })?;
        Ok(())
    }

    fn import_legacy_managers(&mut self) -> Result<(), CommandError> {
        if !self.table_exists("league_managers")? {
            return Ok(());
        }

        let tx = self.conn.transaction().map_err(|_| {
            CommandError::internal("Historische Managerdaten konnten nicht migriert werden.")
        })?;
        {
            let mut stmt = tx.prepare(
                "SELECT league_id, manager_id, name, profile_image, is_user, team_value, profit, points, average_points, matchday_wins, place, updated_at\n                 FROM league_managers"
            ).map_err(|_| CommandError::internal("Historische Managerdaten konnten nicht gelesen werden."))?;
            let rows = stmt
                .query_map([], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, Option<String>>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, Option<i64>>(5)?,
                        row.get::<_, Option<i64>>(6)?,
                        row.get::<_, Option<i64>>(7)?,
                        row.get::<_, Option<f64>>(8)?,
                        row.get::<_, Option<i64>>(9)?,
                        row.get::<_, Option<i64>>(10)?,
                        row.get::<_, String>(11)?,
                    ))
                })
                .map_err(|_| {
                    CommandError::internal("Historische Managerdaten konnten nicht gelesen werden.")
                })?;

            for row in rows {
                let (
                    league_id,
                    manager_id,
                    name,
                    profile_image,
                    is_user,
                    team_value,
                    profit,
                    points,
                    average_points,
                    matchday_wins,
                    place,
                    updated_at,
                ) = row.map_err(|_| {
                    CommandError::internal("Historische Managerdaten konnten nicht gelesen werden.")
                })?;
                tx.execute(
                    "INSERT INTO vnext_managers (league_id, id, name, profile_image_remote_path, is_self, updated_at)\n                     VALUES (?1, ?2, ?3, ?4, ?5, ?6)\n                     ON CONFLICT(league_id, id) DO UPDATE SET\n                       name = excluded.name,\n                       profile_image_remote_path = COALESCE(excluded.profile_image_remote_path, vnext_managers.profile_image_remote_path),\n                       is_self = MAX(vnext_managers.is_self, excluded.is_self),\n                       updated_at = excluded.updated_at",
                    params![league_id, manager_id, name, profile_image, is_user, updated_at],
                ).map_err(|_| CommandError::internal("Historische Managerdaten konnten nicht migriert werden."))?;

                tx.execute(
                    "INSERT INTO vnext_manager_snapshots\n                       (league_id, manager_id, snapshot_date, team_value, profit, points, average_points, matchday_wins, place, recorded_at)\n                     VALUES (?1, ?2, substr(?9, 1, 10), ?3, ?4, ?5, ?6, ?7, ?8, ?9)\n                     ON CONFLICT(league_id, manager_id, snapshot_date) DO UPDATE SET\n                       team_value = excluded.team_value, profit = excluded.profit, points = excluded.points,\n                       average_points = excluded.average_points, matchday_wins = excluded.matchday_wins,\n                       place = excluded.place, recorded_at = excluded.recorded_at",
                    params![league_id, manager_id, team_value, profit, points, average_points, matchday_wins, place, updated_at],
                ).map_err(|_| CommandError::internal("Historische Manager-Snapshots konnten nicht migriert werden."))?;
            }
        }
        tx.commit().map_err(|_| {
            CommandError::internal("Historische Managerdaten konnten nicht migriert werden.")
        })?;
        Ok(())
    }

    fn import_legacy_portrait_mappings(&mut self) -> Result<(), CommandError> {
        if !self.table_exists("player_master")? {
            return Ok(());
        }
        self.conn.execute_batch(
            "INSERT OR REPLACE INTO vnext_portrait_mappings(
                player_id, fotmob_id, portrait_url, portrait_path, state, confidence, reason,
                candidate_name, candidate_team, candidate_position, candidate_shirt_number, checked_at
             )
             SELECT player_id, fotmob_id, portrait_url, portrait_path,
                    COALESCE(NULLIF(portrait_state,''),'MISSING'), portrait_confidence, portrait_reason,
                    portrait_candidate_name, portrait_candidate_team, portrait_candidate_position,
                    portrait_candidate_shirt_number, portrait_checked_at
             FROM player_master
             WHERE player_id IN (SELECT id FROM vnext_players);"
        )
        .map_err(|_| CommandError::internal("Historische Portrait-Mappings konnten nicht migriert werden."))?;
        Ok(())
    }

    fn import_legacy_transfer_events(&mut self) -> Result<(), CommandError> {
        if self.table_exists("league_manager_transfers")? {
            self.conn
                .execute_batch(
                    "INSERT OR IGNORE INTO vnext_transfer_events(
                    league_id, manager_id, player_id, player_name, team_id, club_name,
                    transfer_type, price, transferred_at, observed_at, source
                 )
                 SELECT league_id, manager_id, player_id, player_name, team_id, club,
                        upper(transfer_type), price, transferred_at, observed_at,
                        'legacy_league_manager_transfers'
                 FROM league_manager_transfers;",
                )
                .map_err(|_| {
                    CommandError::internal(
                        "Historische Liga-Transfers konnten nicht migriert werden.",
                    )
                })?;
        }

        if self.table_exists("manager_transfers")? {
            self.conn
                .execute_batch(
                    "INSERT OR IGNORE INTO vnext_transfer_events(
                    league_id, manager_id, player_id, player_name, team_id, club_name,
                    transfer_type, price, transferred_at, observed_at, source
                 )
                 SELECT mt.league_id,
                        COALESCE(
                          (SELECT lm.manager_id FROM league_managers lm
                           WHERE lm.league_id=mt.league_id AND lm.is_user=1 LIMIT 1),
                          'self'
                        ),
                        mt.player_id, mt.player_name, mt.team_id, mt.club,
                        upper(mt.transfer_type), mt.price, mt.transferred_at, mt.transferred_at,
                        'legacy_manager_transfers'
                 FROM manager_transfers mt;",
                )
                .map_err(|_| {
                    CommandError::internal(
                        "Historische eigene Transfers konnten nicht migriert werden.",
                    )
                })?;
        }
        Ok(())
    }

    fn import_legacy_team_logos(&mut self) -> Result<(), CommandError> {
        // The legacy DB already contains Kickbase asset paths in `team_image`.
        // Prefer current manager-squad observations, then fill gaps from the
        // older own-squad table. For each team we pick the most frequently
        // observed path, which avoids one-off stale rows from transfer history.
        let candidate_tables = ["league_manager_players", "players"];
        let mut best_by_team: HashMap<String, (String, Option<String>, i64)> = HashMap::new();

        for table in candidate_tables {
            if !self.table_exists(table)? {
                continue;
            }

            let sql = format!(
                "SELECT team_id, team_image, MAX(club) AS club, COUNT(*) AS observations \
                 FROM {table} \
                 WHERE team_id IS NOT NULL AND trim(team_id) <> '' \
                   AND team_image IS NOT NULL AND trim(team_image) <> '' \
                 GROUP BY team_id, team_image \
                 ORDER BY observations DESC"
            );

            let mut stmt = self.conn.prepare(&sql).map_err(|_| {
                CommandError::internal("Historische Teamlogos konnten nicht gelesen werden.")
            })?;
            let rows = stmt
                .query_map([], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, Option<String>>(2)?,
                        row.get::<_, i64>(3)?,
                    ))
                })
                .map_err(|_| {
                    CommandError::internal("Historische Teamlogos konnten nicht gelesen werden.")
                })?;

            for row in rows {
                let (team_id, image_path, club, observations) = row.map_err(|_| {
                    CommandError::internal("Historische Teamlogos konnten nicht gelesen werden.")
                })?;

                let replace = best_by_team
                    .get(&team_id)
                    .map(|(_, _, current_count)| observations > *current_count)
                    .unwrap_or(true);

                if replace {
                    best_by_team.insert(team_id, (image_path, club, observations));
                }
            }
        }

        let tx = self.conn.transaction().map_err(|_| {
            CommandError::internal("Historische Teamlogos konnten nicht migriert werden.")
        })?;

        for (team_id, (remote_path, club, _)) in best_by_team {
            tx.execute(
                "INSERT INTO vnext_teams (id, name, logo_remote_path, updated_at)
                 VALUES (?1, ?2, ?3, datetime('now'))
                 ON CONFLICT(id) DO UPDATE SET
                   name = COALESCE(vnext_teams.name, excluded.name),
                   logo_remote_path = excluded.logo_remote_path,
                   updated_at = datetime('now')",
                params![team_id, club, remote_path],
            )
            .map_err(|_| {
                CommandError::internal("Historische Teamlogos konnten nicht migriert werden.")
            })?;
        }

        tx.commit().map_err(|_| {
            CommandError::internal("Historische Teamlogos konnten nicht migriert werden.")
        })?;
        Ok(())
    }

    pub(super) fn table_exists(&self, table: &str) -> Result<bool, CommandError> {
        let exists: Option<String> = self
            .conn
            .query_row(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?1",
                [table],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| {
                CommandError::internal("Die Datenbankstruktur konnte nicht gelesen werden.")
            })?;
        Ok(exists.is_some())
    }
}
