use super::*;

impl KickTrackDatabase {
    pub fn self_manager_id(&self, league_id: &str) -> Result<Option<String>, CommandError> {
        if let Some(id) = self.conn
            .query_row(
                "SELECT id FROM vnext_managers WHERE league_id=?1 AND is_self=1 LIMIT 1",
                [league_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| CommandError::internal("Eigener Manager konnte nicht gelesen werden."))?
        {
            return Ok(Some(id));
        }

        if self.table_exists("settings")? {
            for key in [format!("league:{league_id}:manager_id"), "manager_id".to_string()] {
                if let Some(id) = self.conn
                    .query_row("SELECT value FROM settings WHERE key=?1 LIMIT 1", [key], |row| row.get::<_, String>(0))
                    .optional()
                    .map_err(|_| CommandError::internal("Eigener Manager konnte nicht gelesen werden."))?
                {
                    if !id.trim().is_empty() {
                        return Ok(Some(id));
                    }
                }
            }
        }

        if self.table_exists("league_manager_transfers")? && self.table_exists("manager_transfers")? {
            let inferred = self.conn.query_row(
                "SELECT lmt.manager_id
                 FROM league_manager_transfers lmt
                 JOIN manager_transfers mt
                   ON mt.league_id=lmt.league_id
                  AND mt.player_id=lmt.player_id
                  AND upper(mt.transfer_type)=upper(lmt.transfer_type)
                  AND mt.price=lmt.price
                  AND mt.transferred_at=lmt.transferred_at
                 WHERE lmt.league_id=?1
                 GROUP BY lmt.manager_id
                 ORDER BY COUNT(*) DESC
                 LIMIT 1",
                [league_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|_| CommandError::internal("Eigener Manager konnte nicht aus der Transferhistorie bestimmt werden."))?;
            if inferred.is_some() {
                return Ok(inferred);
            }
        }
        Ok(None)
    }

    pub fn upsert_transfer_events(&mut self, events: &[TransferEventRow], source: &str) -> Result<(), CommandError> {
        let tx = self.conn.transaction()
            .map_err(|_| CommandError::internal("Transfers konnten nicht gespeichert werden."))?;
        for event in events {
            tx.execute(
                "INSERT INTO vnext_transfer_events(
                   league_id,manager_id,player_id,player_name,team_id,club_name,
                   transfer_type,price,transferred_at,observed_at,source
                 )
                 VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,datetime('now'),?10)
                 ON CONFLICT(league_id,manager_id,player_id,transfer_type,price,transferred_at)
                 DO UPDATE SET
                   player_name=excluded.player_name,
                   team_id=COALESCE(excluded.team_id,vnext_transfer_events.team_id),
                   club_name=COALESCE(excluded.club_name,vnext_transfer_events.club_name),
                   observed_at=datetime('now'),
                   source=excluded.source",
                params![
                    event.league_id, event.manager_id, event.player_id, event.player_name,
                    event.team_id, event.club_name, event.transfer_type, event.price,
                    event.transferred_at, source
                ],
            )
            .map_err(|_| CommandError::internal("Transfers konnten nicht gespeichert werden."))?;
        }
        tx.commit()
            .map_err(|_| CommandError::internal("Transfers konnten nicht gespeichert werden."))?;
        Ok(())
    }

    pub fn league_buy_events(&self, league_id: &str) -> Result<Vec<TransferEventRow>, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT league_id,manager_id,player_id,player_name,team_id,club_name,
                    transfer_type,price,transferred_at
             FROM vnext_transfer_events
             WHERE league_id=?1 AND upper(transfer_type)='BUY' AND price>0
             ORDER BY transferred_at DESC,id DESC"
        )
        .map_err(|_| CommandError::internal("Liga-Käufe konnten nicht gelesen werden."))?;
        let rows = stmt.query_map(params![league_id], |row| {
            Ok(TransferEventRow {
                league_id: row.get(0)?,
                manager_id: row.get(1)?,
                player_id: row.get(2)?,
                player_name: row.get(3)?,
                team_id: row.get(4)?,
                club_name: row.get(5)?,
                transfer_type: row.get(6)?,
                price: row.get(7)?,
                transferred_at: row.get(8)?,
            })
        })
        .map_err(|_| CommandError::internal("Liga-Käufe konnten nicht gelesen werden."))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Liga-Käufe konnten nicht gelesen werden."))
    }

    pub fn transfer_events(&self, league_id: &str, manager_id: &str) -> Result<Vec<TransferEventRow>, CommandError> {
        let mut stmt = self.conn.prepare(
            "SELECT league_id,manager_id,player_id,player_name,team_id,club_name,
                    transfer_type,price,transferred_at
             FROM vnext_transfer_events
             WHERE league_id=?1 AND manager_id=?2
             ORDER BY transferred_at ASC,id ASC"
        )
        .map_err(|_| CommandError::internal("Transfers konnten nicht gelesen werden."))?;
        let rows = stmt.query_map(params![league_id, manager_id], |row| {
            Ok(TransferEventRow {
                league_id: row.get(0)?,
                manager_id: row.get(1)?,
                player_id: row.get(2)?,
                player_name: row.get(3)?,
                team_id: row.get(4)?,
                club_name: row.get(5)?,
                transfer_type: row.get(6)?,
                price: row.get(7)?,
                transferred_at: row.get(8)?,
            })
        })
        .map_err(|_| CommandError::internal("Transfers konnten nicht gelesen werden."))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|_| CommandError::internal("Transfers konnten nicht gelesen werden."))
    }

    pub fn market_value_on_or_before(&self, player_id: &str, date: &str) -> Result<Option<i64>, CommandError> {
        self.conn.query_row(
            "SELECT value
             FROM market_values
             WHERE player_id=?1 AND snapshot_date<=substr(?2,1,10) AND value>0
             ORDER BY snapshot_date DESC,id DESC LIMIT 1",
            params![player_id, date],
            |row| row.get(0),
        )
        .optional()
        .map_err(|_| CommandError::internal("Marktwert am Transfertag konnte nicht gelesen werden."))
    }

    pub fn earliest_market_value_on_or_before(&self, player_id: &str, date: &str) -> Result<Option<(String, i64)>, CommandError> {
        self.conn.query_row(
            "SELECT snapshot_date,value
             FROM market_values
             WHERE player_id=?1 AND snapshot_date<=substr(?2,1,10) AND value>0
             ORDER BY snapshot_date ASC,id ASC LIMIT 1",
            params![player_id, date],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(|_| CommandError::internal("Erster historischer Marktwert konnte nicht gelesen werden."))
    }

    pub fn latest_market_value(&self, player_id: &str) -> Result<Option<(String, i64)>, CommandError> {
        self.conn.query_row(
            "SELECT snapshot_date,value
             FROM market_values
             WHERE player_id=?1 AND value>0
             ORDER BY snapshot_date DESC,id DESC LIMIT 1",
            [player_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(|_| CommandError::internal("Aktueller historischer Marktwert konnte nicht gelesen werden."))
    }

    pub fn post_sale_market_value(&self, player_id: &str, sale_date: &str, days: i64) -> Result<Option<i64>, CommandError> {
        let days_plus_one = days + 1;
        self.conn.query_row(
            "SELECT value
             FROM market_values
             WHERE player_id=?1
               AND snapshot_date>=date(substr(?2,1,10), printf('+%d days',?3))
               AND snapshot_date<date(substr(?2,1,10), printf('+%d days',?4))
               AND value>0
             ORDER BY snapshot_date ASC,id DESC LIMIT 1",
            params![player_id, sale_date, days, days_plus_one],
            |row| row.get(0),
        )
        .optional()
        .map_err(|_| CommandError::internal("Marktwert nach Verkauf konnte nicht gelesen werden."))
    }

    pub fn days_between(&self, start: &str, end: Option<&str>) -> Result<Option<i64>, CommandError> {
        let value: Option<i64> = if let Some(end) = end {
            self.conn.query_row(
                "SELECT CAST(julianday(?2)-julianday(?1) AS INTEGER)",
                params![start, end],
                |row| row.get(0),
            ).optional()
        } else {
            self.conn.query_row(
                "SELECT CAST(julianday('now')-julianday(?1) AS INTEGER)",
                [start],
                |row| row.get(0),
            ).optional()
        }
        .map_err(|_| CommandError::internal("Haltedauer konnte nicht berechnet werden."))?;
        Ok(value.map(|value| value.max(0)))
    }

}
