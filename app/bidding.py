from __future__ import annotations

from dataclasses import dataclass


CREDIT_RATIO = 0.33


@dataclass(frozen=True)
class BidCapacity:
    squad_value: int
    effective_balance: int
    adjusted_squad_value: int
    minimum_balance: int
    maximum_new_bid: int


def calculate_bid_capacity(
    squad_value: int,
    balance_after_active_bids: int,
    *,
    existing_bid: int = 0,
) -> BidCapacity:
    """Calculate local bidding headroom using Kickbase's documented 33% rule.

    ``balance_after_active_bids`` is the cash position after currently active bids.
    If the selected player already has an own bid, that reservation is added back
    first because a replacement offer supersedes that player's current bid.

    Kickbase remains the authoritative validator; this helper is only a local
    pre-flight guard for the UI.
    """
    squad = max(0, int(squad_value or 0))
    balance = int(balance_after_active_bids or 0) + max(0, int(existing_bid or 0))
    adjusted = max(0, squad + min(balance, 0))
    minimum_balance = -int(adjusted * CREDIT_RATIO)
    maximum_new_bid = max(0, balance - minimum_balance)
    return BidCapacity(
        squad_value=squad,
        effective_balance=balance,
        adjusted_squad_value=adjusted,
        minimum_balance=minimum_balance,
        maximum_new_bid=maximum_new_bid,
    )
