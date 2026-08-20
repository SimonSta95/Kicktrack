from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.teams import TEAM_NAMES, team_name

from .kickbase_common import KickbaseError

class KickbaseLeagueMixin:
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
