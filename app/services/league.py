from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.kickbase import KickbaseClient, KickbaseError
from app.storage import Storage
from app.season import filter_current_season_transfers
from app.teams import team_name


@dataclass(slots=True)
class LeagueManager:
    manager_id: str
    name: str
    profile_image: str | None = None
    is_user: bool = False
    team_value: int | None = None
    profit: int | None = None
    points: int | None = None
    average_points: int | None = None
    matchday_wins: int | None = None
    place: int | None = None


@dataclass(slots=True)
class LeagueOverviewResult:
    league_id: str
    managers: list[LeagueManager] = field(default_factory=list)
    matchday: int | None = None
    season_started: bool = False
    fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat()
    )


@dataclass(slots=True)
class ManagerSquadResult:
    league_id: str
    manager_id: str
    players: list[dict]
    fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat()
    )


@dataclass(slots=True)
class ManagerDetailResult:
    league_id: str
    manager_id: str
    players: list[dict]
    transfers: list[dict] = field(default_factory=list)
    transfer_error: str | None = None


@dataclass(slots=True)
class LeagueOwnershipResult:
    league_id: str
    squads: list[ManagerSquadResult] = field(default_factory=list)
    failed_manager_ids: list[str] = field(default_factory=list)
    fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat()
    )

class LeagueAnalysisService:
    """League/competitor orchestration with persistent SQLite TTL caching."""

    MANAGERS_TTL = 10 * 60
    RANKING_TTL = 5 * 60
    DASHBOARD_TTL = 10 * 60
    SQUAD_TTL = 15 * 60
    MANAGER_TRANSFERS_TTL = 15 * 60
    COMPETITION_PLAYERS_TTL = 2 * 60 * 60

    def __init__(self, client: KickbaseClient, storage: Storage) -> None:
        self.client = client
        self.storage = storage

    def _cached(self, key: str, ttl: int, loader, *, force: bool = False):
        if not force:
            cached = self.storage.cache_get(key, ttl)
            if cached is not None:
                return cached
        value = loader()
        self.storage.cache_set(key, value)
        return value

    def _competition_player_teams(self, *, force: bool = False) -> dict[str, dict[str, str | None]]:
        key = "competition:1:player_teams"
        data = self._cached(
            key,
            self.COMPETITION_PLAYERS_TTL,
            self.client.competition_player_teams,
            force=force,
        )
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _enrich_players(players: list[dict], canonical: dict[str, dict[str, str | None]]) -> list[dict]:
        """Apply the current competition assignment to cached/current player rows.

        Kickbase's competition-player payload currently contains ``tid`` but no
        team name. Older cached squad rows can therefore carry a stale resolved
        club label even though their team id is correct. Always derive the club
        label again from the canonical/current team id instead of trusting the
        cached text value.
        """
        for player in players:
            current = canonical.get(str(player.get("player_id")))
            if current:
                if "team_id" in current:
                    player["team_id"] = (
                        str(current["team_id"]) if current.get("team_id") is not None else None
                    )
                if current.get("team_image"):
                    player["team_image"] = current["team_image"]

                canonical_club = str(current.get("club") or "").strip()
                if canonical_club:
                    player["club"] = canonical_club
                elif player.get("team_id") is not None:
                    # Important for cached squads: competition /players exposes
                    # tid but no team name, so recalculate the label from tid.
                    player["club"] = team_name(player["team_id"])
            elif player.get("team_id") is not None:
                # Even without a competition hit, never keep an obsolete cached
                # label such as Team 15 / Gladbach after the mapping changed.
                player["club"] = team_name(player["team_id"])

        return players

    def _cached_squad_team_value(self, league_id: str, manager_id: str) -> int | None:
        """Return current squad market value, using the persistent squad cache.

        This is intentionally only a fallback for phases where Kickbase reports
        a zero manager team value. It reuses the same 15 minute SQLite cache as
        manager detail squads and therefore remains lightweight.
        """
        try:
            players = self._cached(
                f"league:{league_id}:manager:{manager_id}:squad",
                self.SQUAD_TTL,
                lambda: self.client.manager_squad(league_id, manager_id),
                force=False,
            )
        except Exception:
            return None

        if not isinstance(players, list) or not players:
            return None

        values: list[int] = []
        for player in players:
            if not isinstance(player, dict):
                continue
            value = self.client._to_int(player.get("market_value"))
            if value is not None and value >= 0:
                values.append(value)

        return sum(values) if values else None

    def fetch_overview(self, league_id: str, *, force: bool = False) -> LeagueOverviewResult:
        payload = self._cached(
            f"league:{league_id}:managers",
            self.MANAGERS_TTL,
            lambda: self.client.league_managers(league_id),
            force=force,
        )
        try:
            ranking_payload = self._cached(
                f"league:{league_id}:ranking",
                self.RANKING_TTL,
                lambda: self.client.league_ranking(league_id),
                force=force,
            )
        except Exception:
            ranking_payload = {}

        ranking_by_id = {
            str(item.get("manager_id")): item
            for item in ranking_payload.get("managers", [])
            if item.get("manager_id") is not None
        }
        current_matchday = self.client._to_int(ranking_payload.get("matchday"))
        if current_matchday is None:
            current_matchday = self.client._to_int(payload.get("matchday"))

        ranking_points = [
            self.client._to_int(item.get("points"))
            for item in ranking_payload.get("managers", [])
            if isinstance(item, dict)
        ]
        has_positive_points = any(p is not None and p > 0 for p in ranking_points)
        # Kickbase's matchday field can still point at the previous season during
        # the reset/preseason window. Current-season aggregate metrics (average
        # points / matchday wins) are considered valid only after the current
        # ranking has actually accumulated points.
        season_started = has_positive_points

        managers: list[LeagueManager] = []
        for raw_manager in payload.get("managers", []):
            manager_id = str(raw_manager["manager_id"])
            summary = LeagueManager(
                manager_id=manager_id,
                name=str(raw_manager.get("name") or "Unbekannt"),
                profile_image=raw_manager.get("profile_image"),
                is_user=bool(raw_manager.get("is_user")),
            )

            try:
                dashboard = self._cached(
                    f"league:{league_id}:manager:{manager_id}:dashboard",
                    self.DASHBOARD_TTL,
                    lambda mid=manager_id: self.client.manager_dashboard(league_id, mid),
                    force=force,
                )
            except Exception:
                dashboard = {}

            ranking = ranking_by_id.get(manager_id, {})
            dashboard_team_value = self.client._to_int(dashboard.get("team_value"))
            ranking_team_value = self.client._to_int(ranking.get("team_value"))

            # Kickbase can return tv=0 from ranking/dashboard around a season
            # reset even though the manager already owns a squad. Prefer the
            # canonical dashboard value when it is usable; otherwise derive the
            # team value from the current squad. The squad response is persisted
            # in the SQLite API cache, so this fallback does not create repeated
            # requests on every league view.
            summary.team_value = (
                dashboard_team_value
                if dashboard_team_value is not None and dashboard_team_value > 0
                else ranking_team_value
                if ranking_team_value is not None and ranking_team_value > 0
                else self._cached_squad_team_value(league_id, manager_id)
            )
            summary.profit = self.client._to_int(dashboard.get("profit"))

            # Place and points come exclusively from the current ranking. They are
            # safe to show as 0 during preseason. Dashboard aggregates, however,
            # can still contain last-season values and are therefore gated by
            # ``season_started``. A manager missing from the current ranking gets
            # no current-season metrics at all.
            has_current_ranking = bool(ranking)
            summary.points = (
                self.client._to_int(ranking.get("points")) if has_current_ranking else None
            )
            summary.place = (
                self.client._to_int(ranking.get("place")) if has_current_ranking else None
            )
            summary.average_points = (
                self.client._to_int(dashboard.get("average_points"))
                if season_started and has_current_ranking
                else None
            )
            summary.matchday_wins = (
                self.client._to_int(dashboard.get("matchday_wins"))
                if season_started and has_current_ranking
                else None
            )

            if dashboard.get("manager_name"):
                summary.name = str(dashboard["manager_name"])
            elif ranking.get("name"):
                summary.name = str(ranking["name"])
            if dashboard.get("profile_image"):
                summary.profile_image = dashboard["profile_image"]
            elif ranking.get("profile_image"):
                summary.profile_image = ranking["profile_image"]
            managers.append(summary)

        managers.sort(
            key=lambda manager: (
                manager.place is None,
                manager.place if manager.place is not None else 10**9,
                manager.name.casefold(),
            )
        )
        return LeagueOverviewResult(
            league_id=league_id,
            managers=managers,
            matchday=current_matchday,
            season_started=season_started,
        )

    def fetch_ownership(self, league_id: str, manager_ids: list[str], *, force: bool = False) -> LeagueOwnershipResult:
        """Build a league-wide player ownership index from persisted TTL caches.

        Squads are fetched sequentially and independently so one unavailable
        manager does not discard the ownership data for everybody else. API
        responses are still governed by ``SQUAD_TTL`` in SQLite.
        """
        canonical: dict[str, dict[str, str | None]] = {}
        try:
            canonical = self._competition_player_teams(force=force)
        except Exception:
            pass

        squads: list[ManagerSquadResult] = []
        failed: list[str] = []
        for raw_id in manager_ids:
            manager_id = str(raw_id)
            try:
                players = self._cached(
                    f"league:{league_id}:manager:{manager_id}:squad",
                    self.SQUAD_TTL,
                    lambda mid=manager_id: self.client.manager_squad(league_id, mid),
                    force=force,
                )
                players = [dict(player) for player in players] if isinstance(players, list) else []
                if canonical:
                    players = self._enrich_players(players, canonical)
                squads.append(
                    ManagerSquadResult(
                        league_id=league_id,
                        manager_id=manager_id,
                        players=players,
                    )
                )
            except Exception:
                failed.append(manager_id)

        return LeagueOwnershipResult(
            league_id=league_id,
            squads=squads,
            failed_manager_ids=failed,
        )

    def fetch_manager_detail(self, league_id: str, manager_id: str) -> ManagerDetailResult:
        squad = self.fetch_manager_squad(league_id, manager_id, force=False)
        transfers: list[dict] = []
        transfer_error: str | None = None
        try:
            raw = self._cached(
                f"league:{league_id}:manager:{manager_id}:transfers",
                self.MANAGER_TRANSFERS_TTL,
                lambda: self.client.manager_transfers(league_id, manager_id),
                force=False,
            )
            transfers = self.client.parse_manager_transfers(raw if isinstance(raw, dict) else {})
            transfers = filter_current_season_transfers(transfers)
            try:
                canonical = self._competition_player_teams()
                transfers = self._enrich_players(transfers, canonical)
            except Exception:
                pass
            self.storage.upsert_league_manager_transfers(league_id, manager_id, transfers)
        except Exception as exc:
            transfer_error = str(exc)

        return ManagerDetailResult(
            league_id=league_id,
            manager_id=manager_id,
            players=squad.players,
            transfers=transfers,
            transfer_error=transfer_error,
        )

    def fetch_manager_squad(self, league_id: str, manager_id: str, *, force: bool = False) -> ManagerSquadResult:
        players = self._cached(
            f"league:{league_id}:manager:{manager_id}:squad",
            self.SQUAD_TTL,
            lambda: self.client.manager_squad(league_id, manager_id),
            force=force,
        )
        players = [dict(player) for player in players] if isinstance(players, list) else []
        try:
            canonical = self._competition_player_teams()
            players = self._enrich_players(players, canonical)
        except Exception:
            pass
        return ManagerSquadResult(
            league_id=league_id,
            manager_id=manager_id,
            players=players,
        )

