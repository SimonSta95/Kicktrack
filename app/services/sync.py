from __future__ import annotations

from dataclasses import dataclass, field

from app.kickbase import KickbaseClient


@dataclass(slots=True)
class SyncResult:
    league_id: str
    players: list[dict]
    manager_id: str | None
    transfers: list[dict] = field(default_factory=list)
    acquisitions: dict[str, dict] = field(default_factory=dict)
    dashboard: dict = field(default_factory=dict)
    league_info: dict = field(default_factory=dict)

    @property
    def dashboard_loaded(self) -> bool:
        return self.dashboard.get("profit") is not None or self.dashboard.get("team_value") is not None


class KickbaseSyncService:
    """Fetch one coherent league snapshot without touching Qt or SQLite.

    Keeping network orchestration here makes the UI deterministic and lets the
    expensive API calls run safely on a background thread.
    """

    def __init__(self, client: KickbaseClient) -> None:
        self.client = client

    def fetch(self, league_id: str, known_manager_id: str | None = None) -> SyncResult:
        players = self.client.squad(league_id)
        manager_id = known_manager_id or self.client.detect_manager_id(league_id, players)

        transfers: list[dict] = []
        acquisitions: dict[str, dict] = {}
        dashboard: dict = {}

        if manager_id:
            transfer_response = self.client.manager_transfers(league_id, manager_id)
            transfers = self.client.parse_manager_transfers(transfer_response)
            acquisitions = {
                player["player_id"]: self.client.acquisition_for_current_player(player, transfers)
                for player in players
            }
            try:
                dashboard = self.client.manager_dashboard(league_id, manager_id)
            except Exception:
                # Dashboard data is useful but not required for a successful squad sync.
                dashboard = {}
        else:
            acquisitions = self._fallback_acquisitions(league_id, players)

        league_info = self.client.league_info(league_id)
        return SyncResult(
            league_id=league_id,
            players=players,
            manager_id=manager_id,
            transfers=transfers,
            acquisitions=acquisitions,
            dashboard=dashboard,
            league_info=league_info,
        )

    def _fallback_acquisitions(self, league_id: str, players: list[dict]) -> dict[str, dict]:
        acquisitions: dict[str, dict] = {}
        for player in players:
            player_id = player["player_id"]
            try:
                history = self.client.player_transfer_history(league_id, player_id)
                history = sorted(history, key=lambda item: item.get("dt") or "")
                latest = history[-1] if history else None

                if latest and int(latest.get("t") or -1) == 2 and int(latest.get("trp") or 0) > 0:
                    entry = int(latest["trp"])
                    acquisitions[player_id] = {
                        "origin": "TRANSFER",
                        "entry_value": entry,
                        "purchase_price": entry,
                        "purchase_date": latest.get("dt"),
                    }
                    continue

                market_value = int(player["market_value"])
                gain_loss = player.get("market_gain_loss")
                acquisitions[player_id] = {
                    "origin": "STARTKADER",
                    "entry_value": market_value - int(gain_loss) if gain_loss is not None else None,
                    "purchase_price": None,
                    "purchase_date": latest.get("dt") if latest else None,
                }
            except Exception:
                # A single malformed player history must not invalidate the whole snapshot.
                acquisitions[player_id] = {
                    "origin": "UNKNOWN",
                    "entry_value": None,
                    "purchase_price": None,
                    "purchase_date": None,
                }
        return acquisitions
