from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.teams import TEAM_NAMES, team_name

from .kickbase_common import KickbaseError

class KickbaseIntelligenceMixin:
    def market_overview(
        self,
        league_id: str,
        manager_id: str | None = None,
        owned_player_ids: set[str] | None = None,
    ) -> dict:
        """Return the complete current market plus budget context for analysis."""
        overview = self.budget_overview(league_id, manager_id, owned_player_ids)
        manager_id = str(manager_id) if manager_id else None
        market_raw = overview.get("market_raw")
        points_are_current = True
        if isinstance(market_raw, dict) and market_raw.get("dt"):
            try:
                season_start_dt = datetime.fromisoformat(str(market_raw.get("dt")).replace("Z", "+00:00"))
                points_are_current = datetime.now(season_start_dt.tzinfo) >= season_start_dt
            except (TypeError, ValueError):
                points_are_current = True
        entries: list[dict] = []
        for item in self._market_items(market_raw):
            player_id = item.get("pi") or item.get("i") or item.get("id")
            first = str(item.get("fn") or item.get("firstName") or "").strip()
            short = str(item.get("pn") or item.get("n") or item.get("lastName") or item.get("name") or "").strip()
            full_name = " ".join(part for part in (first, short) if part).strip() or short or "Unbekannter Spieler"
            team_id = item.get("tid") or item.get("teamId") or item.get("ti")
            seller = item.get("u") or item.get("ui") or item.get("seller")
            seller_name = "Kickbase"
            seller_id = None
            if isinstance(seller, dict):
                seller_id = seller.get("i") or seller.get("id") or seller.get("u")
                seller_name = str(seller.get("n") or seller.get("name") or seller.get("unm") or "Manager")
            elif seller is not None:
                seller_id = seller
            own_bid = None
            direct_user = item.get("uoid")
            direct_price = self._first_int(item, ("uop",))
            if manager_id and direct_user is not None and str(direct_user) == manager_id:
                own_bid = direct_price
            if own_bid is None and manager_id:
                for offer in self._offer_items(item):
                    offer_user = offer.get("uoid") or offer.get("u") or offer.get("ui") or offer.get("userId")
                    if isinstance(offer_user, dict):
                        offer_user = offer_user.get("i") or offer_user.get("id") or offer_user.get("u")
                    if offer_user is not None and str(offer_user) != manager_id:
                        continue
                    price = self._first_int(offer, ("uop", "prc", "price", "p", "amount", "bid"))
                    if price and price > 0:
                        own_bid = max(int(own_bid or 0), int(price))
            expires_in = self._first_int(item, ("exs", "expiresIn", "expires_in"))
            expires_at = None
            if seller is None and expires_in is not None and expires_in >= 0:
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()

            entries.append({
                "player_id": str(player_id) if player_id is not None else None,
                "name": full_name,
                "full_name": full_name,
                "team_id": str(team_id) if team_id is not None else None,
                "club": team_name(team_id) if team_id is not None else "",
                "position": self.POSITION_MAP.get(item.get("pos"), str(item.get("pos") or "")),
                "market_value": self._first_int(item, ("mv", "marketValue")),
                # Kickbase exposes the latest 24h market-value movement directly
                # on market entries as `tfhmvt`. Keep that exact value separate
                # from longer locally reconstructed history windows.
                "daily_change": self._first_int(item, ("tfhmvt", "dailyChange")),
                "d1": self._first_int(item, ("tfhmvt", "dailyChange")),
                "price": self._first_int(item, ("prc", "price")),
                "market_trend": self._first_int(item, ("mvt", "marketValueTrend")),
                # Only Kickbase's canonical availability fields are valid here.
                # Never fall back to a generic field named `status`: other v4
                # endpoints use that name for a different enum (values like 3/5).
                "status": self._first_int(item, ("st",)),
                "status_list": item.get("stl") or [],
                "points_total": self._first_int(item, ("p", "points")) if points_are_current else None,
                "average_points": self._first_int(item, ("ap", "averagePoints")) if points_are_current else None,
                "seller_id": str(seller_id) if seller_id is not None else None,
                "seller_name": seller_name,
                "is_kickbase": seller is None,
                "offer_count": self._first_int(item, ("ofc", "offerCount")) or 0,
                "own_bid": own_bid,
                "is_new": bool(item.get("isn") or item.get("isNew")),
                "expires_in": expires_in if seller is None else None,
                "expires_at": expires_at,
                "listed_at": item.get("dt"),
                "team_image": item.get("pim"),
                "raw": item,
            })
        # Keep the normal market load lightweight. Some market payloads omit
        # ``tfhmvt``; do NOT fan out into one player-detail request per missing
        # value here. Missing 24h values remain ``None`` and can be filled by
        # explicit/expensive scanner workflows instead.

        overview["market_entries"] = entries
        overview["points_are_current"] = points_are_current
        return overview

    def market_daily_changes(self, league_id: str, player_ids: list[str]) -> dict[str, int | None]:
        """Return exact Kickbase 24h MW changes for market players.

        The market endpoint does not reliably expose ``tfhmvt``. Fetch the
        canonical player detail only for missing values and cache the result for
        the current local day. A small worker pool avoids making the market load
        painfully slow without hammering the API.
        """
        today = datetime.now().date().isoformat()
        if self._daily_change_cache_date != today:
            self._daily_change_cache_date = today
            self._daily_change_cache.clear()

        normalized = [str(pid) for pid in player_ids if pid]
        missing = [pid for pid in normalized if (str(league_id), pid) not in self._daily_change_cache]

        def fetch(pid: str) -> tuple[str, int | None]:
            try:
                data = self._get_json(f"/v4/leagues/{league_id}/players/{pid}")
                value = self._to_int(data.get("tfhmvt")) if isinstance(data, dict) else None
                return pid, value
            except Exception:
                return pid, None

        # Four parallel requests are enough to keep the initial load responsive
        # while staying deliberately conservative with the unofficial API.
        if missing:
            with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
                futures = [pool.submit(fetch, pid) for pid in missing]
                for future in as_completed(futures):
                    pid, value = future.result()
                    self._daily_change_cache[(str(league_id), pid)] = value

        return {pid: self._daily_change_cache.get((str(league_id), pid)) for pid in normalized}

    def player_performance(self, league_id: str, player_id: str) -> dict:
        data = self._get_json(f"/v4/leagues/{league_id}/players/{player_id}/performance")
        return data if isinstance(data, dict) else {}

    def player_match_center(
        self,
        league_id: str,
        player_id: str,
        match_id: str,
        competition_id: str | int = 1,
    ) -> dict:
        data = self._get_json(
            f"/v4/competitions/{competition_id}/playercenter/{player_id}",
            params={"leagueId": str(league_id), "matchId": str(match_id)},
        )
        return data if isinstance(data, dict) else {}

    def live_event_types(self) -> dict | list:
        data = self._get_json("/v4/live/eventtypes")
        return data if isinstance(data, (dict, list)) else {}

    def competition_fixtures(self, competition_id: str | int = 1) -> dict:
        data = self._get_json(f"/v4/competitions/{competition_id}/matchdays")
        return data if isinstance(data, dict) else {}

    def competition_table(self, competition_id: str | int = 1) -> dict:
        data = self._get_json(f"/v4/competitions/{competition_id}/table")
        return data if isinstance(data, dict) else {}

    def manager_performance(self, league_id: str, manager_id: str) -> dict:
        data = self._get_json(f"/v4/leagues/{league_id}/managers/{manager_id}/performance")
        return data if isinstance(data, dict) else {}

    def my_lineup(self, league_id: str) -> dict:
        data = self._get_json(f"/v4/leagues/{league_id}/lineup")
        return data if isinstance(data, dict) else {}

    def activity_feed(self, league_id: str, start: int = 0, maximum: int = 50) -> dict:
        data = self._get_json(
            f"/v4/leagues/{league_id}/activitiesFeed",
            params={"start": max(0, int(start)), "max": max(1, min(100, int(maximum)))},
        )
        return data if isinstance(data, dict) else {}
