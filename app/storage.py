from __future__ import annotations

import os
import platform
import sqlite3
import json
import threading
from datetime import UTC, date, datetime
from pathlib import Path

from app.teams import TEAM_NAMES


POSITION_MAP = {
    "1": "TW",
    "2": "ABW",
    "3": "MF",
    "4": "ST",
    1: "TW",
    2: "ABW",
    3: "MF",
    4: "ST",
}


def normalize_position(position) -> str:
    if position is None:
        return ""
    return POSITION_MAP.get(position, POSITION_MAP.get(str(position), str(position)))


def app_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.getenv("APPDATA", Path.home()))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "KickTrack"
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = app_data_dir() / "kicktrack.db"


class Storage:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._migrate()
        self._repair_current_team_names()

    def _new_connection(self) -> sqlite3.Connection:
        """Create a SQLite connection owned by the current thread.

        Qt background workers must never reuse a connection that was created
        by the UI thread. Each thread therefore gets its own lightweight
        connection while all threads still operate on the same database file.
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        # WAL allows readers and a writer to coexist much better during
        # background refreshes without weakening SQLite's thread checks.
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _repair_current_team_names(self) -> None:
        """Keep current squad club labels aligned with the canonical team-id map.

        This intentionally updates only current squad tables. Historical transfer
        rows retain the club label from the transfer date.
        """
        for team_id, club in TEAM_NAMES.items():
            self.conn.execute(
                "UPDATE players SET club = ? WHERE team_id = ? AND COALESCE(club, '') <> ?",
                (club, team_id, club),
            )
            self.conn.execute(
                "UPDATE league_manager_players SET club = ? WHERE team_id = ? AND COALESCE(club, '') <> ?",
                (club, team_id, club),
            )
        self.conn.commit()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS players(
                player_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                club TEXT,
                team_id TEXT,
                position TEXT,
                entry_value INTEGER,
                purchase_price INTEGER,
                purchase_date TEXT,
                origin TEXT DEFAULT 'UNKNOWN',
                player_status TEXT DEFAULT 'KADER',
                daily_change INTEGER,
                api_gain_loss INTEGER,
                api_long_change INTEGER,
                team_image TEXT,
                kickbase_status INTEGER,
                points_total INTEGER,
                average_points INTEGER,
                player_role TEXT DEFAULT 'OFFEN'
            );

            CREATE TABLE IF NOT EXISTS market_values(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                value INTEGER NOT NULL,
                snapshot_date TEXT,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dashboard_snapshots(
                league_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                team_value INTEGER NOT NULL,
                budget INTEGER,
                total_assets INTEGER,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(league_id, snapshot_date)
            );

            CREATE TABLE IF NOT EXISTS manager_transfers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team_id TEXT,
                club TEXT,
                transfer_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                transferred_at TEXT NOT NULL,
                team_image TEXT,
                UNIQUE(league_id, player_id, transfer_type, price, transferred_at)
            );

            CREATE TABLE IF NOT EXISTS league_managers(
                league_id TEXT NOT NULL,
                manager_id TEXT NOT NULL,
                name TEXT NOT NULL,
                profile_image TEXT,
                is_user INTEGER NOT NULL DEFAULT 0,
                team_value INTEGER,
                profit INTEGER,
                points INTEGER,
                average_points INTEGER,
                matchday_wins INTEGER,
                place INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(league_id, manager_id)
            );

            CREATE TABLE IF NOT EXISTS api_cache(
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS league_manager_players(
                league_id TEXT NOT NULL,
                manager_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                name TEXT NOT NULL,
                club TEXT,
                team_id TEXT,
                position TEXT,
                market_value INTEGER,
                points_total INTEGER,
                average_points INTEGER,
                team_image TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(league_id, manager_id, player_id)
            );

            CREATE TABLE IF NOT EXISTS league_manager_transfers(
                league_id TEXT NOT NULL,
                manager_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team_id TEXT,
                club TEXT,
                transfer_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                transferred_at TEXT NOT NULL,
                team_image TEXT,
                observed_at TEXT NOT NULL,
                PRIMARY KEY(league_id, manager_id, player_id, transfer_type, price, transferred_at)
            );

            CREATE TABLE IF NOT EXISTS analytics_decisions(
                league_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                signal TEXT NOT NULL,
                market_value INTEGER,
                market_price INTEGER,
                max_bid INTEGER,
                investment_score INTEGER,
                squad_fit_score INTEGER,
                confidence_score INTEGER,
                investment_horizon TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(league_id, player_id, decision_date)
            );
            """
        )

        self._ensure_column("players", "team_id", "TEXT")
        self._ensure_column("players", "entry_value", "INTEGER")
        self._ensure_column("players", "purchase_price", "INTEGER")
        self._ensure_column("players", "purchase_date", "TEXT")
        self._ensure_column("players", "origin", "TEXT DEFAULT 'UNKNOWN'")
        self._ensure_column("players", "player_status", "TEXT DEFAULT 'KADER'")
        self._ensure_column("players", "daily_change", "INTEGER")
        self._ensure_column("players", "api_gain_loss", "INTEGER")
        self._ensure_column("players", "api_long_change", "INTEGER")
        self._ensure_column("players", "team_image", "TEXT")
        self._ensure_column("players", "kickbase_status", "INTEGER")
        self._ensure_column("players", "points_total", "INTEGER")
        self._ensure_column("players", "average_points", "INTEGER")
        self._ensure_column("players", "player_role", "TEXT DEFAULT 'OFFEN'")
        self.conn.execute("UPDATE players SET player_role = 'OFFEN' WHERE player_role IS NULL OR player_role = ''")
        self._ensure_column("market_values", "snapshot_date", "TEXT")

        self.conn.execute(
            """
            UPDATE market_values
            SET snapshot_date = SUBSTR(recorded_at, 1, 10)
            WHERE snapshot_date IS NULL OR snapshot_date = ''
            """
        )
        self.conn.execute(
            """
            DELETE FROM market_values
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM market_values
                GROUP BY player_id, snapshot_date
            )
            """
        )
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_market_values_player_day
            ON market_values(player_id, snapshot_date)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_market_values_player_date
            ON market_values(player_id, snapshot_date DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dashboard_snapshots_league_date
            ON dashboard_snapshots(league_id, snapshot_date DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manager_transfers_league_date
            ON manager_transfers(league_id, transferred_at DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_league_manager_transfers_manager_date
            ON league_manager_transfers(league_id, manager_id, transferred_at DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_league_managers_place
            ON league_managers(league_id, place)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_league_manager_players_owner
            ON league_manager_players(league_id, manager_id)
            """
        )

        for raw, normalized in (("1", "TW"), ("2", "ABW"), ("3", "MF"), ("4", "ST")):
            self.conn.execute(
                "UPDATE players SET position = ? WHERE position = ?",
                (normalized, raw),
            )

        self.conn.commit()

    def _ensure_column(self, table: str, column: str, sql_type: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            self.conn.commit()

    # ------------------------------------------------------------------
    # Analytics decision log / lightweight backtesting
    # ------------------------------------------------------------------

    def record_market_decisions(self, league_id: str, rows: list[dict]) -> None:
        today = date.today().isoformat()
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        payload = []
        for row in rows:
            player_id = row.get("player_id")
            signal = row.get("signal")
            if not player_id or not signal:
                continue
            payload.append((
                str(league_id), str(player_id), today, str(signal),
                int(row.get("market_value") or 0), int(row.get("price") or 0),
                int(row.get("max_bid") or 0) if row.get("max_bid") is not None else None,
                int(row.get("investment_score") or 0), int(row.get("squad_fit_score") or 0),
                int(row.get("confidence_score") or 0), str(row.get("investment_horizon") or ""), now,
            ))
        if not payload:
            return
        self.conn.executemany(
            """
            INSERT INTO analytics_decisions(
                league_id, player_id, decision_date, signal, market_value, market_price,
                max_bid, investment_score, squad_fit_score, confidence_score, investment_horizon, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(league_id, player_id, decision_date) DO UPDATE SET
                signal=excluded.signal, market_value=excluded.market_value, market_price=excluded.market_price,
                max_bid=excluded.max_bid, investment_score=excluded.investment_score,
                squad_fit_score=excluded.squad_fit_score, confidence_score=excluded.confidence_score,
                investment_horizon=excluded.investment_horizon, created_at=excluded.created_at
            """, payload
        )
        self.conn.commit()

    def decision_backtest_summary(self, league_id: str) -> dict:
        """Evaluate decision separation after seven days.

        The primary metric is the return spread between BUY-like and PASS calls.
        Directional hit-rate remains for compatibility, but a BUY must gain at
        least 1% to count as a meaningful hit rather than winning by one euro.
        """
        rows = self.conn.execute(
            """
            SELECT d.*, (
                SELECT mv.value FROM market_values mv
                WHERE mv.player_id=d.player_id
                  AND mv.snapshot_date >= date(d.decision_date, '+7 day')
                ORDER BY mv.snapshot_date ASC LIMIT 1
            ) AS value_7d
            FROM analytics_decisions d
            WHERE d.league_id=?
            """, (str(league_id),)
        ).fetchall()
        evaluated = 0
        correct = 0
        all_returns: list[float] = []
        buy_returns: list[float] = []
        pass_returns: list[float] = []
        for raw in rows:
            row = dict(raw)
            start = int(row.get("market_value") or 0)
            end = int(row.get("value_7d") or 0)
            if start <= 0 or end <= 0:
                continue
            ret = (end - start) / start * 100.0
            bullish = row.get("signal") in {"KAUFEN", "TOP-CHANCE", "INVEST-CHANCE", "KADER-UPGRADE", "KAUFPRÜFUNG"}
            bearish = row.get("signal") == "PASSEN"
            if not bullish and not bearish:
                continue
            evaluated += 1
            all_returns.append(ret)
            if bullish:
                buy_returns.append(ret)
                if ret >= 1.0:
                    correct += 1
            else:
                pass_returns.append(ret)
                if ret <= 0.0:
                    correct += 1

        buy_avg = (sum(buy_returns) / len(buy_returns)) if buy_returns else None
        pass_avg = (sum(pass_returns) / len(pass_returns)) if pass_returns else None
        spread = (buy_avg - pass_avg) if buy_avg is not None and pass_avg is not None else None
        return {
            "evaluated": evaluated,
            "correct": correct,
            "hit_rate": (correct / evaluated * 100.0) if evaluated else None,
            "avg_return_7d": (sum(all_returns) / len(all_returns)) if all_returns else None,
            "buy_avg_return_7d": buy_avg,
            "pass_avg_return_7d": pass_avg,
            "return_spread_7d": spread,
            "buy_count": len(buy_returns),
            "pass_count": len(pass_returns),
        }

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        self.conn.commit()

    def get_setting(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def get_int_setting(self, key: str, default: int | None = None) -> int | None:
        value = self.get_setting(key)
        if value is None:
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def league_setting_key(league_id: str, key: str) -> str:
        return f"league:{league_id}:{key}"

    def get_league_setting(self, league_id: str | None, key: str, default=None):
        if league_id:
            value = self.get_setting(self.league_setting_key(league_id, key))
            if value is not None:
                return value
        return self.get_setting(key, default)

    def get_league_int_setting(
        self, league_id: str | None, key: str, default: int | None = None
    ) -> int | None:
        value = self.get_league_setting(league_id, key)
        if value is None:
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # Players / squad
    # ------------------------------------------------------------------

    def begin_squad_sync(self) -> None:
        self.conn.execute("UPDATE players SET player_status = 'NICHT_IM_KADER'")
        self.conn.commit()

    def upsert_player(self, player: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO players(
                player_id, name, club, team_id, position, player_status,
                daily_change, api_gain_loss, api_long_change, team_image, kickbase_status,
                points_total, average_points
            )
            VALUES(?, ?, ?, ?, ?, 'KADER', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                name = excluded.name,
                club = CASE WHEN excluded.club IS NOT NULL AND excluded.club != '' THEN excluded.club ELSE players.club END,
                team_id = excluded.team_id,
                position = excluded.position,
                player_status = 'KADER',
                daily_change = excluded.daily_change,
                api_gain_loss = excluded.api_gain_loss,
                api_long_change = excluded.api_long_change,
                team_image = excluded.team_image,
                kickbase_status = excluded.kickbase_status,
                points_total = excluded.points_total,
                average_points = excluded.average_points
            """,
            (
                player["player_id"],
                player["name"],
                player.get("club"),
                player.get("team_id"),
                normalize_position(player.get("position")),
                player.get("daily_change"),
                player.get("market_gain_loss"),
                player.get("api_long_change"),
                player.get("team_image"),
                player.get("status"),
                player.get("points_total"),
                player.get("average_points"),
            ),
        )
        self.conn.commit()

    def set_acquisition(
        self,
        player_id: str,
        origin: str,
        entry_value: int | None,
        purchase_price: int | None,
        purchase_date: str | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE players
            SET origin = ?, entry_value = ?, purchase_price = ?, purchase_date = ?
            WHERE player_id = ?
            """,
            (origin, entry_value, purchase_price, purchase_date, player_id),
        )
        self.conn.commit()

    def set_player_role(self, player_id: str, role: str) -> None:
        role = (role or "OFFEN").upper()
        if role not in {"OFFEN", "STAMM", "INVEST", "TRANSFERLISTE"}:
            role = "OFFEN"
        self.conn.execute(
            "UPDATE players SET player_role = ? WHERE player_id = ?",
            (role, player_id),
        )
        self.conn.commit()

    def current_players(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT
                p.*,
                (SELECT mv.value FROM market_values mv
                    WHERE mv.player_id = p.player_id
                    ORDER BY mv.snapshot_date DESC, mv.recorded_at DESC LIMIT 1) AS market_value
            FROM players p
            WHERE p.player_status = 'KADER'
            ORDER BY market_value DESC, p.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_player(self, player_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT
                p.*,
                (SELECT mv.value FROM market_values mv
                    WHERE mv.player_id = p.player_id
                    ORDER BY mv.snapshot_date DESC, mv.recorded_at DESC LIMIT 1) AS market_value
            FROM players p
            WHERE p.player_id = ?
            """,
            (player_id,),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Market value snapshots / analytics
    # ------------------------------------------------------------------

    def snapshot_market_value(self, player_id: str, value: int) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        snapshot_date = now[:10]
        self.conn.execute(
            """
            INSERT INTO market_values(player_id, value, snapshot_date, recorded_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                value = excluded.value,
                recorded_at = excluded.recorded_at
            """,
            (player_id, int(value), snapshot_date, now),
        )
        self.conn.commit()


    def upsert_market_value_history(self, player_id: str, rows: list[dict]) -> None:
        """Persist remote historical MV points without overwriting newer same-day observations."""
        payload = []
        for row in rows or []:
            try:
                value = int(row.get("value") or 0)
                snapshot_date = str(row.get("snapshot_date") or "")[:10]
            except (TypeError, ValueError):
                continue
            if value <= 0 or len(snapshot_date) != 10:
                continue
            recorded_at = str(row.get("recorded_at") or snapshot_date)
            payload.append((str(player_id), value, snapshot_date, recorded_at))
        if not payload:
            return
        self.conn.executemany(
            """
            INSERT INTO market_values(player_id, value, snapshot_date, recorded_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                value = excluded.value,
                recorded_at = excluded.recorded_at
            """,
            payload,
        )
        self.conn.commit()

    def all_market_value_rows(self) -> list[dict]:
        """Return all persisted daily market-value observations for model calibration."""
        rows = self.conn.execute(
            """SELECT player_id, value, snapshot_date, recorded_at
               FROM market_values
               ORDER BY snapshot_date ASC, player_id ASC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def all_history(self, player_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT value, snapshot_date, recorded_at FROM market_values
               WHERE player_id = ? ORDER BY snapshot_date ASC, recorded_at ASC""",
            (str(player_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def history(self, player_id: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT value, snapshot_date, recorded_at
            FROM market_values
            WHERE player_id = ?
            ORDER BY snapshot_date DESC, recorded_at DESC
            LIMIT ?
            """,
            (player_id, limit),
        ).fetchall()
        result = [dict(row) for row in rows]
        result.reverse()
        return result

    def analytics(self, player_id: str) -> dict:
        player = self.get_player(player_id) or {}
        history = self.history(player_id, 30)
        if not history:
            return {"d1": player.get("daily_change"), "d3": None, "d7": None}

        latest = history[-1]
        latest_value = latest["value"]
        latest_date = date.fromisoformat(latest["snapshot_date"])

        def delta_days(days: int) -> int | None:
            target = latest_date.toordinal() - days
            comparison = None
            for entry in history:
                entry_date = date.fromisoformat(entry["snapshot_date"])
                if entry_date.toordinal() <= target:
                    comparison = entry
            if comparison is None:
                return None
            return latest_value - comparison["value"]

        d1 = player.get("daily_change")
        d3 = delta_days(3)
        d7 = delta_days(7)
        d14 = delta_days(14)
        # Compare non-overlapping windows. d7 already contains d3, so using
        # d3/3 versus d7/7 double-counts the recent three days and understates
        # real acceleration. The previous velocity is days 4-7 only.
        v3 = (float(d3) / 3.0) if d3 is not None else None
        previous_v4 = ((float(d7) - float(d3)) / 4.0) if d3 is not None and d7 is not None else None
        v7 = (float(d7) / 7.0) if d7 is not None else None
        acceleration = (v3 - previous_v4) if v3 is not None and previous_v4 is not None else None
        return {
            "d1": d1,
            "d3": d3,
            "d7": d7,
            "d14": d14,
            "trend_velocity_3d": v3,
            "trend_velocity_7d": v7,
            "trend_velocity_previous_4d": previous_v4,
            "trend_acceleration": acceleration,
        }


    def apply_sync_result(self, result) -> None:
        """Persist one fetched league snapshot atomically.

        A sync either becomes fully visible to the UI or not at all. This avoids
        partially updated squads when a database write fails halfway through.
        """
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        snapshot_date = now[:10]

        with self.conn:
            self.conn.execute("UPDATE players SET player_status = 'NICHT_IM_KADER'")

            for player in result.players:
                self.conn.execute(
                    """
                    INSERT INTO players(
                        player_id, name, club, team_id, position, player_status,
                        daily_change, api_gain_loss, api_long_change, team_image, kickbase_status,
                        points_total, average_points
                    ) VALUES(?, ?, ?, ?, ?, 'KADER', ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        name = excluded.name,
                        club = CASE WHEN excluded.club IS NOT NULL AND excluded.club != '' THEN excluded.club ELSE players.club END,
                        team_id = excluded.team_id,
                        position = excluded.position,
                        player_status = 'KADER',
                        daily_change = excluded.daily_change,
                        api_gain_loss = excluded.api_gain_loss,
                        api_long_change = excluded.api_long_change,
                        team_image = excluded.team_image,
                        kickbase_status = excluded.kickbase_status,
                        points_total = excluded.points_total,
                        average_points = excluded.average_points
                    """,
                    (
                        player["player_id"], player["name"], player.get("club"),
                        player.get("team_id"), normalize_position(player.get("position")),
                        player.get("daily_change"), player.get("market_gain_loss"),
                        player.get("api_long_change"), player.get("team_image"), player.get("status"),
                        player.get("points_total"), player.get("average_points"),
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO market_values(player_id, value, snapshot_date, recorded_at)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                        value = excluded.value, recorded_at = excluded.recorded_at
                    """,
                    (player["player_id"], int(player["market_value"]), snapshot_date, now),
                )

                acquisition = result.acquisitions.get(player["player_id"])
                if acquisition:
                    self.conn.execute(
                        """
                        UPDATE players
                        SET origin = ?, entry_value = ?, purchase_price = ?, purchase_date = ?
                        WHERE player_id = ?
                        """,
                        (
                            acquisition.get("origin"), acquisition.get("entry_value"),
                            acquisition.get("purchase_price"), acquisition.get("purchase_date"),
                            player["player_id"],
                        ),
                    )

            self.conn.execute("DELETE FROM manager_transfers WHERE league_id = ?", (result.league_id,))
            self.conn.executemany(
                """
                INSERT INTO manager_transfers(
                    league_id, player_id, player_name, team_id, club,
                    transfer_type, price, transferred_at, team_image
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.league_id, transfer["player_id"], transfer["player_name"],
                        transfer.get("team_id"), transfer.get("club"), transfer["transfer_type"],
                        transfer["price"], transfer["transferred_at"], transfer.get("team_image"),
                    )
                    for transfer in result.transfers
                ],
            )

            settings = {"league_id": result.league_id}
            if result.manager_id:
                settings["manager_id"] = result.manager_id
                settings[self.league_setting_key(result.league_id, "manager_id")] = result.manager_id
            if result.dashboard.get("profit") is not None:
                settings["kickbase_profit"] = result.dashboard["profit"]
                settings[self.league_setting_key(result.league_id, "kickbase_profit")] = result.dashboard["profit"]
            if result.dashboard.get("team_value") is not None:
                settings["kickbase_team_value"] = result.dashboard["team_value"]
                settings[self.league_setting_key(result.league_id, "kickbase_team_value")] = result.dashboard["team_value"]
            if result.league_info.get("budget") is not None:
                settings["budget"] = result.league_info["budget"]
                settings[self.league_setting_key(result.league_id, "budget")] = result.league_info["budget"]

            team_value = result.dashboard.get("team_value")
            if team_value is None or int(team_value or 0) <= 0:
                team_value = sum(int(player.get("market_value") or 0) for player in result.players)
            budget = result.league_info.get("budget")
            total_assets = int(team_value) + int(budget) if budget is not None else None
            self.conn.execute(
                """
                INSERT INTO dashboard_snapshots(
                    league_id, snapshot_date, team_value, budget, total_assets, recorded_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(league_id, snapshot_date) DO UPDATE SET
                    team_value = excluded.team_value,
                    budget = excluded.budget,
                    total_assets = excluded.total_assets,
                    recorded_at = excluded.recorded_at
                """,
                (result.league_id, snapshot_date, int(team_value), budget, total_assets, now),
            )

            self.conn.executemany(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                [(key, str(value)) for key, value in settings.items()],
            )

    def team_value_history(self, league_id: str | None, days: int = 90) -> list[dict]:
        if not league_id:
            return []
        rows = self.conn.execute(
            """
            SELECT snapshot_date, team_value, budget, total_assets, recorded_at
            FROM dashboard_snapshots
            WHERE league_id = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (str(league_id), max(1, int(days))),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ------------------------------------------------------------------
    # Persistent API cache
    # ------------------------------------------------------------------

    def cache_get(self, key: str, max_age_seconds: int | None = None):
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM api_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if max_age_seconds is not None:
            try:
                fetched = datetime.fromisoformat(str(row["fetched_at"]).replace("Z", "+00:00"))
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - fetched.astimezone(UTC)).total_seconds()
                if age > max(0, int(max_age_seconds)):
                    return None
            except (TypeError, ValueError):
                return None
        try:
            return json.loads(row["payload"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def cache_set(self, key: str, payload) -> None:
        fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        self.conn.execute(
            """
            INSERT INTO api_cache(cache_key, payload, fetched_at) VALUES(?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload, fetched_at = excluded.fetched_at
            """,
            (key, json.dumps(payload, ensure_ascii=False), fetched_at),
        )
        self.conn.commit()

    def cache_delete(self, key: str) -> None:
        self.conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (key,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # League analysis cache
    # ------------------------------------------------------------------

    def replace_league_managers(self, result) -> None:
        """Replace cached manager summaries for one league atomically."""
        with self.conn:
            self.conn.execute("DELETE FROM league_managers WHERE league_id = ?", (result.league_id,))
            # Manager squads have their own TTL. Keep them across an overview
            # refresh so the persistent ownership cache remains useful.
            self.conn.executemany(
                """
                INSERT INTO league_managers(
                    league_id, manager_id, name, profile_image, is_user, team_value,
                    profit, points, average_points, matchday_wins, place, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.league_id, manager.manager_id, manager.name,
                        manager.profile_image, 1 if manager.is_user else 0,
                        manager.team_value, manager.profit, manager.points,
                        manager.average_points, manager.matchday_wins, manager.place,
                        result.fetched_at,
                    )
                    for manager in result.managers
                ],
            )
            if result.matchday is not None:
                key = self.league_setting_key(result.league_id, "matchday")
                self.conn.execute(
                    """
                    INSERT INTO settings(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(result.matchday)),
                )
            season_key = self.league_setting_key(result.league_id, "season_started")
            self.conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (season_key, "1" if bool(getattr(result, "season_started", False)) else "0"),
            )

    @staticmethod
    def _timestamp_is_fresh(value: str | None, max_age_seconds: int) -> bool:
        if not value:
            return False
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return (datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds() <= max(0, int(max_age_seconds))
        except (TypeError, ValueError):
            return False

    def league_managers_are_fresh(self, league_id: str, max_age_seconds: int) -> bool:
        row = self.conn.execute(
            "SELECT MAX(updated_at) AS updated_at, COUNT(*) AS count FROM league_managers WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        return bool(row and int(row["count"] or 0) > 0 and self._timestamp_is_fresh(row["updated_at"], max_age_seconds))

    def league_managers(self, league_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM league_managers
            WHERE league_id = ?
            ORDER BY CASE WHEN place IS NULL THEN 1 ELSE 0 END, place, name COLLATE NOCASE
            """,
            (league_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_league_manager(self, league_id: str, manager_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM league_managers WHERE league_id = ? AND manager_id = ?",
            (league_id, manager_id),
        ).fetchone()
        return dict(row) if row else None

    def replace_manager_squad(self, result) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM league_manager_players WHERE league_id = ? AND manager_id = ?",
                (result.league_id, result.manager_id),
            )
            self.conn.executemany(
                """
                INSERT INTO league_manager_players(
                    league_id, manager_id, player_id, name, club, team_id, position,
                    market_value, points_total, average_points, team_image, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.league_id, result.manager_id, player["player_id"],
                        player["name"], player.get("club"), player.get("team_id"),
                        normalize_position(player.get("position")), player.get("market_value"),
                        player.get("points_total"), player.get("average_points"),
                        player.get("team_image"), result.fetched_at,
                    )
                    for player in result.players
                ],
            )

    def manager_squad_is_fresh(self, league_id: str, manager_id: str, max_age_seconds: int) -> bool:
        row = self.conn.execute(
            """
            SELECT MAX(updated_at) AS updated_at, COUNT(*) AS count
            FROM league_manager_players
            WHERE league_id = ? AND manager_id = ?
            """,
            (league_id, manager_id),
        ).fetchone()
        return bool(row and int(row["count"] or 0) > 0 and self._timestamp_is_fresh(row["updated_at"], max_age_seconds))

    def manager_squad(self, league_id: str, manager_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM league_manager_players
            WHERE league_id = ? AND manager_id = ?
            ORDER BY market_value DESC, name COLLATE NOCASE
            """,
            (league_id, manager_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def league_player(self, league_id: str, player_id: str) -> dict | None:
        """Return the richest cached current-league row for a player, regardless of owner."""
        row = self.conn.execute(
            """
            SELECT lmp.*
            FROM league_manager_players lmp
            WHERE lmp.league_id = ? AND lmp.player_id = ?
            ORDER BY lmp.updated_at DESC
            LIMIT 1
            """,
            (league_id, player_id),
        ).fetchone()
        return dict(row) if row else None

    def player_owner(self, league_id: str, player_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT lm.manager_id, lm.name AS manager_name, lm.place, lm.is_user, lmp.updated_at
            FROM league_manager_players lmp
            JOIN league_managers lm
              ON lm.league_id = lmp.league_id AND lm.manager_id = lmp.manager_id
            WHERE lmp.league_id = ? AND lmp.player_id = ?
            LIMIT 1
            """,
            (league_id, player_id),
        ).fetchone()
        return dict(row) if row else None

    def replace_league_ownership(self, result) -> None:
        """Replace the league-wide ownership index atomically.

        A full sync marker is only written when every requested manager squad
        was fetched successfully. Partial data remains usable for known owners,
        but the UI will not label unknown players as free until coverage is full.
        """
        now = getattr(result, "fetched_at", None) or datetime.now(UTC).replace(microsecond=0).isoformat()
        with self.conn:
            self.conn.execute(
                "DELETE FROM league_manager_players WHERE league_id = ?",
                (result.league_id,),
            )
            for squad in result.squads:
                self.conn.executemany(
                    """
                    INSERT INTO league_manager_players(
                        league_id, manager_id, player_id, name, club, team_id, position,
                        market_value, points_total, average_points, team_image, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            squad.league_id, squad.manager_id, player["player_id"],
                            player["name"], player.get("club"), player.get("team_id"),
                            normalize_position(player.get("position")), player.get("market_value"),
                            player.get("points_total"), player.get("average_points"),
                            player.get("team_image"), squad.fetched_at,
                        )
                        for player in squad.players
                    ],
                )

            key = self.league_setting_key(result.league_id, "ownership_synced_at")
            if not getattr(result, "failed_manager_ids", []):
                self.conn.execute(
                    """
                    INSERT INTO settings(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, now),
                )
            else:
                self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def league_ownership_is_fresh(self, league_id: str, max_age_seconds: int) -> bool:
        value = self.get_league_setting(league_id, "ownership_synced_at")
        return self._timestamp_is_fresh(value, max_age_seconds)

    def ownership_coverage(self, league_id: str) -> tuple[int, int]:
        total_row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM league_managers WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        covered_row = self.conn.execute(
            """
            SELECT COUNT(DISTINCT manager_id) AS count
            FROM league_manager_players
            WHERE league_id = ?
            """,
            (league_id,),
        ).fetchone()
        return int(covered_row["count"] or 0), int(total_row["count"] or 0)

    # ------------------------------------------------------------------
    # League manager transfer history
    # ------------------------------------------------------------------

    def upsert_league_manager_transfers(
        self, league_id: str, manager_id: str, transfers: list[dict]
    ) -> None:
        observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        for transfer in transfers:
            self.conn.execute(
                """
                INSERT INTO league_manager_transfers(
                    league_id, manager_id, player_id, player_name, team_id, club,
                    transfer_type, price, transferred_at, team_image, observed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(league_id, manager_id, player_id, transfer_type, price, transferred_at)
                DO UPDATE SET
                    player_name=excluded.player_name,
                    team_id=excluded.team_id,
                    club=excluded.club,
                    team_image=excluded.team_image,
                    observed_at=excluded.observed_at
                """,
                (
                    league_id, manager_id, transfer.get("player_id"),
                    transfer.get("player_name") or "Unbekannt", transfer.get("team_id"),
                    transfer.get("club"), transfer.get("transfer_type"),
                    int(transfer.get("price") or 0), transfer.get("transferred_at") or "",
                    transfer.get("team_image"), observed_at,
                ),
            )
        self.conn.commit()

    def league_manager_transfers_are_fresh(
        self, league_id: str, manager_id: str, max_age_seconds: int = 3600
    ) -> bool:
        row = self.conn.execute(
            """
            SELECT MAX(observed_at) AS observed_at, COUNT(*) AS count
            FROM league_manager_transfers
            WHERE league_id = ? AND manager_id = ?
            """,
            (league_id, manager_id),
        ).fetchone()
        return bool(
            row
            and int(row["count"] or 0) > 0
            and self._timestamp_is_fresh(row["observed_at"], max_age_seconds)
        )

    def league_manager_transfer_rows(
        self, league_id: str, manager_id: str, *, since: str | None = None
    ) -> list[dict]:
        if since:
            rows = self.conn.execute(
                """
                SELECT * FROM league_manager_transfers
                WHERE league_id = ? AND manager_id = ?
                  AND DATE(transferred_at) >= DATE(?)
                ORDER BY transferred_at DESC
                """,
                (league_id, manager_id, since),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM league_manager_transfers
                WHERE league_id = ? AND manager_id = ?
                ORDER BY transferred_at DESC
                """,
                (league_id, manager_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def league_all_manager_transfer_rows(self, league_id: str, *, since: str | None = None) -> list[dict]:
        if since:
            rows = self.conn.execute(
                """
                SELECT * FROM league_manager_transfers
                WHERE league_id = ? AND DATE(transferred_at) >= DATE(?)
                ORDER BY transferred_at DESC
                """,
                (league_id, since),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM league_manager_transfers
                WHERE league_id = ?
                ORDER BY transferred_at DESC
                """,
                (league_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Manager transfers
    # ------------------------------------------------------------------

    def replace_manager_transfers(self, league_id: str, transfers: list[dict]) -> None:
        self.conn.execute("DELETE FROM manager_transfers WHERE league_id = ?", (league_id,))
        for transfer in transfers:
            self.conn.execute(
                """
                INSERT INTO manager_transfers(
                    league_id, player_id, player_name, team_id, club,
                    transfer_type, price, transferred_at, team_image
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    league_id,
                    transfer["player_id"],
                    transfer["player_name"],
                    transfer.get("team_id"),
                    transfer.get("club"),
                    transfer["transfer_type"],
                    transfer["price"],
                    transfer["transferred_at"],
                    transfer.get("team_image"),
                ),
            )
        self.conn.commit()

    def transfer_rows(self, league_id: str | None = None) -> list[dict]:
        if league_id:
            rows = self.conn.execute(
                """
                SELECT * FROM manager_transfers
                WHERE league_id = ?
                ORDER BY transferred_at DESC
                """,
                (league_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM manager_transfers
                ORDER BY transferred_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def transfer_stats(self, league_id: str | None) -> dict:
        rows = self.transfer_rows(league_id)
        if not rows and league_id:
            # Fallback: Falls bei alten Datensätzen die Liga-ID anders gespeichert wurde,
            # zeigen wir lieber vorhandene Transfers als stumpf 0 an.
            rows = self.transfer_rows(None)
        buys = [row for row in rows if row["transfer_type"] == "BUY"]
        sells = [row for row in rows if row["transfer_type"] == "SELL"]
        return {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "buy_volume": sum(row["price"] for row in buys),
            "sell_volume": sum(row["price"] for row in sells),
            "total_count": len(rows),
        }

    # ------------------------------------------------------------------
    # Aggregate performance
    # ------------------------------------------------------------------

    def current_open_pnl(self) -> int:
        total = 0
        for player in self.current_players():
            entry = player.get("entry_value")
            market_value = player.get("market_value")
            if entry is not None and market_value is not None:
                total += int(market_value) - int(entry)
        return total

    def current_team_value(self) -> int:
        return sum(int(player.get("market_value") or 0) for player in self.current_players())

    def current_daily_change(self) -> int:
        return sum(int(player.get("daily_change") or 0) for player in self.current_players())

    def dashboard_metrics(self, league_id: str | None = None) -> dict:
        open_pnl = self.current_open_pnl()
        kickbase_profit = self.get_league_int_setting(league_id, "kickbase_profit")
        team_value_api = self.get_league_int_setting(league_id, "kickbase_team_value")
        team_value = team_value_api if team_value_api is not None else self.current_team_value()
        budget = self.get_league_int_setting(league_id, "budget")
        daily = self.current_daily_change()
        realized = kickbase_profit - open_pnl if kickbase_profit is not None else None
        total_assets = team_value + budget if budget is not None else None
        transfers = self.transfer_stats(league_id)
        return {
            "team_value": team_value,
            "budget": budget,
            "daily_change": daily,
            "open_pnl": open_pnl,
            "realized_pnl": realized,
            "total_pnl": kickbase_profit,
            "total_assets": total_assets,
            **transfers,
        }

    def close(self) -> None:
        """Close the SQLite connection owned by the current thread."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            del self._local.conn
