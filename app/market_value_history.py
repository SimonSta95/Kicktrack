from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Iterable

from .league_learning import normalize_market_value_history


@dataclass(frozen=True)
class HistoryCoverage:
    player_id: str
    rows: int
    first_day: str | None
    last_day: str | None
    fresh: bool
    source: str

    def as_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "rows": self.rows,
            "first_day": self.first_day,
            "last_day": self.last_day,
            "fresh": self.fresh,
            "source": self.source,
        }


class MarketValueHistoryService:
    """Make real Kickbase market-value histories a dependable shared input.

    Prediction code must not silently rely on whichever daily snapshots happen to
    exist locally.  This service first checks persisted history, then a short-lived
    raw API cache, and finally fetches Kickbase's 365-day history endpoint.  Only
    values actually returned by Kickbase are persisted; no interpolation is used.
    """

    CACHE_TTL_SECONDS = 12 * 3600
    MIN_USEFUL_ROWS = 14
    MAX_STALE_DAYS = 2

    def __init__(self, client, storage, league_id: str, *, timeframe: int = 365, max_workers: int = 6) -> None:
        self.client = client
        self.storage = storage
        self.league_id = str(league_id)
        self.timeframe = max(30, int(timeframe or 365))
        self.max_workers = max(1, min(8, int(max_workers or 6)))

    @staticmethod
    def _coverage(player_id: str, rows: list[dict], source: str) -> HistoryCoverage:
        valid = [row for row in rows or [] if row.get("snapshot_date") and row.get("value")]
        valid.sort(key=lambda row: str(row.get("snapshot_date")))
        first_day = str(valid[0]["snapshot_date"])[:10] if valid else None
        last_day = str(valid[-1]["snapshot_date"])[:10] if valid else None
        fresh = False
        if last_day and len(valid) >= MarketValueHistoryService.MIN_USEFUL_ROWS:
            try:
                latest = date.fromisoformat(last_day)
                # History rows intentionally stop before today's live observation.
                expected = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=1)
                fresh = (expected - latest).days <= MarketValueHistoryService.MAX_STALE_DAYS
            except ValueError:
                fresh = False
        return HistoryCoverage(str(player_id), len(valid), first_day, last_day, fresh, source)

    def _stored(self, player_id: str) -> tuple[list[dict], HistoryCoverage]:
        rows = self.storage.all_history(str(player_id))
        coverage = self._coverage(str(player_id), rows, "LOCAL")
        return rows, coverage

    def _cache_keys(self, player_id: str) -> tuple[str, ...]:
        # The legacy scanner key remains readable so existing installations do not
        # throw away already downloaded 365-day histories after the refactor.
        return (
            f"mv_history:{self.timeframe}:{player_id}",
            f"mv_scanner:365:{player_id}" if self.timeframe == 365 else "",
            f"league_learning:mv365:{self.league_id}:{player_id}" if self.timeframe == 365 else "",
        )

    def _cached(self, player_id: str) -> list[dict]:
        for key in self._cache_keys(player_id):
            if not key:
                continue
            payload = self.storage.cache_get(key, self.CACHE_TTL_SECONDS)
            if payload is None:
                continue
            rows = normalize_market_value_history(payload)
            if rows:
                return rows
        return []

    def _persist_payload(self, player_id: str, payload) -> list[dict]:
        rows = normalize_market_value_history(payload)
        if not rows:
            return []
        self.storage.upsert_market_value_history(str(player_id), rows)
        self.storage.cache_set(f"mv_history:{self.timeframe}:{player_id}", payload)
        # Preserve compatibility with the scanner and older league-learning cache.
        if self.timeframe == 365:
            self.storage.cache_set(f"mv_scanner:365:{player_id}", payload)
            self.storage.cache_set(f"league_learning:mv365:{self.league_id}:{player_id}", payload)
        return rows

    def ensure_one(self, player_id: str, *, force: bool = False) -> tuple[list[dict], HistoryCoverage]:
        player_id = str(player_id)
        stored, coverage = self._stored(player_id)
        if stored and coverage.fresh and not force:
            return stored, coverage

        if not force:
            cached = self._cached(player_id)
            if cached:
                self.storage.upsert_market_value_history(player_id, cached)
                merged, merged_cov = self._stored(player_id)
                if merged_cov.fresh:
                    return merged, HistoryCoverage(
                        player_id, merged_cov.rows, merged_cov.first_day, merged_cov.last_day, True, "CACHE"
                    )

        payload = self.client.market_value_history(self.league_id, player_id, self.timeframe)
        self._persist_payload(player_id, payload)
        merged, merged_cov = self._stored(player_id)
        return merged, HistoryCoverage(
            player_id,
            merged_cov.rows,
            merged_cov.first_day,
            merged_cov.last_day,
            merged_cov.fresh,
            "API",
        )

    def ensure_many(self, player_ids: Iterable[str], *, force: bool = False) -> dict:
        unique = list(dict.fromkeys(str(pid) for pid in player_ids if str(pid or "").strip()))
        histories: dict[str, list[dict]] = {}
        coverage: dict[str, dict] = {}
        needs_fetch: list[str] = []

        for player_id in unique:
            stored, cov = self._stored(player_id)
            if stored and cov.fresh and not force:
                histories[player_id] = stored
                coverage[player_id] = cov.as_dict()
                continue

            if not force:
                cached = self._cached(player_id)
                if cached:
                    self.storage.upsert_market_value_history(player_id, cached)
                    stored, cov = self._stored(player_id)
                    if cov.fresh:
                        histories[player_id] = stored
                        coverage[player_id] = HistoryCoverage(
                            player_id, cov.rows, cov.first_day, cov.last_day, True, "CACHE"
                        ).as_dict()
                        continue
            needs_fetch.append(player_id)

        if needs_fetch:
            workers = min(self.max_workers, len(needs_fetch))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self.client.market_value_history, self.league_id, pid, self.timeframe): pid
                    for pid in needs_fetch
                }
                for future in as_completed(futures):
                    pid = futures[future]
                    try:
                        payload = future.result()
                        self._persist_payload(pid, payload)
                    except Exception:
                        # Keep whatever verified local history exists. Reliability
                        # means degrading explicitly, not fabricating missing days.
                        pass
                    rows, cov = self._stored(pid)
                    histories[pid] = rows
                    coverage[pid] = cov.as_dict()

        fresh_count = sum(1 for item in coverage.values() if item.get("fresh"))
        useful_count = sum(1 for item in coverage.values() if int(item.get("rows") or 0) >= self.MIN_USEFUL_ROWS)
        return {
            "histories": histories,
            "coverage": coverage,
            "players": len(unique),
            "fresh_players": fresh_count,
            "useful_players": useful_count,
            "fetched_players": len(needs_fetch),
        }
