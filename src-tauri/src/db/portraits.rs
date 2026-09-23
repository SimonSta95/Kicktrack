use super::*;

impl KickTrackDatabase {
    pub fn upsert_player_reference(
        &self,
        player_id: &str,
        display_name: &str,
        full_name: Option<&str>,
        team_id: Option<&str>,
        position: Option<&str>,
    ) -> Result<(), CommandError> {
        if player_id.trim().is_empty() || display_name.trim().is_empty() {
            return Ok(());
        }
        if let Some(team_id) = team_id.filter(|value| !value.trim().is_empty()) {
            self.conn.execute(
                "INSERT INTO vnext_teams(id,name,updated_at)
                 VALUES(?1,NULL,datetime('now'))
                 ON CONFLICT(id) DO NOTHING",
                [team_id],
            )
            .map_err(|_| CommandError::internal("Team-Referenz konnte nicht vorbereitet werden."))?;
        }
        self.conn.execute(
            "INSERT INTO vnext_players(
                id,display_name,full_name,team_id,position,portrait_path,legacy_fotmob_id,updated_at
             )
             VALUES(?1,?2,?3,?4,?5,NULL,NULL,datetime('now'))
             ON CONFLICT(id) DO UPDATE SET
               display_name=excluded.display_name,
               full_name=COALESCE(excluded.full_name,vnext_players.full_name),
               team_id=COALESCE(excluded.team_id,vnext_players.team_id),
               position=COALESCE(excluded.position,vnext_players.position),
               updated_at=datetime('now')",
            params![player_id, display_name, full_name, team_id, position],
        )
        .map_err(|_| CommandError::internal("Spieler-Stammdaten konnten nicht aktualisiert werden."))?;
        Ok(())
    }

    pub fn portrait_candidates(&self, limit: usize, retry_failed: bool) -> Result<Vec<PortraitPlayer>, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT p.id, p.display_name, p.full_name, t.name,
                    COALESCE(pm.fotmob_id, p.legacy_fotmob_id), pm.portrait_url,
                    COALESCE(pm.portrait_path, p.portrait_path), COALESCE(pm.state,'MISSING'),
                    pm.confidence, pm.reason, pm.candidate_name, pm.candidate_team,
                    pm.candidate_position, pm.candidate_shirt_number
             FROM vnext_players p
             LEFT JOIN vnext_teams t ON t.id=p.team_id
             LEFT JOIN vnext_portrait_mappings pm ON pm.player_id=p.id
             WHERE COALESCE(pm.state,'MISSING') NOT IN ('REJECTED','NEEDS_REVIEW')
               AND (?1 = 1 OR COALESCE(pm.state,'MISSING') <> 'FAILED')
               AND (
                 COALESCE(pm.portrait_path,p.portrait_path) IS NULL
                 OR trim(COALESCE(pm.portrait_path,p.portrait_path)) = ''
                 OR COALESCE(pm.state,'MISSING') IN ('MISSING','FAILED')
               )
             ORDER BY
               CASE WHEN COALESCE(pm.fotmob_id,p.legacy_fotmob_id) IS NOT NULL THEN 0 ELSE 1 END,
               lower(COALESCE(p.full_name,p.display_name))
             LIMIT ?2"
        )
        .map_err(|_| CommandError::internal("Portrait-Kandidaten konnten nicht gelesen werden."))?;

        let rows = stmt.query_map(params![if retry_failed { 1 } else { 0 }, limit as i64], |row| {
            Ok(PortraitPlayer {
                player_id: row.get(0)?,
                display_name: row.get(1)?,
                full_name: row.get(2)?,
                club_name: row.get(3)?,
                fotmob_id: row.get(4)?,
                portrait_url: row.get(5)?,
                portrait_path: row.get(6)?,
                portrait_state: row.get(7)?,
                portrait_confidence: row.get(8)?,
                portrait_reason: row.get(9)?,
                candidate_name: row.get(10)?,
                candidate_team: row.get(11)?,
                candidate_position: row.get(12)?,
                candidate_shirt_number: row.get(13)?,
            })
        })
        .map_err(|_| CommandError::internal("Portrait-Kandidaten konnten nicht gelesen werden."))?;

        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Portrait-Kandidaten konnten nicht gelesen werden."))
    }

    pub fn portrait_candidates_for_ids(
        &self,
        player_ids: &[String],
        retry_failed: bool,
    ) -> Result<Vec<PortraitPlayer>, CommandError> {
        if player_ids.is_empty() {
            return Ok(Vec::new());
        }

        let mut stmt = self.conn.prepare(
            "SELECT p.id, p.display_name, p.full_name, t.name,
                    COALESCE(pm.fotmob_id, p.legacy_fotmob_id), pm.portrait_url,
                    COALESCE(pm.portrait_path, p.portrait_path), COALESCE(pm.state,'MISSING'),
                    pm.confidence, pm.reason, pm.candidate_name, pm.candidate_team,
                    pm.candidate_position, pm.candidate_shirt_number
             FROM vnext_players p
             LEFT JOIN vnext_teams t ON t.id=p.team_id
             LEFT JOIN vnext_portrait_mappings pm ON pm.player_id=p.id
             WHERE p.id=?1
               AND COALESCE(pm.state,'MISSING') NOT IN ('REJECTED','NEEDS_REVIEW')
               AND (?2 = 1 OR COALESCE(pm.state,'MISSING') <> 'FAILED')
               AND (
                 COALESCE(pm.portrait_path,p.portrait_path) IS NULL
                 OR trim(COALESCE(pm.portrait_path,p.portrait_path)) = ''
                 OR COALESCE(pm.state,'MISSING') IN ('MISSING','FAILED')
               )"
        )
        .map_err(|_| CommandError::internal("Portrait-Kandidaten konnten nicht gelesen werden."))?;

        let mut result = Vec::new();
        for player_id in player_ids {
            let row = stmt.query_row(
                params![player_id, if retry_failed { 1 } else { 0 }],
                |row| {
                    Ok(PortraitPlayer {
                        player_id: row.get(0)?,
                        display_name: row.get(1)?,
                        full_name: row.get(2)?,
                        club_name: row.get(3)?,
                        fotmob_id: row.get(4)?,
                        portrait_url: row.get(5)?,
                        portrait_path: row.get(6)?,
                        portrait_state: row.get(7)?,
                        portrait_confidence: row.get(8)?,
                        portrait_reason: row.get(9)?,
                        candidate_name: row.get(10)?,
                        candidate_team: row.get(11)?,
                        candidate_position: row.get(12)?,
                        candidate_shirt_number: row.get(13)?,
                    })
                },
            ).optional()
            .map_err(|_| CommandError::internal("Portrait-Kandidat konnte nicht gelesen werden."))?;
            if let Some(row) = row {
                result.push(row);
            }
        }
        Ok(result)
    }

    pub fn revalidate_portrait_cache(&self) -> Result<usize, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT player_id, portrait_path
             FROM vnext_portrait_mappings
             WHERE state='CACHED' AND portrait_path IS NOT NULL AND trim(portrait_path) <> ''"
        )
        .map_err(|_| CommandError::internal("Portrait-Cache konnte nicht geprüft werden."))?;
        let rows = stmt.query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)))
            .map_err(|_| CommandError::internal("Portrait-Cache konnte nicht geprüft werden."))?;

        let mut missing = Vec::new();
        for row in rows {
            let (player_id, path) = row
                .map_err(|_| CommandError::internal("Portrait-Cache konnte nicht geprüft werden."))?;
            if !Path::new(&path).exists() {
                missing.push(player_id);
            }
        }
        drop(stmt);

        for player_id in &missing {
            self.conn.execute(
                "UPDATE vnext_portrait_mappings
                 SET portrait_path=NULL, state='MISSING',
                     reason='Lokale Portrait-Datei fehlt', checked_at=datetime('now')
                 WHERE player_id=?1",
                [player_id],
            )
            .map_err(|_| CommandError::internal("Portrait-Cache konnte nicht repariert werden."))?;
            self.conn.execute(
                "UPDATE vnext_players SET portrait_path=NULL, updated_at=datetime('now') WHERE id=?1",
                [player_id],
            )
            .map_err(|_| CommandError::internal("Portrait-Cache konnte nicht repariert werden."))?;
        }

        Ok(missing.len())
    }

    pub fn portrait_state_counts(&self) -> Result<HashMap<String, i64>, CommandError> {
        let mut counts = HashMap::new();
        let mut stmt = self.conn.prepare(
            "SELECT COALESCE(state,'MISSING'), COUNT(*)
             FROM vnext_portrait_mappings
             GROUP BY COALESCE(state,'MISSING')"
        )
        .map_err(|_| CommandError::internal("Portrait-Status konnte nicht gelesen werden."))?;
        let rows = stmt.query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)))
            .map_err(|_| CommandError::internal("Portrait-Status konnte nicht gelesen werden."))?;
        for row in rows {
            let (state, count) = row.map_err(|_| CommandError::internal("Portrait-Status konnte nicht gelesen werden."))?;
            counts.insert(state, count);
        }

        let total_players: i64 = self.conn
            .query_row("SELECT COUNT(*) FROM vnext_players", [], |row| row.get(0))
            .map_err(|_| CommandError::internal("Spieleranzahl konnte nicht gelesen werden."))?;
        let mapped: i64 = counts.values().sum();
        if total_players > mapped {
            *counts.entry("MISSING".into()).or_insert(0) += total_players - mapped;
        }
        Ok(counts)
    }

    pub fn portrait_review_items(&self) -> Result<Vec<PortraitReviewItem>, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT p.id, COALESCE(p.full_name,p.display_name), t.name,
                    pm.fotmob_id, pm.portrait_url, pm.confidence, pm.reason,
                    pm.candidate_name, pm.candidate_team, pm.candidate_position,
                    pm.candidate_shirt_number
             FROM vnext_portrait_mappings pm
             JOIN vnext_players p ON p.id=pm.player_id
             LEFT JOIN vnext_teams t ON t.id=p.team_id
             WHERE pm.state='NEEDS_REVIEW'
             ORDER BY COALESCE(pm.confidence,0) DESC, lower(p.display_name)"
        )
        .map_err(|_| CommandError::internal("Portrait-Prüffälle konnten nicht gelesen werden."))?;
        let rows = stmt.query_map([], |row| {
            Ok(PortraitReviewItem {
                player_id: row.get(0)?,
                player_name: row.get(1)?,
                club_name: row.get(2)?,
                fotmob_id: row.get(3)?,
                portrait_url: row.get(4)?,
                confidence: row.get(5)?,
                reason: row.get(6)?,
                candidate_name: row.get(7)?,
                candidate_team: row.get(8)?,
                candidate_position: row.get(9)?,
                candidate_shirt_number: row.get(10)?,
            })
        })
        .map_err(|_| CommandError::internal("Portrait-Prüffälle konnten nicht gelesen werden."))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Portrait-Prüffälle konnten nicht gelesen werden."))
    }

    pub fn save_portrait_mapping(&self, player: &PortraitPlayer) -> Result<(), CommandError> {
        self.conn.execute(
            "INSERT INTO vnext_portrait_mappings(
               player_id,fotmob_id,portrait_url,portrait_path,state,confidence,reason,
               candidate_name,candidate_team,candidate_position,candidate_shirt_number,checked_at
             )
             VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,datetime('now'))
             ON CONFLICT(player_id) DO UPDATE SET
               fotmob_id=excluded.fotmob_id,
               portrait_url=excluded.portrait_url,
               portrait_path=excluded.portrait_path,
               state=excluded.state,
               confidence=excluded.confidence,
               reason=excluded.reason,
               candidate_name=excluded.candidate_name,
               candidate_team=excluded.candidate_team,
               candidate_position=excluded.candidate_position,
               candidate_shirt_number=excluded.candidate_shirt_number,
               checked_at=datetime('now')",
            params![
                player.player_id,
                player.fotmob_id,
                player.portrait_url,
                player.portrait_path,
                player.portrait_state,
                player.portrait_confidence,
                player.portrait_reason,
                player.candidate_name,
                player.candidate_team,
                player.candidate_position,
                player.candidate_shirt_number
            ],
        )
        .map_err(|_| CommandError::internal("Portrait-Mapping konnte nicht gespeichert werden."))?;
        Ok(())
    }

    pub fn reject_portrait(&self, player_id: &str) -> Result<(), CommandError> {
        self.conn.execute(
            "UPDATE vnext_portrait_mappings
             SET state='REJECTED',
                 reason=COALESCE(reason,'Manuell abgelehnt'),
                 checked_at=datetime('now')
             WHERE player_id=?1",
            [player_id],
        )
        .map_err(|_| CommandError::internal("Portrait-Zuordnung konnte nicht abgelehnt werden."))?;
        Ok(())
    }

    pub fn portrait_cache_path(&self, player_id: &str) -> Result<PathBuf, CommandError> {
        let dir = self.app_dir.join("player_portraits");
        fs::create_dir_all(&dir)
            .map_err(|_| CommandError::internal("Der Portrait-Cache konnte nicht angelegt werden."))?;
        Ok(dir.join(format!("{player_id}.png")))
    }

}
