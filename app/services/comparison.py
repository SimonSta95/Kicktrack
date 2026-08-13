from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

POSITIONS = ("TW", "ABW", "MF", "ST")


@dataclass(slots=True)
class PositionComparison:
    position: str
    player_count: int
    market_value: int
    average_points: float | None


@dataclass(slots=True)
class SquadComparison:
    player_count: int
    market_value: int
    average_points: float | None
    total_points: int | None
    positions: dict[str, PositionComparison]
    top_by_average_points: list[dict]
    top_by_market_value: list[dict]


def _number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_squad(players: list[dict], *, top_n: int = 3) -> SquadComparison:
    normalized = [player for player in players if isinstance(player, dict)]
    market_value = sum(max(0, int(_number(player.get("market_value")) or 0)) for player in normalized)

    averages = [
        value
        for player in normalized
        if (value := _number(player.get("average_points"))) is not None
    ]
    totals = [
        int(value)
        for player in normalized
        if (value := _number(player.get("points_total"))) is not None
    ]

    positions: dict[str, PositionComparison] = {}
    for position in POSITIONS:
        group = [player for player in normalized if str(player.get("position") or "") == position]
        group_averages = [
            value
            for player in group
            if (value := _number(player.get("average_points"))) is not None
        ]
        positions[position] = PositionComparison(
            position=position,
            player_count=len(group),
            market_value=sum(max(0, int(_number(player.get("market_value")) or 0)) for player in group),
            average_points=mean(group_averages) if group_averages else None,
        )

    top_by_average_points = sorted(
        normalized,
        key=lambda player: _number(player.get("average_points")) if _number(player.get("average_points")) is not None else -1,
        reverse=True,
    )[:top_n]
    top_by_market_value = sorted(
        normalized,
        key=lambda player: _number(player.get("market_value")) or 0,
        reverse=True,
    )[:top_n]

    return SquadComparison(
        player_count=len(normalized),
        market_value=market_value,
        average_points=mean(averages) if averages else None,
        total_points=sum(totals) if totals else None,
        positions=positions,
        top_by_average_points=top_by_average_points,
        top_by_market_value=top_by_market_value,
    )
