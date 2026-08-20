from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.teams import TEAM_NAMES, team_name

from .kickbase_common import KickbaseError
from .kickbase_market import KickbaseMarketMixin
from .kickbase_intelligence import KickbaseIntelligenceMixin
from .kickbase_league import KickbaseLeagueMixin

class KickbaseClient(KickbaseMarketMixin, KickbaseIntelligenceMixin, KickbaseLeagueMixin):
    BASE = "https://api.kickbase.com"
    CDN_BASE = "https://kickbase.b-cdn.net"

    POSITION_MAP = {
        1: "TW",
        2: "ABW",
        3: "MF",
        4: "ST",
        "1": "TW",
        "2": "ABW",
        "3": "MF",
        "4": "ST",
    }

    # Central mapping kept as a class alias for existing parser code/tests.
    TEAM_NAMES = TEAM_NAMES

    def __init__(self) -> None:
        self.client = httpx.Client(
            base_url=self.BASE,
            timeout=20.0,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Accept-Language": "de-DE,de;q=0.9",
            },
        )
        self.token: str | None = None
        # Per-day cache for market 24h changes. The transfer-market endpoint does
        # not reliably include tfhmvt, while the player-detail endpoint does.
        self._daily_change_cache_date: str | None = None
        self._daily_change_cache: dict[tuple[str, str], int | None] = {}

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _items(data: Any) -> list[dict]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []

        for key in ("it", "items", "leagues", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                for nested in ("it", "items"):
                    nested_value = value.get(nested)
                    if isinstance(nested_value, list):
                        return [x for x in nested_value if isinstance(x, dict)]
        return []

    def _get_json(self, path: str, *, params: dict | None = None) -> Any:
        response = self.client.get(path, params=params)
        if response.status_code >= 400:
            raise KickbaseError(
                f"GET {path} fehlgeschlagen (HTTP {response.status_code}).\n"
                f"{response.text[:400]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise KickbaseError(f"Ungültige JSON-Antwort von {path}.") from exc

    def login(self, email: str, password: str) -> dict:
        candidates = ["/v4/user/login", "/v3/user/login", "/user/login"]
        last_error = "keine Antwort"

        for path in candidates:
            try:
                response = self.client.post(
                    path,
                    json={"em": email, "pass": password, "loy": False, "rep": {}},
                )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                    continue

                data = response.json()
                token = (
                    data.get("tkn")
                    or data.get("token")
                    or data.get("accessToken")
                    or data.get("access_token")
                )
                if not token and isinstance(data.get("it"), dict):
                    token = data["it"].get("tkn") or data["it"].get("token")

                if token:
                    self.token = str(token)
                    self.client.headers["Authorization"] = f"Bearer {self.token}"
                    # Some competition/player-profile routes used by the official app
                    # still accept the same auth token through kkstrauth. Keep both
                    # forms so v4 endpoints remain compatible.
                    self.client.headers["Cookie"] = f"kkstrauth={self.token}"
                    return data
            except Exception as exc:  # Login-Fallbacks bewusst tolerant
                last_error = str(exc)

        raise KickbaseError(f"Login fehlgeschlagen ({last_error}).")

    def leagues(self) -> list[dict]:
        paths = [
            "/v4/leagues/selection",
            "/v3/leagues/selection",
            "/v2/leagues/selection",
            "/leagues/selection",
        ]
        data = None
        last_error: Exception | None = None
        for path in paths:
            try:
                data = self._get_json(path)
                break
            except Exception as exc:
                last_error = exc

        if data is None:
            raise KickbaseError(str(last_error or "Liga-Liste konnte nicht geladen werden."))

        result: list[dict] = []
        for item in self._items(data):
            league_id = item.get("id") or item.get("i") or item.get("lid") or item.get("leagueId")
            name = item.get("name") or item.get("n") or item.get("ln") or item.get("leagueName") or "Liga"
            if league_id is not None:
                result.append({"id": str(league_id), "name": str(name)})
        return result

    def league_info(self, league_id: str) -> dict:
        data = self._get_json(f"/v4/leagues/{league_id}/me")
        if not isinstance(data, dict):
            return {}
        return {
            "budget": self._to_int(data.get("b")),
            "league_name": data.get("lnm"),
            "max_players": self._to_int(data.get("mgm")),
            "current_players": self._to_int(data.get("mgc")),
            "raw": data,
        }

    def squad(self, league_id: str) -> list[dict]:
        data = self._get_json(f"/v4/leagues/{league_id}/squad")
        items = data.get("it") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise KickbaseError("Die Kaderantwort enthält keine Spieler-Liste.")

        players: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_squad_player(item)
            if parsed:
                players.append(parsed)

        if not players:
            raise KickbaseError("Kader geladen, aber keine Spieler konnten gelesen werden.")
        return players

    def _parse_squad_player(self, item: dict) -> dict | None:
        player_id = item.get("i")
        name = item.get("n")
        market_value = self._to_int(item.get("mv"))
        if player_id is None or name is None or market_value is None:
            return None

        team_id = str(item.get("tid")) if item.get("tid") is not None else None
        club = self.TEAM_NAMES.get(team_id or "", "")
        if not club and team_id:
            club = f"Team {team_id}"

        position = self.POSITION_MAP.get(item.get("pos"), str(item.get("pos") or ""))

        return {
            "player_id": str(player_id),
            "name": str(name),
            "club": club,
            "team_id": team_id,
            "position": position,
            "market_value": market_value,
            "daily_change": self._to_int(item.get("tfhmvt")),
            "market_gain_loss": self._to_int(item.get("mvgl")),
            "api_long_change": self._to_int(item.get("sdmvt")),
            "team_image": item.get("pim"),
            "status": self._to_int(item.get("st")),
            "status_list": item.get("stl") or [],
            "points_total": self._to_int(item.get("p")),
            "average_points": self._to_int(item.get("ap")),
        }
