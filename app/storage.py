from __future__ import annotations

import os
import platform
import sqlite3
import json
import threading
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo
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


def bundled_assets_dir() -> Path:
    """Return the source/PyInstaller assets directory.

    PyInstaller rewrites ``__file__`` into its bundle root, so resolving from
    this module works both from source and from an onedir distribution.
    """
    return Path(__file__).resolve().parent.parent / "assets"


def bundled_portrait_path(player_id: str) -> Path | None:
    portrait_dir = bundled_assets_dir() / "portraits"
    pid = str(player_id).strip()
    if not pid or not portrait_dir.exists():
        return None
    for suffix in (".png", ".webp", ".jpg", ".jpeg"):
        candidate = portrait_dir / f"{pid}{suffix}"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


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

            CREATE TABLE IF NOT EXISTS player_master(
                player_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                full_name TEXT,
                club TEXT,
                team_id TEXT,
                position TEXT,
                active_state TEXT NOT NULL DEFAULT 'ACTIVE',
                miss_count INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_sync_at TEXT NOT NULL,
                market_value INTEGER,
                points_total INTEGER,
                average_points INTEGER,
                fotmob_id TEXT,
                portrait_url TEXT,
                portrait_path TEXT,
                portrait_state TEXT NOT NULL DEFAULT 'MISSING',
                portrait_confidence INTEGER,
                portrait_reason TEXT,
                portrait_candidate_name TEXT,
                portrait_candidate_team TEXT,
                portrait_candidate_position TEXT,
                portrait_candidate_shirt_number TEXT,
                portrait_checked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_player_master_active
                ON player_master(active_state);
            CREATE INDEX IF NOT EXISTS idx_player_master_portrait
                ON player_master(portrait_state);

            CREATE TABLE IF NOT EXISTS watchlist(
                league_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY(league_id, player_id)
            );

            CREATE INDEX IF NOT EXISTS idx_watchlist_league
                ON watchlist(league_id, added_at DESC);

            CREATE TABLE IF NOT EXISTS mv_predictions(
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
                prediction_source TEXT,
                actual_value INTEGER,
                actual_delta INTEGER,
                absolute_error INTEGER,
                signed_error INTEGER,
                direction_hit INTEGER,
                evaluated_at TEXT,
                PRIMARY KEY(league_id, player_id, target_date)
            );
            """
        )

        self._ensure_column("players", "team_id", "TEXT")
        self._ensure_column("players", "entry_value", "INTEGER")
        self._ensure_column("players", "purchase_price", "INTEGER")
        self._ensure_column("players", "purchase_date", "TEXT")
        self._ensure_column("market_values", "source", "TEXT")
        self._ensure_column("mv_predictions", "actual_snapshot_date", "TEXT")
        self._ensure_column("mv_predictions", "actual_recorded_at", "TEXT")
        self._ensure_column("mv_predictions", "evaluation_source", "TEXT")
        self._ensure_column("mv_predictions", "prediction_source", "TEXT")
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
        self._ensure_column("player_master", "portrait_candidate_name", "TEXT")
        self._ensure_column("player_master", "portrait_candidate_team", "TEXT")
        self._ensure_column("player_master", "portrait_candidate_position", "TEXT")
        self._ensure_column("player_master", "portrait_candidate_shirt_number", "TEXT")
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
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mv_predictions_target
            ON mv_predictions(league_id, target_date DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mv_predictions_evaluated
            ON mv_predictions(league_id, evaluated_at, target_date DESC)
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
    # Market-value prediction tracking / model evaluation
    # ------------------------------------------------------------------

    def record_mv_predictions(
        self,
        league_id: str,
        predictions: dict[str, dict],
        *,
        current_values: dict[str, int],
        current_deltas: dict[str, int] | None = None,
        target_date: str | date,
        sources: dict[str, str] | None = None,
    ) -> int:
        """Store the latest pre-refresh forecast for each player/target day.

        Repeated refreshes before 22:00 intentionally replace the earlier forecast
        for the same player/day. That means evaluation measures the prediction the
        user actually saw closest to the market-value refresh.
        """
        if isinstance(target_date, date):
            target = target_date.isoformat()
        else:
            target = str(target_date)[:10]
            date.fromisoformat(target)  # validate

        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        current_deltas = {str(k): int(v) for k, v in (current_deltas or {}).items() if v is not None}
        sources = {str(k): str(v) for k, v in (sources or {}).items() if v}
        payload = []
        for player_id, raw in (predictions or {}).items():
            pid = str(player_id)
            if pid not in current_values:
                continue
            try:
                baseline = int(current_values[pid])
                pred_delta = int(raw.get("delta"))
                expected = int(raw.get("expected_value"))
            except (TypeError, ValueError):
                continue
            if baseline <= 0 or expected <= 0:
                continue
            payload.append((
                str(league_id), pid, target, now, baseline,
                current_deltas.get(pid, raw.get("baseline_delta")), pred_delta, expected,
                int(raw.get("low_delta")) if raw.get("low_delta") is not None else None,
                int(raw.get("high_delta")) if raw.get("high_delta") is not None else None,
                str(raw.get("confidence") or ""),
                int(raw.get("sample_count") or 0),
                int(raw.get("history_days") or 0),
                str(raw.get("method") or ""),
                sources.get(pid, "MARKET"),
            ))
        if not payload:
            return 0
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO mv_predictions(
                    league_id, player_id, target_date, predicted_at,
                    baseline_value, baseline_delta, predicted_delta, expected_value,
                    low_delta, high_delta, confidence, sample_count, history_days, method, prediction_source
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(league_id, player_id, target_date) DO UPDATE SET
                    predicted_at=excluded.predicted_at,
                    baseline_value=excluded.baseline_value,
                    baseline_delta=excluded.baseline_delta,
                    predicted_delta=excluded.predicted_delta,
                    expected_value=excluded.expected_value,
                    low_delta=excluded.low_delta,
                    high_delta=excluded.high_delta,
                    confidence=excluded.confidence,
                    sample_count=excluded.sample_count,
                    history_days=excluded.history_days,
                    method=excluded.method,
                    prediction_source=excluded.prediction_source,
                    actual_value=NULL,
                    actual_delta=NULL,
                    absolute_error=NULL,
                    signed_error=NULL,
                    direction_hit=NULL,
                    evaluated_at=NULL
                """,
                payload,
            )
        return len(payload)

    @staticmethod
    def _parse_recorded_at(value: str | None) -> datetime | None:
        text = str(value or "").strip()
        if not text or len(text) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _looks_like_legacy_live_observation(recorded_at: str | None) -> bool:
        """Recognise live observations written before market_values.source existed.

        Historical fallback rows created by KickTrack use exactly noon UTC, while
        date-only/midnight rows are also not trustworthy as an observed refresh.
        A real app snapshot carries the actual wall-clock time.
        """
        parsed = Storage._parse_recorded_at(recorded_at)
        if parsed is None:
            return False
        clock = parsed.timetz().replace(tzinfo=None)
        return clock not in {time(0, 0), time(12, 0)}

    def _prediction_actual_observation(self, player_id: str, target_date: str) -> dict | None:
        """Return the first trustworthy observation after the target 22:00 refresh.

        A prediction for 15 Aug targets the 15 Aug 22:00 Europe/Berlin refresh.
        If KickTrack is not opened again until the morning of 16 Aug, that morning
        observation still represents the 15 Aug refresh and is therefore valid.
        Pre-refresh observations from 15 Aug must never be used as the outcome.
        """
        target_day = date.fromisoformat(str(target_date)[:10])
        berlin = ZoneInfo("Europe/Berlin")
        refresh_local = datetime.combine(target_day, time(22, 0), tzinfo=berlin)
        next_refresh_local = datetime.combine(target_day + timedelta(days=1), time(22, 0), tzinfo=berlin)
        refresh_utc = refresh_local.astimezone(UTC)
        next_refresh_utc = next_refresh_local.astimezone(UTC)
        end_day = (target_day + timedelta(days=1)).isoformat()
        rows = self.conn.execute(
            """
            SELECT value, snapshot_date, recorded_at, source
            FROM market_values
            WHERE player_id = ? AND snapshot_date BETWEEN ? AND ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (str(player_id), target_day.isoformat(), end_day),
        ).fetchall()
        candidates = []
        for row in rows:
            observed_at = self._parse_recorded_at(row["recorded_at"])
            if observed_at is None or observed_at < refresh_utc or observed_at >= next_refresh_utc:
                continue
            source = str(row["source"] or "").lower()
            if source != "live" and not (not source and self._looks_like_legacy_live_observation(row["recorded_at"])):
                continue
            value = int(row["value"] or 0)
            if value <= 0:
                continue
            candidates.append({
                "value": value,
                "snapshot_date": str(row["snapshot_date"] or ""),
                "recorded_at": str(row["recorded_at"] or ""),
                "source": source or "legacy-live",
                "observed_at": observed_at,
            })
        return min(candidates, key=lambda item: item["observed_at"]) if candidates else None

    def evaluate_mv_predictions(self, league_id: str, *, through_date: str | date) -> int:
        """Evaluate forecasts only against an observation made after 22:00.

        Older KickTrack builds matched solely on ``snapshot_date``.  A value read
        before 22:00 could therefore be mistaken for that night's completed
        refresh.  We deliberately re-audit *all* eligible rows here so existing
        bad evaluations are repaired (or cleared if no trustworthy outcome was
        captured).
        """
        if isinstance(through_date, date):
            through = through_date.isoformat()
        else:
            through = str(through_date)[:10]
            date.fromisoformat(through)
        rows = self.conn.execute(
            """
            SELECT league_id, player_id, target_date, baseline_value, predicted_delta
            FROM mv_predictions
            WHERE league_id = ? AND target_date <= ?
            ORDER BY target_date ASC
            """,
            (str(league_id), through),
        ).fetchall()
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        updates = []
        clears = []
        for row in rows:
            actual = self._prediction_actual_observation(str(row["player_id"]), str(row["target_date"]))
            key = (str(row["league_id"]), str(row["player_id"]), str(row["target_date"]))
            if not actual:
                clears.append(key)
                continue
            actual_value = int(actual["value"] or 0)
            baseline = int(row["baseline_value"] or 0)
            predicted_delta = int(row["predicted_delta"] or 0)
            if actual_value <= 0 or baseline <= 0:
                clears.append(key)
                continue
            actual_delta = actual_value - baseline
            signed_error = predicted_delta - actual_delta
            absolute_error = abs(signed_error)
            pred_sign = 1 if predicted_delta > 0 else (-1 if predicted_delta < 0 else 0)
            actual_sign = 1 if actual_delta > 0 else (-1 if actual_delta < 0 else 0)
            direction_hit = 1 if pred_sign == actual_sign else 0
            updates.append((
                actual_value, actual_delta, absolute_error, signed_error, direction_hit, now,
                actual["snapshot_date"], actual["recorded_at"], actual["source"], *key,
            ))
        with self.conn:
            if clears:
                self.conn.executemany(
                    """
                    UPDATE mv_predictions
                    SET actual_value=NULL, actual_delta=NULL, absolute_error=NULL, signed_error=NULL,
                        direction_hit=NULL, evaluated_at=NULL, actual_snapshot_date=NULL,
                        actual_recorded_at=NULL, evaluation_source=NULL
                    WHERE league_id=? AND player_id=? AND target_date=?
                    """,
                    clears,
                )
            if updates:
                self.conn.executemany(
                    """
                    UPDATE mv_predictions
                    SET actual_value=?, actual_delta=?, absolute_error=?, signed_error=?,
                        direction_hit=?, evaluated_at=?, actual_snapshot_date=?, actual_recorded_at=?,
                        evaluation_source=?
                    WHERE league_id=? AND player_id=? AND target_date=?
                    """,
                    updates,
                )
        return len(updates)

    def mv_prediction_summary(self, league_id: str, *, limit_days: int = 30) -> dict:
        """Return transparent quality metrics for evaluated 22:00 forecasts."""
        cutoff = (date.today() - timedelta(days=max(1, int(limit_days)))).isoformat()
        rows = self.conn.execute(
            """
            SELECT predicted_delta, actual_delta, absolute_error, signed_error,
                   direction_hit, confidence, target_date
            FROM mv_predictions
            WHERE league_id = ?
              AND evaluated_at IS NOT NULL
              AND baseline_delta IS NOT NULL
              AND target_date >= ?
            ORDER BY target_date DESC
            """,
            (str(league_id), cutoff),
        ).fetchall()
        if not rows:
            return {
                "evaluated": 0, "direction_hits": 0, "direction_hit_rate": None,
                "mae": None, "median_abs_error": None, "bias": None,
                "within_100k_rate": None, "high_confidence_hit_rate": None,
            }
        errors = sorted(int(row["absolute_error"] or 0) for row in rows)
        n = len(errors)
        median_error = errors[n // 2] if n % 2 else int(round((errors[n // 2 - 1] + errors[n // 2]) / 2))
        hits = sum(int(row["direction_hit"] or 0) for row in rows)
        within = sum(1 for error in errors if error <= 100_000)
        signed = [int(row["signed_error"] or 0) for row in rows]
        high = [row for row in rows if str(row["confidence"] or "").upper() == "HOCH"]
        high_hits = sum(int(row["direction_hit"] or 0) for row in high)
        return {
            "evaluated": n,
            "direction_hits": hits,
            "direction_hit_rate": hits / n * 100.0,
            "mae": sum(errors) / n,
            "median_abs_error": median_error,
            "bias": sum(signed) / n,
            "within_100k_rate": within / n * 100.0,
            "high_confidence_hit_rate": (high_hits / len(high) * 100.0) if high else None,
            "high_confidence_count": len(high),
        }

    def mv_prediction_rows(self, league_id: str, *, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM mv_predictions
            WHERE league_id = ?
            ORDER BY target_date DESC, predicted_at DESC
            LIMIT ?
            """,
            (str(league_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def mv_predictions_for_target(self, league_id: str, target_date: str | date) -> dict[str, dict]:
        """Return already stored forecasts for one refresh day keyed by player id."""
        target = target_date.isoformat() if isinstance(target_date, date) else str(target_date)[:10]
        rows = self.conn.execute(
            """
            SELECT * FROM mv_predictions
            WHERE league_id = ? AND target_date = ?
            ORDER BY predicted_at DESC
            """,
            (str(league_id), target),
        ).fetchall()
        return {str(row["player_id"]): dict(row) for row in rows}

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

    def set_watchlisted(self, league_id: str, player_id: str, enabled: bool) -> None:
        league_id = str(league_id or "").strip()
        player_id = str(player_id or "").strip()
        if not league_id or not player_id:
            return
        if enabled:
            self.conn.execute(
                "INSERT OR REPLACE INTO watchlist(league_id, player_id, added_at) VALUES(?, ?, ?)",
                (league_id, player_id, datetime.now(UTC).replace(microsecond=0).isoformat()),
            )
        else:
            self.conn.execute(
                "DELETE FROM watchlist WHERE league_id = ? AND player_id = ?",
                (league_id, player_id),
            )
        self.conn.commit()

    def is_watchlisted(self, league_id: str, player_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM watchlist WHERE league_id = ? AND player_id = ? LIMIT 1",
            (str(league_id or ""), str(player_id or "")),
        ).fetchone()
        return row is not None

    def watchlist_ids(self, league_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT player_id FROM watchlist WHERE league_id = ? ORDER BY added_at DESC",
            (str(league_id or ""),),
        ).fetchall()
        return {str(row["player_id"]) for row in rows}

    def watchlist_rows(self, league_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT w.league_id, w.player_id, w.added_at,
                   pm.name, pm.full_name, pm.club, pm.team_id, pm.position,
                   pm.market_value, pm.points_total, pm.average_points, pm.active_state
            FROM watchlist w
            LEFT JOIN player_master pm ON pm.player_id = w.player_id
            WHERE w.league_id = ?
            ORDER BY w.added_at DESC
            """,
            (str(league_id or ""),),
        ).fetchall()
        return [dict(row) for row in rows]

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
    # Competition player master / portraits
    # ------------------------------------------------------------------

    def portrait_cache_dir(self) -> Path:
        path = self.db_path.parent / "player_portraits"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sync_player_master(self, players: list[dict], *, missing_threshold: int = 3) -> dict:
        """Merge a complete Kickbase competition player snapshot.

        Missing players are not deleted. They first become UNKNOWN and only
        become LEFT_LEAGUE after several complete snapshots, which protects us
        from a transient/incomplete API response.
        """
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        incoming = {str(row.get("player_id")): row for row in players or [] if row.get("player_id") is not None}
        if not incoming:
            return {"seen": 0, "new": 0, "active": 0, "unknown": 0, "left": 0}

        existing = {
            str(row["player_id"]): dict(row)
            for row in self.conn.execute("SELECT * FROM player_master").fetchall()
        }
        new_count = 0

        with self.conn:
            for player_id, row in incoming.items():
                old = existing.get(player_id)
                if old is None:
                    new_count += 1
                name = str(row.get("name") or row.get("full_name") or f"Spieler {player_id}")
                full_name = str(row.get("full_name") or name)
                self.conn.execute(
                    """
                    INSERT INTO player_master(
                        player_id, name, full_name, club, team_id, position,
                        active_state, miss_count, first_seen_at, last_seen_at, last_sync_at,
                        market_value, points_total, average_points, portrait_state
                    )
                    VALUES(?, ?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?, ?, ?, ?, ?, 'MISSING')
                    ON CONFLICT(player_id) DO UPDATE SET
                        name = excluded.name,
                        full_name = excluded.full_name,
                        club = excluded.club,
                        team_id = excluded.team_id,
                        position = excluded.position,
                        active_state = 'ACTIVE',
                        miss_count = 0,
                        last_seen_at = excluded.last_seen_at,
                        last_sync_at = excluded.last_sync_at,
                        market_value = excluded.market_value,
                        points_total = excluded.points_total,
                        average_points = excluded.average_points
                    """,
                    (
                        player_id, name, full_name, row.get("club"), row.get("team_id"),
                        normalize_position(row.get("position")), now, now, now,
                        row.get("market_value"), row.get("points_total"), row.get("average_points"),
                    ),
                )

                # A release build may ship already-cached portraits in
                # assets/portraits. Adopt them automatically without
                # overwriting a newer local cached portrait.
                bundled = bundled_portrait_path(player_id)
                if bundled is not None:
                    current_portrait = self.conn.execute(
                        "SELECT portrait_state, portrait_path FROM player_master WHERE player_id = ?",
                        (player_id,),
                    ).fetchone()
                    local_cached = False
                    if current_portrait and current_portrait["portrait_state"] == "CACHED" and current_portrait["portrait_path"]:
                        try:
                            local_cached = Path(str(current_portrait["portrait_path"])).exists()
                        except OSError:
                            local_cached = False
                    if not local_cached:
                        self.conn.execute(
                            "UPDATE player_master SET portrait_state = 'CACHED', portrait_path = ? WHERE player_id = ?",
                            (str(bundled), player_id),
                        )

            missing_ids = [player_id for player_id in existing if player_id not in incoming]
            for player_id in missing_ids:
                old = existing[player_id]
                misses = int(old.get("miss_count") or 0) + 1
                state = "LEFT_LEAGUE" if misses >= max(1, int(missing_threshold)) else "UNKNOWN"
                self.conn.execute(
                    "UPDATE player_master SET active_state = ?, miss_count = ?, last_sync_at = ? WHERE player_id = ?",
                    (state, misses, now, player_id),
                )

        counts = self.player_master_stats()
        return {
            "seen": len(incoming),
            "new": new_count,
            "new_ids": [player_id for player_id in incoming if player_id not in existing],
            "active": counts.get("active", 0),
            "unknown": counts.get("unknown", 0),
            "left": counts.get("left", 0),
        }

    def player_master_rows(self, *, state: str | None = None) -> list[dict]:
        if state:
            rows = self.conn.execute(
                "SELECT * FROM player_master WHERE active_state = ? ORDER BY club COLLATE NOCASE, full_name COLLATE NOCASE",
                (state,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM player_master ORDER BY active_state, club COLLATE NOCASE, full_name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def player_master_row(self, player_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM player_master WHERE player_id = ?", (str(player_id),)
        ).fetchone()
        return dict(row) if row else None

    def enrich_player_master_identity(self, player_id: str, details: dict) -> dict | None:
        """Persist richer Kickbase player-detail identity data without touching portrait state."""
        player_id = str(player_id)
        current = self.player_master_row(player_id)
        if not current or not isinstance(details, dict):
            return current

        name = str(details.get("name") or current.get("name") or "").strip()
        full_name = str(details.get("full_name") or name or current.get("full_name") or "").strip()
        club = str(details.get("club") or current.get("club") or "").strip()
        position = normalize_position(details.get("position") or current.get("position"))
        market_value = details.get("market_value")
        points_total = details.get("points_total")
        average_points = details.get("average_points")

        with self.conn:
            self.conn.execute(
                """
                UPDATE player_master
                SET name = ?,
                    full_name = ?,
                    club = ?,
                    team_id = COALESCE(?, team_id),
                    position = ?,
                    market_value = COALESCE(?, market_value),
                    points_total = COALESCE(?, points_total),
                    average_points = COALESCE(?, average_points)
                WHERE player_id = ?
                """,
                (
                    name or current.get("name"),
                    full_name or current.get("full_name"),
                    club or current.get("club"),
                    details.get("team_id"),
                    position or current.get("position"),
                    market_value,
                    points_total,
                    average_points,
                    player_id,
                ),
            )
        return self.player_master_row(player_id)

    def player_master_stats(self) -> dict:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN active_state = 'ACTIVE' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN active_state = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown,
                SUM(CASE WHEN active_state = 'LEFT_LEAGUE' THEN 1 ELSE 0 END) AS left,
                SUM(CASE WHEN portrait_state = 'CACHED' THEN 1 ELSE 0 END) AS cached,
                SUM(CASE WHEN portrait_state = 'MISSING' THEN 1 ELSE 0 END) AS missing,
                SUM(CASE WHEN portrait_state = 'NEEDS_REVIEW' THEN 1 ELSE 0 END) AS review,
                SUM(CASE WHEN portrait_state = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN portrait_state = 'REJECTED' THEN 1 ELSE 0 END) AS rejected
            FROM player_master
            """
        ).fetchone()
        if not row:
            return {"total": 0, "active": 0, "unknown": 0, "left": 0, "cached": 0, "missing": 0, "review": 0, "failed": 0, "rejected": 0}
        return {key: int(row[key] or 0) for key in row.keys()}

    def players_needing_portrait(
        self, *, limit: int | None = None, retry_failed: bool = False, player_ids: list[str] | None = None
    ) -> list[dict]:
        # NEEDS_REVIEW is included deliberately: resolver/scoring updates can
        # automatically recover previously conservative matches without users
        # having to delete the DB or reset portrait states manually.
        states = ["MISSING", "NEEDS_REVIEW"]
        if retry_failed:
            states.append("FAILED")
        placeholders = ",".join("?" for _ in states)
        sql = f"""
            SELECT * FROM player_master
            WHERE active_state = 'ACTIVE' AND portrait_state IN ({placeholders})
        """
        params: list[object] = list(states)
        if player_ids:
            ids = [str(value) for value in player_ids if value is not None]
            if ids:
                sql += " AND player_id IN (" + ",".join("?" for _ in ids) + ")"
                params.extend(ids)
        sql += " ORDER BY market_value DESC, full_name COLLATE NOCASE"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def save_portrait_match(self, match) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        self.conn.execute(
            """
            UPDATE player_master
            SET fotmob_id = COALESCE(?, fotmob_id),
                portrait_url = COALESCE(?, portrait_url),
                portrait_path = COALESCE(?, portrait_path),
                portrait_state = ?,
                portrait_confidence = ?,
                portrait_reason = ?,
                portrait_candidate_name = COALESCE(?, portrait_candidate_name),
                portrait_candidate_team = COALESCE(?, portrait_candidate_team),
                portrait_candidate_position = COALESCE(?, portrait_candidate_position),
                portrait_candidate_shirt_number = COALESCE(?, portrait_candidate_shirt_number),
                portrait_checked_at = ?
            WHERE player_id = ?
            """,
            (
                getattr(match, "fotmob_id", None),
                getattr(match, "portrait_url", None),
                getattr(match, "portrait_path", None),
                getattr(match, "state", "FAILED"),
                int(getattr(match, "confidence", 0) or 0),
                getattr(match, "reason", ""),
                getattr(match, "candidate_name", None),
                getattr(match, "candidate_team", None),
                getattr(match, "candidate_position", None),
                getattr(match, "candidate_shirt_number", None),
                now,
                str(getattr(match, "kickbase_player_id", "")),
            ),
        )
        self.conn.commit()

    def portrait_review_rows(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM player_master
            WHERE active_state = 'ACTIVE' AND portrait_state = 'NEEDS_REVIEW'
            ORDER BY portrait_confidence DESC, market_value DESC, full_name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def reject_portrait_candidate(self, player_id: str) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        self.conn.execute(
            """
            UPDATE player_master
            SET portrait_state = 'REJECTED', portrait_checked_at = ?,
                portrait_reason = CASE
                    WHEN portrait_reason IS NULL OR portrait_reason = '' THEN 'Manuell abgelehnt'
                    ELSE portrait_reason || ' · manuell abgelehnt'
                END
            WHERE player_id = ?
            """,
            (now, str(player_id)),
        )
        self.conn.commit()

    def reset_rejected_portraits(self) -> int:
        cur = self.conn.execute(
            """
            UPDATE player_master
            SET portrait_state = 'MISSING', portrait_checked_at = NULL
            WHERE active_state = 'ACTIVE' AND portrait_state = 'REJECTED'
            """
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def portrait_path(self, player_id: str) -> str | None:
        """Resolve a portrait, preferring a writable local cache over bundled assets."""
        pid = str(player_id)
        row = self.conn.execute(
            "SELECT portrait_path, portrait_state FROM player_master WHERE player_id = ?",
            (pid,),
        ).fetchone()
        if row and row["portrait_state"] == "CACHED" and row["portrait_path"]:
            path = Path(str(row["portrait_path"]))
            if path.exists():
                return str(path)

        bundled = bundled_portrait_path(pid)
        return str(bundled) if bundled is not None else None

    # ------------------------------------------------------------------
    # Market value snapshots / analytics
    # ------------------------------------------------------------------

    def snapshot_market_value(self, player_id: str, value: int) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        # The refresh schedule is defined in German local time.  Using UTC's
        # calendar date here can shift observations between days around midnight.
        snapshot_date = now.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()
        recorded_at = now.isoformat()
        self.conn.execute(
            """
            INSERT INTO market_values(player_id, value, snapshot_date, recorded_at, source)
            VALUES(?, ?, ?, ?, 'live')
            ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                value = excluded.value,
                recorded_at = excluded.recorded_at,
                source = excluded.source
            """,
            (player_id, int(value), snapshot_date, recorded_at),
        )
        self.conn.commit()


    def upsert_market_value_history(self, player_id: str, rows: list[dict]) -> int:
        """Persist exact remote MV history and backfill missing calendar days.

        Historical rows are treated as authoritative for past days, but never
        replace a newer observation from the same day. This is important when a
        normal live sync has already stored today's current market value.

        Returns the number of inserted/updated historical day rows.
        """
        payload = []
        now = datetime.now(UTC).replace(microsecond=0)

        for row in rows or []:
            try:
                value = int(row.get("value") or 0)
                snapshot_date = str(row.get("snapshot_date") or "")[:10]
                parsed_day = date.fromisoformat(snapshot_date)
            except (TypeError, ValueError):
                continue

            # The history endpoint can expose a row for the current calendar
            # day before the 22:00 refresh. That row still represents the last
            # completed refresh and would duplicate yesterday's value. Keep
            # today's value exclusively from a real live observation.
            if value <= 0 or parsed_day >= now.date():
                continue

            raw_recorded_at = str(row.get("recorded_at") or "").strip()
            if raw_recorded_at:
                recorded_at = raw_recorded_at
            else:
                # Noon UTC is intentional: it clearly marks this as a historical
                # day value instead of pretending it was observed at refresh time.
                recorded_at = f"{snapshot_date}T12:00:00+00:00"

            payload.append((str(player_id), value, snapshot_date, recorded_at))

        if not payload:
            return 0

        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO market_values(player_id, value, snapshot_date, recorded_at, source)
                VALUES(?, ?, ?, ?, 'history')
                ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                    value = excluded.value,
                    recorded_at = excluded.recorded_at,
                    source = excluded.source
                WHERE excluded.recorded_at >= market_values.recorded_at
                   OR market_values.recorded_at IS NULL
                   OR market_values.recorded_at = ''
                """,
                payload,
            )

        return len(payload)

    def missing_market_value_days(
        self,
        player_id: str,
        *,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> list[str]:
        """Return missing calendar days for one player's stored MV timeline.

        By default the range starts at the first stored market-value day and ends
        yesterday. Today is excluded because its value can still change during
        the current Kickbase refresh cycle.
        """
        player_id = str(player_id)

        if start_date is None:
            row = self.conn.execute(
                """
                SELECT MIN(snapshot_date) AS first_day
                FROM market_values
                WHERE player_id = ?
                """,
                (player_id,),
            ).fetchone()
            if not row or not row["first_day"]:
                return []
            start = date.fromisoformat(str(row["first_day"])[:10])
        elif isinstance(start_date, date):
            start = start_date
        else:
            start = date.fromisoformat(str(start_date)[:10])

        if end_date is None:
            end = date.today() - timedelta(days=1)
        elif isinstance(end_date, date):
            end = end_date
        else:
            end = date.fromisoformat(str(end_date)[:10])

        if end < start:
            return []

        existing = {
            str(row["snapshot_date"])[:10]
            for row in self.conn.execute(
                """
                SELECT snapshot_date
                FROM market_values
                WHERE player_id = ?
                  AND snapshot_date BETWEEN ? AND ?
                """,
                (player_id, start.isoformat(), end.isoformat()),
            ).fetchall()
            if row["snapshot_date"]
        }

        missing = []
        cursor = start
        while cursor <= end:
            day = cursor.isoformat()
            if day not in existing:
                missing.append(day)
            cursor += timedelta(days=1)
        return missing

    def market_value_backfill_status(
        self,
        *,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> dict:
        """Summarize missing MV days across every player known to the database."""
        player_ids = [
            str(row["player_id"])
            for row in self.conn.execute(
                """
                SELECT DISTINCT player_id
                FROM market_values
                ORDER BY player_id
                """
            ).fetchall()
        ]

        missing_by_player: dict[str, list[str]] = {}
        for player_id in player_ids:
            missing = self.missing_market_value_days(
                player_id,
                start_date=start_date,
                end_date=end_date,
            )
            if missing:
                missing_by_player[player_id] = missing

        all_missing_days = sorted({
            day
            for days in missing_by_player.values()
            for day in days
        })

        return {
            "players_checked": len(player_ids),
            "players_with_gaps": len(missing_by_player),
            "missing_days": all_missing_days,
            "missing_by_player": missing_by_player,
        }

    def backfill_market_value_histories(
        self,
        histories: dict[str, list[dict]],
    ) -> dict:
        """Backfill exact historical market values for multiple players at once.

        ``histories`` maps player_id -> normalized history rows. No interpolation
        or estimation is performed. The method simply persists real historical
        values supplied by the Kickbase history endpoint/cache.
        """
        written = 0
        players = 0

        for player_id, rows in (histories or {}).items():
            if not rows:
                continue
            players += 1
            written += self.upsert_market_value_history(str(player_id), rows)

        status = self.market_value_backfill_status()
        return {
            "players_with_history": players,
            "history_rows_processed": written,
            **status,
        }

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
        now_dt = datetime.now(UTC).replace(microsecond=0)
        now = now_dt.isoformat()
        snapshot_date = now_dt.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()

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
                    INSERT INTO market_values(player_id, value, snapshot_date, recorded_at, source)
                    VALUES(?, ?, ?, ?, 'live')
                    ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                        value = excluded.value, recorded_at = excluded.recorded_at, source = 'live'
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

        # Optional automatic history backfill. Sync services can attach a
        # ``market_value_histories`` mapping (player_id -> normalized rows) to
        # the result object. Older SyncResult objects remain fully compatible.
        histories = getattr(result, "market_value_histories", None)
        if histories:
            self.backfill_market_value_histories(histories)

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
        The same sync also writes fresh live market-value observations for these
        players so the 22U model can learn and evaluate beyond the transfer market.
        """
        now_dt = datetime.now(UTC).replace(microsecond=0)
        now = getattr(result, "fetched_at", None) or now_dt.isoformat()
        snapshot_date = now_dt.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()
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
                self.conn.executemany(
                    """
                    INSERT INTO market_values(player_id, value, snapshot_date, recorded_at, source)
                    VALUES(?, ?, ?, ?, 'live')
                    ON CONFLICT(player_id, snapshot_date) DO UPDATE SET
                        value = excluded.value, recorded_at = excluded.recorded_at, source = 'live'
                    """,
                    [
                        (str(player["player_id"]), int(player.get("market_value") or 0), snapshot_date, now)
                        for player in squad.players
                        if int(player.get("market_value") or 0) > 0
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

    def league_prediction_pool(self, league_id: str) -> list[dict]:
        """Return cached players owned by other managers for 22U predictions."""
        rows = self.conn.execute(
            """
            SELECT lmp.*, lm.is_user
            FROM league_manager_players lmp
            LEFT JOIN league_managers lm
              ON lm.league_id = lmp.league_id AND lm.manager_id = lmp.manager_id
            WHERE lmp.league_id = ?
            ORDER BY lmp.updated_at DESC, lmp.market_value DESC
            """,
            (league_id,),
        ).fetchall()
        result = []
        seen: set[str] = set()
        for row in rows:
            pid = str(row["player_id"] or "")
            if not pid or pid in seen or int(row["is_user"] or 0) == 1:
                continue
            seen.add(pid)
            result.append(dict(row))
        return result

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
