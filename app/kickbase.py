from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.teams import TEAM_NAMES, team_name


class KickbaseError(RuntimeError):
    pass


class KickbaseClient:
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Auth / leagues
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Squad
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Budget / transfer market
    # ------------------------------------------------------------------

    @staticmethod
    def _first_int(data: Any, keys: tuple[str, ...]) -> int | None:
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data:
                value = KickbaseClient._to_int(data.get(key))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _market_items(data: Any) -> list[dict]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("players", "it", "items", "market"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested in ("players", "it", "items"):
                    nested_value = value.get(nested)
                    if isinstance(nested_value, list):
                        return [item for item in nested_value if isinstance(item, dict)]
        return []

    @staticmethod
    def _market_player_name(item: dict) -> str:
        direct = item.get("pn") or item.get("n") or item.get("name")
        if direct:
            return str(direct)
        first = str(item.get("firstName") or item.get("fn") or "").strip()
        last = str(item.get("lastName") or item.get("ln") or "").strip()
        return " ".join(part for part in (first, last) if part) or "Unbekannter Spieler"

    @staticmethod
    def _offer_items(item: dict) -> list[dict]:
        for key in ("offers", "ofr", "ofs", "of", "bids"):
            value = item.get(key)
            if isinstance(value, list):
                return [offer for offer in value if isinstance(offer, dict)]
            if isinstance(value, dict):
                return [value]
        return []

    def budget_overview(
        self,
        league_id: str,
        manager_id: str | None = None,
        owned_player_ids: set[str] | None = None,
    ) -> dict:
        """Return live budget, transfer-list value and active bids.

        Kickbase documents `/me/budget` and `/market`, but compact v4 market
        response fields are only partially documented. The parser is therefore
        deliberately defensive and only treats offers on *other managers'* market
        players as committed bids of the authenticated user.
        """
        budget_raw = self._get_json(f"/v4/leagues/{league_id}/me/budget")
        market_raw = self._get_json(f"/v4/leagues/{league_id}/market")

        balance = None
        if isinstance(budget_raw, dict):
            balance = self._first_int(
                budget_raw,
                ("b", "budget", "bdg", "amount", "balance", "cash", "availableBudget"),
            )
            if balance is None:
                for nested_key in ("data", "me", "budget"):
                    nested = budget_raw.get(nested_key)
                    if isinstance(nested, dict):
                        balance = self._first_int(
                            nested,
                            ("b", "budget", "bdg", "amount", "balance", "cash", "availableBudget"),
                        )
                        if balance is not None:
                            break

        own_listings: list[dict] = []
        active_bids: list[dict] = []
        manager_id = str(manager_id) if manager_id else None
        owned_player_ids = {str(value) for value in (owned_player_ids or set())}

        for item in self._market_items(market_raw):
            player_id = item.get("pi") or item.get("i") or item.get("id")
            seller_value = item.get("ui") or item.get("u") or item.get("userId") or item.get("uid")
            if isinstance(seller_value, dict):
                seller_value = seller_value.get("i") or seller_value.get("id") or seller_value.get("ui") or seller_value.get("u")
            seller_id = str(seller_value) if seller_value is not None else None
            price = self._first_int(item, ("prc", "price", "p"))
            market_value = self._first_int(item, ("mv", "marketValue"))
            first_name = str(item.get("fn") or item.get("firstName") or "").strip()
            short_name = self._market_player_name(item)
            full_name = " ".join(part for part in (first_name, short_name) if part).strip() or short_name
            team_id = item.get("tid") or item.get("teamId") or item.get("ti")
            player = {
                "player_id": str(player_id) if player_id is not None else None,
                "name": short_name,
                "full_name": full_name,
                "team_id": str(team_id) if team_id is not None else None,
                "club": team_name(team_id) if team_id is not None else "",
                "position": self.POSITION_MAP.get(item.get("pos"), str(item.get("pos") or "")),
                "points_total": self._to_int(item.get("p")),
                "average_points": self._to_int(item.get("ap")),
                "seller_id": seller_id,
                "price": price,
                "market_value": market_value,
            }

            is_own_listing = (
                (manager_id is not None and seller_id == manager_id)
                or (player["player_id"] is not None and player["player_id"] in owned_player_ids)
            )
            if is_own_listing:
                # A manager listing cannot be bought below the player's current
                # market value. If an older listing price has fallen below MW,
                # the economically relevant minimum sale value is therefore the
                # current MW. A listing above MW remains the effective minimum.
                listing_price = int(price or 0)
                current_mv = int(market_value or 0)
                effective_sale_value = max(listing_price, current_mv)
                player["listing_price"] = listing_price
                player["minimum_bid"] = current_mv if current_mv > 0 else listing_price
                player["effective_sale_value"] = effective_sale_value
                own_listings.append(player)
                continue

            parsed_offers: list[dict] = []

            # Current compact v4 market shape: the authenticated user's own offer
            # is exposed directly on the market item as uoid/uop. `ofs` contains
            # the same offer with user metadata. Prefer this explicit pair because
            # it is unambiguous and avoids treating other managers' offers as ours.
            direct_offer_user = item.get("uoid")
            direct_offer_price = self._first_int(item, ("uop",))
            if (
                manager_id
                and direct_offer_user is not None
                and str(direct_offer_user) == manager_id
                and direct_offer_price is not None
                and direct_offer_price > 0
            ):
                parsed_offers.append({"price": direct_offer_price, "raw": item, "source": "uoid/uop"})

            for offer in self._offer_items(item):
                offer_price = self._first_int(offer, ("uop", "prc", "price", "p", "amount", "bid"))
                if offer_price is None or offer_price <= 0:
                    continue
                offer_user = (
                    offer.get("uoid")
                    or offer.get("ui")
                    or offer.get("u")
                    or offer.get("userId")
                    or offer.get("uid")
                )
                if isinstance(offer_user, dict):
                    offer_user = offer_user.get("i") or offer_user.get("id") or offer_user.get("u")
                # If the offer carries an owner, it must be the authenticated user.
                # Legacy verbose fixtures may omit it; keep those for backwards
                # compatibility with older API response shapes.
                if offer_user is not None and manager_id and str(offer_user) != manager_id:
                    continue
                parsed_offers.append({"price": offer_price, "raw": offer, "source": "offers"})

            if parsed_offers:
                # uoid/uop and ofs can describe the same bid. One player can only
                # bind the highest current bid amount once.
                selected = max(parsed_offers, key=lambda entry: entry["price"])
                active_bids.append({**player, "bid": selected["price"]})

        transfer_list_value = sum(
            int(
                entry.get("effective_sale_value")
                or max(int(entry.get("price") or 0), int(entry.get("market_value") or 0))
            )
            for entry in own_listings
        )
        parsed_committed = sum(int(entry["bid"]) for entry in active_bids)

        # `/me/budget` exposes pbaa in the current v4 response. In observed live
        # data it is the cash budget after active auction bids. Use it as an
        # authoritative reconciliation value so the budget remains correct even
        # if a market item ever omits its detailed offer payload.
        budget_after_active_bids = None
        if isinstance(budget_raw, dict):
            budget_after_active_bids = self._first_int(
                budget_raw,
                ("pbaa", "budgetAfterActiveAuctions", "budgetAfterActiveBids"),
            )
        api_committed = None
        if balance is not None and budget_after_active_bids is not None:
            api_committed = max(0, int(balance) - int(budget_after_active_bids))

        committed = api_committed if api_committed is not None else parsed_committed
        total_budget = (balance + transfer_list_value) if balance is not None else None
        rest_without_sales = (
            budget_after_active_bids
            if budget_after_active_bids is not None
            else ((balance - committed) if balance is not None else None)
        )
        rest_budget = (
            rest_without_sales + transfer_list_value
            if rest_without_sales is not None
            else None
        )

        return {
            "balance": balance,
            "transfer_list_value": transfer_list_value,
            "total_budget": total_budget,
            "committed": committed,
            "rest_budget": rest_budget,
            "rest_without_sales": rest_without_sales,
            "active_bids": active_bids,
            "own_listings": own_listings,
            "budget_raw": budget_raw,
            "market_raw": market_raw,
        }


    def place_market_offer(self, league_id: str, player_id: str, price: int) -> dict:
        """Place or replace the authenticated manager's offer for a market player."""
        amount = int(price or 0)
        if amount <= 0:
            raise KickbaseError("Das Gebot muss größer als 0 € sein.")
        path = f"/v4/leagues/{league_id}/market/{player_id}/offers"
        response = self.client.post(path, json={"price": amount})
        if response.status_code >= 400:
            message = response.text[:500].strip()
            raise KickbaseError(
                f"Gebot konnte nicht abgegeben werden (HTTP {response.status_code})."
                + (f"\n{message}" if message else "")
            )
        if not response.content:
            return {"ok": True, "status_code": response.status_code}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {"data": payload}


    @staticmethod
    def _response_payload(response) -> dict:
        if not getattr(response, "content", b""):
            return {"ok": True, "status_code": int(response.status_code)}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {"data": payload}

    @staticmethod
    def _raise_write_error(action: str, response) -> None:
        if response.status_code < 400:
            return
        message = str(getattr(response, "text", "") or "")[:500].strip()
        raise KickbaseError(
            f"{action} fehlgeschlagen (HTTP {response.status_code})."
            + (f"\n{message}" if message else "")
        )

    def set_transfer_price(self, league_id: str, player_id: str, price: int | float) -> dict:
        """Set/update the authenticated manager's listing price.

        Verified against the official Kickbase Android app on 2026-08-18:
        POST /v4/leagues/{leagueId}/market with ``pi`` as a string and ``prc``
        as a JSON floating-point number.
        """
        amount = int(price or 0)
        if amount <= 0:
            raise KickbaseError("Der Verkaufspreis muss größer als 0 € sein.")
        response = self.client.post(
            f"/v4/leagues/{league_id}/market",
            json={"pi": str(player_id), "prc": float(amount)},
        )
        self._raise_write_error("Verkaufspreis setzen", response)
        return self._response_payload(response)

    def list_player_for_sale(self, league_id: str, player_id: str, price: int | float) -> dict:
        """List/update an owned player on the league market with one verified write.

        Verified against the official Kickbase Android app on 2026-08-18:
        ``POST /v4/leagues/{leagueId}/market`` with ``pi`` as a string and
        ``prc`` as a JSON floating-point number. This action only lists the
        player / changes the listing price; it does not accept a sale offer.
        """
        amount = int(price or 0)
        if amount <= 0:
            raise KickbaseError("Der Verkaufspreis muss größer als 0 € sein.")

        response = self.client.post(
            f"/v4/leagues/{league_id}/market",
            json={"pi": str(player_id), "prc": float(amount)},
        )
        self._raise_write_error("Spieler anbieten", response)
        return {
            "ok": True,
            "price_set": True,
            "requested_price": amount,
            "market": self._response_payload(response),
        }

    def remove_player_from_market(self, league_id: str, player_id: str) -> dict:
        response = self.client.delete(f"/v4/leagues/{league_id}/market/{player_id}")
        self._raise_write_error("Spieler vom Markt nehmen", response)
        return self._response_payload(response)

    def player_transfer_state(self, league_id: str, player_id: str) -> dict:
        """Offer loading is intentionally disabled until the official request is captured."""
        raise KickbaseError(
            "Angebote laden ist noch nicht verifiziert. Der Request wird erst nach einem Mitschnitt der offiziellen App freigeschaltet."
        )

    def normalize_incoming_offers(self, payload: dict) -> list[dict]:
        """Keep the parser ready for the verified offer payload once available."""
        offers = payload.get("ofs") if isinstance(payload, dict) else None
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list):
            return []
        result = []
        for raw in offers:
            if not isinstance(raw, dict):
                continue
            offer_id = raw.get("i") or raw.get("id") or raw.get("oi") or raw.get("ofi") or raw.get("offerId")
            price = self._first_int(raw, ("prc", "price", "p", "amount", "bid", "uop"))
            user = raw.get("u") or raw.get("ui") or raw.get("user") or raw.get("userId") or raw.get("uid")
            user_id = None
            user_name = None
            if isinstance(user, dict):
                user_id = user.get("i") or user.get("id") or user.get("u") or user.get("ui")
                user_name = user.get("n") or user.get("name") or user.get("unm")
            elif user is not None:
                user_id = user
            user_id = raw.get("uoid") or raw.get("oui") or user_id
            user_name = raw.get("unm") or raw.get("username") or raw.get("name") or user_name
            is_kickbase = user_id is None and not user_name
            result.append({
                "offer_id": str(offer_id) if offer_id is not None else None,
                "price": int(price or 0),
                "user_id": str(user_id) if user_id is not None else None,
                "user_name": str(user_name) if user_name else ("Kickbase" if is_kickbase else "Manager"),
                "is_kickbase": bool(is_kickbase),
                "raw": raw,
            })
        return sorted(result, key=lambda row: int(row.get("price") or 0), reverse=True)

    def accept_manager_offer(self, league_id: str, player_id: str, offer_id: str) -> dict:
        raise KickbaseError(
            "Angebote annehmen ist noch nicht verifiziert und deshalb aus Sicherheitsgründen deaktiviert."
        )

    def decline_manager_offer(self, league_id: str, player_id: str, offer_id: str) -> dict:
        raise KickbaseError(
            "Angebote ablehnen ist noch nicht verifiziert und deshalb aus Sicherheitsgründen deaktiviert."
        )

    def accept_kickbase_sale_offer(self, league_id: str, player_id: str) -> dict:
        """Accept the current Kickbase-owned sale offer for a listed player.

        Verified against the official Kickbase Android app on 2026-08-20:
        ``POST /v4/leagues/{leagueId}/market/{playerId}/sell`` with no request
        body. This is deliberately kept separate from manager offers, which
        require a specific offer-selection flow that is not yet verified.
        """
        response = self.client.post(
            f"/v4/leagues/{league_id}/market/{player_id}/sell"
        )
        self._raise_write_error("An Kickbase verkaufen", response)
        return self._response_payload(response)


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

    # ------------------------------------------------------------------
    # Intelligence endpoints (read-only)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Transfer endpoints
    # ------------------------------------------------------------------

    def player_transfer_history(self, league_id: str, player_id: str) -> list[dict]:
        data = self._get_json(
            f"/v4/leagues/{league_id}/players/{player_id}/transferHistory"
        )
        return self._items(data)

    def detect_manager_id(self, league_id: str, players: list[dict]) -> str | None:
        """Findet die eigene Manager-ID mit möglichst wenig Requests.

        Bei einem aktuellen Kaderspieler ist der jüngste Transfer-/Startkader-Eintrag
        normalerweise dem aktuellen Besitzer zugeordnet. Ein Spieler reicht daher in
        der Praxis fast immer.
        """
        for player in players[:4]:
            try:
                history = self.player_transfer_history(league_id, player["player_id"])
            except Exception:
                continue
            if not history:
                continue
            history = sorted(history, key=lambda x: x.get("dt") or "")
            for item in reversed(history):
                if item.get("u") is not None:
                    return str(item["u"])
        return None

    def manager_transfers(self, league_id: str, manager_id: str) -> dict:
        """Return manager transfer history with guarded offset pagination.

        Kickbase documents the endpoint as paginated via ``start``. We keep the
        number of pages bounded and stop as soon as a page contains no unseen
        events, so a server ignoring the offset cannot create an endless loop.
        """
        path = f"/v4/leagues/{league_id}/managers/{manager_id}/transfer"
        all_items: list[dict] = []
        seen: set[tuple] = set()
        start = 0
        base: dict = {}

        for _page in range(8):
            data = self._get_json(path, params={"start": start} if start else None)
            if not isinstance(data, dict):
                raise KickbaseError("Ungültige Manager-Transferantwort.")
            if not base:
                base = dict(data)
            items = self._items(data)
            if not items:
                break

            new_count = 0
            for item in items:
                key = (
                    str(item.get("pi") or ""),
                    self._to_int(item.get("tty")),
                    self._to_int(item.get("trp")),
                    str(item.get("dt") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                all_items.append(item)
                new_count += 1

            if new_count == 0:
                break
            start += len(items)
            # Small final pages are normally the end. The extra no-item request
            # is avoided without assuming a fixed Kickbase page size.
            if len(items) < 20:
                break

        base["it"] = all_items
        return base

    def parse_manager_transfers(self, data: dict) -> list[dict]:
        result: list[dict] = []
        for item in self._items(data):
            transfer_type = self._to_int(item.get("tty"))
            if transfer_type not in (1, 2):
                continue
            team_id = str(item.get("tid")) if item.get("tid") is not None else None
            club = self.TEAM_NAMES.get(team_id or "", f"Team {team_id}" if team_id else "–")
            result.append(
                {
                    "player_id": str(item.get("pi")),
                    "player_name": str(item.get("pn") or "Unbekannt"),
                    "team_id": team_id,
                    "club": club,
                    "transfer_type": "BUY" if transfer_type == 1 else "SELL",
                    "price": self._to_int(item.get("trp")) or 0,
                    "transferred_at": item.get("dt") or "",
                    "team_image": item.get("pim"),
                }
            )
        return sorted(result, key=lambda x: x["transferred_at"], reverse=True)

    def acquisition_for_current_player(
        self,
        player: dict,
        manager_transfers: list[dict],
    ) -> dict:
        """Bestimmt den Einstieg eines aktuell gehaltenen Spielers.

        - Letzter eigener Vorgang ist BUY -> Kaufpreis = Einstieg.
        - Kein aktueller Kauf -> Startkader. Dann ist `mv - mvgl` der von
          Kickbase geführte Einstiegswert der Zuteilung.
        """
        player_events = [
            event for event in manager_transfers if event["player_id"] == player["player_id"]
        ]
        player_events.sort(key=lambda x: x["transferred_at"], reverse=True)

        if player_events and player_events[0]["transfer_type"] == "BUY":
            event = player_events[0]
            return {
                "origin": "TRANSFER",
                "entry_value": event["price"],
                "purchase_price": event["price"],
                "purchase_date": event["transferred_at"],
            }

        market_value = self._to_int(player.get("market_value"))
        gain_loss = self._to_int(player.get("market_gain_loss"))
        entry_value = None
        if market_value is not None and gain_loss is not None:
            entry_value = market_value - gain_loss

        return {
            "origin": "STARTKADER",
            "entry_value": entry_value,
            "purchase_price": None,
            "purchase_date": None,
        }

    # ------------------------------------------------------------------
    # League / manager analysis
    # ------------------------------------------------------------------

    def league_managers(self, league_id: str) -> dict:
        """Return the managers participating in a league.

        The v4 settings endpoint is the current source used by Kickbase for the
        manager list. Keep the parser intentionally narrow and return normalized
        field names so the UI never depends on Kickbase's abbreviated keys.
        """
        data = self._get_json(f"/v4/leagues/{league_id}/settings/managers")
        if not isinstance(data, dict):
            raise KickbaseError("Ungültige Manager-Liste.")

        raw_managers = data.get("us")
        if not isinstance(raw_managers, list):
            raw_managers = self._items(data)

        managers: list[dict] = []
        for item in raw_managers:
            if not isinstance(item, dict):
                continue
            manager_id = item.get("i") or item.get("id") or item.get("u")
            if manager_id is None:
                continue
            managers.append(
                {
                    "manager_id": str(manager_id),
                    "name": str(item.get("n") or item.get("unm") or item.get("name") or "Unbekannt"),
                    "profile_image": item.get("uim") or item.get("image"),
                    "is_user": bool(item.get("isu")),
                }
            )

        return {
            "managers": managers,
            "matchday": self._to_int(data.get("day")),
            "raw": data,
        }

    def league_ranking(self, league_id: str) -> dict:
        """Return the current league ranking in normalized form.

        Ranking is the authoritative source for season points/place and exposes
        the current matchday explicitly. Manager dashboards can temporarily
        carry previous-season aggregates during the preseason.
        """
        data = self._get_json(f"/v4/leagues/{league_id}/ranking")
        if not isinstance(data, dict):
            raise KickbaseError("Ungültige Liga-Rangliste.")

        raw_managers = data.get("us")
        if not isinstance(raw_managers, list):
            raw_managers = []

        managers: list[dict] = []
        for item in raw_managers:
            if not isinstance(item, dict):
                continue
            manager_id = item.get("i")
            if manager_id is None:
                continue
            managers.append(
                {
                    "manager_id": str(manager_id),
                    "name": str(item.get("n") or "Unbekannt"),
                    "points": self._to_int(item.get("sp")),
                    "place": self._to_int(item.get("spl")),
                    "team_value": self._to_int(item.get("tv")),
                    "profile_image": item.get("uim"),
                }
            )

        return {
            "managers": managers,
            "matchday": self._to_int(data.get("day")),
            "season": data.get("sn"),
            "raw": data,
        }

    @staticmethod
    def _club_from_payload(item: dict) -> str:
        """Read an explicit club name without guessing from a numeric id."""
        for key in ("tn", "teamName", "team_name", "club", "clubName", "club_name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("team", "clubData", "teamData"):
            nested = item.get(key)
            if not isinstance(nested, dict):
                continue
            for name_key in ("n", "name", "tn", "teamName"):
                value = nested.get(name_key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def competition_players(self) -> list[dict]:
        """Fetch the complete current competition player catalogue.

        The public competition ``/players`` route currently returns only the
        first 25 rows in some API versions and may ignore pagination offsets.
        Relying on it as the sole player-master source therefore silently
        truncates the Bundesliga pool.  Team profiles, on the other hand,
        expose the current squad for each Kickbase club and are already used by
        the app as the canonical source for player availability status.

        We consequently build the catalogue from all known team profiles and
        use the competition route only as an enrichment/fallback source.  This
        also makes promoted/relegated/transfer additions visible as soon as
        they appear in their club profile.
        """
        catalogue_rows: dict[str, dict] = {}

        # 1) Best-effort competition catalogue. It is useful for fields such
        # as market value/points even when the endpoint is truncated to 25.
        path = "/v4/competitions/1/players"
        try:
            data = self._get_json(path, params={"position": "0", "sorting": "1"})
            items = self._items(data)
            if isinstance(data, list):
                items = [item for item in data if isinstance(item, dict)]
            for item in items:
                player_id = item.get("i") or item.get("pi") or item.get("id")
                if player_id is not None:
                    catalogue_rows[str(player_id)] = dict(item)
        except Exception:
            pass

        # 2) Canonical complete pool: one teamprofile request per Bundesliga
        # club. Squads are small enough that these responses are not affected
        # by the 25-row competition catalogue limitation.
        combined: dict[str, dict] = {}
        for team_id, club_name in TEAM_NAMES.items():
            try:
                data = self._get_json(f"/v4/competitions/1/teams/{team_id}/teamprofile")
            except Exception:
                continue
            items = self._items(data)
            if isinstance(data, dict) and isinstance(data.get("it"), list):
                items = [row for row in data.get("it") or [] if isinstance(row, dict)]
            if isinstance(data, list):
                items = [row for row in data if isinstance(row, dict)]

            for row in items:
                player_id = row.get("i") or row.get("pi") or row.get("id")
                if player_id is None:
                    continue
                key = str(player_id)
                # Start with the (possibly richer) catalogue row and overwrite
                # with teamprofile values where present. Team assignment is
                # always taken from the profile currently being queried.
                merged = dict(catalogue_rows.get(key) or {})
                merged.update(row)
                merged["tid"] = team_id
                merged["tn"] = club_name
                combined[key] = merged

        # If teamprofile calls fail completely (e.g. temporary API outage), do
        # not turn a usable 25-row catalogue into an empty master.
        if not combined:
            combined = catalogue_rows
        else:
            # Keep catalogue-only rows as well. They may represent a brand-new
            # player whose teamprofile propagation is a few minutes behind.
            for key, row in catalogue_rows.items():
                combined.setdefault(key, row)

        players: list[dict] = []
        for item in combined.values():
            player_id = item.get("i") or item.get("pi") or item.get("id")
            if player_id is None:
                continue
            team_id_value = item.get("tid") or item.get("teamId")
            team_id = str(team_id_value) if team_id_value is not None else None
            club = self._club_from_payload(item)
            if not club and team_id is not None:
                club = team_name(team_id)

            first = str(item.get("fn") or item.get("firstName") or "").strip()
            last = str(item.get("ln") or item.get("n") or item.get("lastName") or item.get("name") or "").strip()
            full_name = " ".join(part for part in (first, last) if part).strip() or last or first or f"Spieler {player_id}"
            pos_raw = item.get("pos") if item.get("pos") is not None else item.get("position")
            players.append({
                "player_id": str(player_id),
                "name": last or full_name,
                "full_name": full_name,
                "club": club or "",
                "team_id": team_id,
                "team_image": item.get("pim") or item.get("tim") or item.get("teamSymbol"),
                "position": self.POSITION_MAP.get(pos_raw, self.POSITION_MAP.get(str(pos_raw), str(pos_raw or ""))),
                "market_value": self._first_int(item, ("mv", "marketValue")),
                "market_trend": self._first_int(item, ("mvt", "marketValueTrend")),
                "competition_status": self._first_int(item, ("status",)),
                "average_points": self._first_int(item, ("ap", "averagePoints")),
                "points_total": self._first_int(item, ("p", "tp", "totalPoints")),
                "raw": item,
            })

        players.sort(key=lambda player: ((player.get("club") or "").casefold(), (player.get("name") or "").casefold()))
        return players


    def competition_player_statuses(self) -> dict[str, dict]:
        """Return canonical Kickbase availability status for competition players.

        The competition-wide ``/players`` catalogue exposes a field named
        ``status`` whose values are *not* the same status enum used by league
        player rows.  Kickbase-Insights gets the actual availability value from
        each team's ``teamprofile`` rows (``st`` / ``stl``), so we deliberately
        do the same here.
        """
        statuses: dict[str, dict] = {}
        for team_id in TEAM_NAMES:
            try:
                data = self._get_json(f"/v4/competitions/1/teams/{team_id}/teamprofile")
            except Exception:
                continue
            items = self._items(data)
            if isinstance(data, dict) and isinstance(data.get("it"), list):
                items = [row for row in data.get("it") or [] if isinstance(row, dict)]
            for item in items:
                player_id = item.get("i") or item.get("pi") or item.get("id")
                if player_id is None:
                    continue
                raw_status = item.get("st")
                try:
                    status = int(raw_status) if raw_status is not None else None
                except (TypeError, ValueError):
                    status = None
                statuses[str(player_id)] = {
                    "status": status,
                    "status_list": item.get("stl") or [],
                }
        return statuses

    def competition_player_teams(self) -> dict[str, dict[str, str | None]]:
        """Return canonical current player/team assignments."""
        mapping: dict[str, dict[str, str | None]] = {}
        for item in self.competition_players():
            mapping[str(item["player_id"])] = {
                "club": item.get("club") or None,
                "team_id": item.get("team_id"),
                "team_image": item.get("team_image"),
            }
        return mapping

    def manager_squad(self, league_id: str, manager_id: str) -> list[dict]:
        """Load another manager's current squad with API-version fallbacks.

        Kickbase has moved this resource over time. We prefer v4 and retain the
        legacy user-players route as a compatibility fallback. Each route is
        read-only and the returned payload is normalized through one parser.
        """
        paths = [
            f"/v4/leagues/{league_id}/managers/{manager_id}/squad",
            f"/v2/leagues/{league_id}/managers/{manager_id}/squad",
            f"/leagues/{league_id}/users/{manager_id}/players",
        ]
        last_error: Exception | None = None
        for path in paths:
            try:
                data = self._get_json(path)
                players = self._parse_manager_squad_payload(data)
                if players:
                    return players
                last_error = KickbaseError(f"{path} lieferte keine lesbaren Spieler.")
            except Exception as exc:
                last_error = exc
        raise KickbaseError(str(last_error or "Manager-Kader konnte nicht geladen werden."))

    def _parse_manager_squad_payload(self, data: Any) -> list[dict]:
        candidates = self._items(data)
        if not candidates and isinstance(data, dict):
            for key in ("pls", "players", "squad"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates = [item for item in value if isinstance(item, dict)]
                    break

        players: list[dict] = []
        for item in candidates:
            player_id = item.get("i") or item.get("pi") or item.get("id")
            name = item.get("n") or item.get("pn") or item.get("name")
            if player_id is None or not name:
                continue

            team_id_value = item.get("tid") or item.get("teamId")
            team_id = str(team_id_value) if team_id_value is not None else None
            club = self._club_from_payload(item)
            if not club:
                club = self.TEAM_NAMES.get(team_id or "", "")
            if not club and team_id:
                club = f"Team {team_id}"
    
            market_value = self._to_int(item.get("mv") if item.get("mv") is not None else item.get("marketValue"))
            position_raw = item.get("pos") if item.get("pos") is not None else item.get("position")
            position = self.POSITION_MAP.get(position_raw, self.POSITION_MAP.get(str(position_raw), str(position_raw or "")))
            players.append(
                {
                    "player_id": str(player_id),
                    "name": str(name),
                    "club": str(club or ""),
                    "team_id": team_id,
                    "position": position,
                    "market_value": market_value,
                    "points_total": self._to_int(item.get("p") if item.get("p") is not None else item.get("points")),
                    "average_points": self._to_int(item.get("ap") if item.get("ap") is not None else item.get("averagePoints")),
                    "team_image": item.get("pim"),
                }
            )

        return players

    # ------------------------------------------------------------------
    # Manager dashboard = Kickbase's canonical aggregate values
    # ------------------------------------------------------------------

    def manager_dashboard(self, league_id: str, manager_id: str) -> dict:
        data = self._get_json(
            f"/v4/leagues/{league_id}/managers/{manager_id}/dashboard"
        )
        if not isinstance(data, dict):
            return {}
        return {
            "manager_id": str(data.get("u")) if data.get("u") is not None else manager_id,
            "manager_name": data.get("unm"),
            "team_value": self._to_int(data.get("tv")),
            "profit": self._to_int(data.get("prft")),
            "points": self._to_int(data.get("tp")),
            "average_points": self._to_int(data.get("ap")),
            "matchday_wins": self._to_int(data.get("mdw")),
            "place": self._to_int(data.get("pl")),
            "profile_image": data.get("uim"),
            "league_name": data.get("lnm"),
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Player details / market-value history
    # ------------------------------------------------------------------

    def player_details(self, league_id: str, player_id: str) -> dict:
        """Load rich player details, including Kickbase's localized status note.

        Kickbase-Insights showed that ``stxt`` is exposed by the competition player
        profile. We merge that payload with the league detail payload because the
        latter remains useful for league-specific values.
        """
        league_data: dict = {}
        profile_data: dict = {}
        try:
            raw = self._get_json(f"/v4/leagues/{league_id}/players/{player_id}")
            if isinstance(raw, dict):
                league_data = raw
        except Exception:
            league_data = {}
        try:
            raw = self._get_json(
                f"/v4/competitions/1/players/{player_id}",
                params={"leagueId": str(league_id)},
            )
            if isinstance(raw, dict):
                profile_data = raw
        except Exception:
            profile_data = {}

        if not league_data and not profile_data:
            raise KickbaseError("Spielerdetails konnten nicht geladen werden.")

        data = dict(profile_data)
        data.update({k: v for k, v in league_data.items() if v is not None})
        first = str(data.get("fn") or data.get("firstName") or "").strip()
        last = str(data.get("ln") or data.get("n") or data.get("lastName") or "").strip()
        full_name = " ".join(part for part in (first, last) if part).strip() or last or first
        team_id_value = data.get("tid") or data.get("teamId")
        team_id = str(team_id_value) if team_id_value is not None else None
        club = str(data.get("tn") or data.get("teamName") or "").strip()
        if not club and team_id:
            club = team_name(team_id)
        status_text = str(profile_data.get("stxt") or data.get("stxt") or "").strip()
        status_value = data.get("st") if data.get("st") is not None else data.get("status")
        status_list = data.get("stl") or data.get("statusList") or profile_data.get("stl") or []
        return {
            "player_id": str(data.get("i") or data.get("id") or player_id),
            "name": last or full_name or "Spieler",
            "full_name": full_name or last or "Spieler",
            "club": club,
            "team_id": team_id,
            "position": self.POSITION_MAP.get(data.get("pos") if data.get("pos") is not None else data.get("position"), str(data.get("pos") or data.get("position") or "")),
            "market_value": self._to_int(data.get("mv") if data.get("mv") is not None else data.get("marketValue")),
            "daily_change": self._to_int(data.get("tfhmvt")),
            "points_total": self._to_int(data.get("tp") if data.get("tp") is not None else data.get("p") if data.get("p") is not None else data.get("totalPoints")),
            "average_points": self._to_int(data.get("ap") if data.get("ap") is not None else data.get("averagePoints")),
            "team_image": data.get("tim") or data.get("pim"),
            "status": self._to_int(status_value),
            "status_list": status_list,
            "status_text": status_text or None,
            "raw": data,
            "profile_raw": profile_data,
        }

    def market_value_history(
        self,
        league_id: str,
        player_id: str,
        timeframe: int = 365,
    ) -> dict:
        """Load market-value history, preferring the competition-wide v4 route.

        The external Kickbase-Insights project uses the competition endpoint for
        a full 365-day history. League routes remain as fallbacks because Kickbase
        has changed these paths before.
        """
        timeframe = max(1, int(timeframe or 365))
        paths = [
            (f"/v4/competitions/1/players/{player_id}/marketValue/{timeframe}", None),
            (f"/v4/leagues/{league_id}/players/{player_id}/marketValue/{timeframe}", None),
            (f"/v4/leagues/{league_id}/players/{player_id}/marketvalue/{timeframe}", None),
        ]
        last_error: Exception | None = None
        for path, params in paths:
            try:
                data = self._get_json(path, params=params)
                return data if isinstance(data, dict) else {"it": data}
            except Exception as exc:
                last_error = exc
        raise KickbaseError(str(last_error or "Marktwert-Historie konnte nicht geladen werden."))
