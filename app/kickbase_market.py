from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.teams import TEAM_NAMES, team_name

from .kickbase_common import KickbaseError

class KickbaseMarketMixin:
    @classmethod
    def _first_int(cls, data: Any, keys: tuple[str, ...]) -> int | None:
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data:
                value = cls._to_int(data.get(key))
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
                # Own market entries expose incoming manager bids in ``ofs``.
                # Keep them attached to the listing so the UI can show a fast
                # offer count without issuing another request. The offer modal
                # still refreshes the targeted player state before a write.
                incoming = self.normalize_incoming_offers({"ofs": self._offer_items(item)})
                player["incoming_offers"] = incoming
                player["offer_count"] = int(item.get("ofc") or len(incoming) or 0)
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
        """Return the live listing/offer state for one player.

        Kickbase exposes incoming offers for an owned listing on the player's
        ``/transfers`` endpoint. This is distinct from ``/transferHistory``,
        which contains completed transfers only.
        """
        payload = self._get_json(f"/v4/leagues/{league_id}/players/{player_id}/transfers")
        if not isinstance(payload, dict):
            payload = {}
        return {
            "raw": payload,
            "offers": self.normalize_incoming_offers(payload),
            "is_on_market": bool(payload.get("iotm") or payload.get("iposl")),
            "market_value": self._first_int(payload, ("mv", "marketValue")),
            "listing_price": self._first_int(payload, ("prc", "price", "p")),
        }

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
            raw_offer_id = raw.get("i") or raw.get("id") or raw.get("oi") or raw.get("ofi") or raw.get("offerId")
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
            # In current v4 responses the path offerId is the bidder user id
            # (uoid/u). Prefer that verified identifier over legacy generic ids.
            offer_id = raw.get("uoid") or raw.get("oui") or raw_offer_id or user_id
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
        if not offer_id:
            raise KickbaseError("Keine Angebots-ID vorhanden.")
        response = self.client.post(
            f"/v4/leagues/{league_id}/market/{player_id}/offers/{offer_id}/accept"
        )
        self._raise_write_error("Manager-Angebot annehmen", response)
        return self._response_payload(response)

    def decline_manager_offer(self, league_id: str, player_id: str, offer_id: str) -> dict:
        if not offer_id:
            raise KickbaseError("Keine Angebots-ID vorhanden.")
        response = self.client.post(
            f"/v4/leagues/{league_id}/market/{player_id}/offers/{offer_id}/decline"
        )
        self._raise_write_error("Manager-Angebot ablehnen", response)
        return self._response_payload(response)

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
