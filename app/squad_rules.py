from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

MAX_SQUAD_SIZE = 18


@dataclass(frozen=True)
class SquadCapacity:
    current: int
    maximum: int = MAX_SQUAD_SIZE

    @property
    def free(self) -> int:
        return max(0, self.maximum - self.current)

    @property
    def is_full(self) -> bool:
        return self.current >= self.maximum

    @property
    def pressure(self) -> str:
        if self.current >= self.maximum:
            return "VOLL"
        if self.current == self.maximum - 1:
            return "HOCH"
        if self.current >= self.maximum - 3:
            return "NORMAL"
        return "NIEDRIG"

    @property
    def label(self) -> str:
        if self.is_full:
            return f"{self.current}/{self.maximum} · KADER VOLL"
        if self.free == 1:
            return f"{self.current}/{self.maximum} · 1 PLATZ FREI"
        return f"{self.current}/{self.maximum} · {self.free} PLÄTZE FREI"


def squad_capacity(squad_rows: Iterable[dict]) -> SquadCapacity:
    rows = [row for row in squad_rows if row is not None]
    return SquadCapacity(current=len(rows))


def active_bid_count(market_rows: Iterable[dict]) -> int:
    seen: set[str] = set()
    count = 0
    for row in market_rows:
        try:
            own_bid = int(row.get("own_bid") or 0)
        except (TypeError, ValueError, AttributeError):
            own_bid = 0
        if own_bid <= 0:
            continue
        player_id = str(row.get("player_id") or row.get("id") or "")
        key = player_id or f"row:{id(row)}"
        if key in seen:
            continue
        seen.add(key)
        count += 1
    return count


def required_sales(current_squad_size: int, incoming_players: int, *, maximum: int = MAX_SQUAD_SIZE) -> int:
    return max(0, int(current_squad_size or 0) + max(0, int(incoming_players or 0)) - int(maximum))
