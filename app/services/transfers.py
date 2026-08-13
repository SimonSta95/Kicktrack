from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean


@dataclass(slots=True)
class CompletedTrade:
    player_id: str
    player_name: str
    buy_price: int
    sell_price: int
    pnl: int
    bought_at: str
    sold_at: str
    holding_days: float | None


@dataclass(slots=True)
class TransferBehavior:
    buy_count: int
    sell_count: int
    buy_volume: int
    sell_volume: int
    completed_trade_count: int
    realized_pnl: int
    average_holding_days: float | None
    best_trade: CompletedTrade | None
    worst_trade: CompletedTrade | None
    completed_trades: list[CompletedTrade]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def analyze_manager_transfers(events: list[dict]) -> TransferBehavior:
    """Calculate transparent transfer KPIs from observable buy/sell events.

    A sale is paired with the latest unmatched buy of the same player. Sales of
    start-squad players therefore do not invent a purchase price and are not
    counted as completed trades / realized trading P&L.
    """
    normalized = sorted(
        [event for event in events if isinstance(event, dict)],
        key=lambda event: str(event.get("transferred_at") or ""),
    )
    buys = [event for event in normalized if event.get("transfer_type") == "BUY"]
    sells = [event for event in normalized if event.get("transfer_type") == "SELL"]

    open_buys: dict[str, dict] = {}
    completed: list[CompletedTrade] = []
    for event in normalized:
        player_id = str(event.get("player_id") or "")
        if not player_id:
            continue
        transfer_type = event.get("transfer_type")
        if transfer_type == "BUY":
            open_buys[player_id] = event
            continue
        if transfer_type != "SELL":
            continue
        buy = open_buys.pop(player_id, None)
        if not buy:
            continue

        buy_price = int(buy.get("price") or 0)
        sell_price = int(event.get("price") or 0)
        bought_at = str(buy.get("transferred_at") or "")
        sold_at = str(event.get("transferred_at") or "")
        start = _parse_datetime(bought_at)
        end = _parse_datetime(sold_at)
        holding_days = None
        if start is not None and end is not None and end >= start:
            holding_days = (end - start).total_seconds() / 86400

        completed.append(
            CompletedTrade(
                player_id=player_id,
                player_name=str(event.get("player_name") or buy.get("player_name") or "Unbekannt"),
                buy_price=buy_price,
                sell_price=sell_price,
                pnl=sell_price - buy_price,
                bought_at=bought_at,
                sold_at=sold_at,
                holding_days=holding_days,
            )
        )

    holding = [trade.holding_days for trade in completed if trade.holding_days is not None]
    best = max(completed, key=lambda trade: trade.pnl, default=None)
    worst = min(completed, key=lambda trade: trade.pnl, default=None)
    return TransferBehavior(
        buy_count=len(buys),
        sell_count=len(sells),
        buy_volume=sum(int(event.get("price") or 0) for event in buys),
        sell_volume=sum(int(event.get("price") or 0) for event in sells),
        completed_trade_count=len(completed),
        realized_pnl=sum(trade.pnl for trade in completed),
        average_holding_days=mean(holding) if holding else None,
        best_trade=best,
        worst_trade=worst,
        completed_trades=sorted(completed, key=lambda trade: trade.sold_at, reverse=True),
    )
