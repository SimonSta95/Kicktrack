from __future__ import annotations


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _decision_points(investment_score: int | None, squad_fit_score: int | None, maximum: float = 45.0) -> tuple[float, float]:
    """Player decision independent of the concrete bid price."""
    trading = _clamp(float(investment_score or 0))
    squad = _clamp(float(squad_fit_score or 0))
    combined = squad * 0.55 + trading * 0.45
    return maximum * combined / 100.0, combined


def _max_bid_points(bid: int, market_value: int, max_bid: int | None, maximum: float = 35.0) -> tuple[float, str]:
    """Rate how much of the explicitly allowed premium the bid consumes."""
    if bid <= 0 or market_value <= 0:
        return maximum * 0.4, "Preisgrenze nicht belastbar"
    ceiling = int(max_bid or market_value)
    if ceiling <= market_value:
        if bid <= market_value:
            return maximum, "auf Marktwert"
        return 0.0, "über der Preisgrenze"
    premium_room = ceiling - market_value
    consumed = (bid - market_value) / premium_room
    if consumed <= 0:
        return maximum, "kein Premium verbraucht"
    if consumed <= 1:
        # At the ceiling there are still some points: the bid is allowed, just no longer attractive.
        factor = 1.0 - 0.55 * consumed
        return maximum * factor, f"{consumed*100:.0f}% des erlaubten Premiums genutzt"
    over = (bid - ceiling) / ceiling
    factor = max(0.0, 0.45 - over / 0.08 * 0.45)
    return maximum * factor, f"{over*100:.1f}% über Max-Bid"


def _budget_points(bid: int, balance: int | None, maximum: float = 20.0) -> tuple[float, float | None]:
    if not balance or balance <= 0 or bid <= 0:
        return maximum * 0.35, None
    share = bid / balance
    if share <= 0.15:
        points = maximum
    elif share <= 0.30:
        points = maximum * 0.90
    elif share <= 0.50:
        points = maximum * 0.70
    elif share <= 0.70:
        points = maximum * 0.40
    elif share <= 1.00:
        points = maximum * 0.10
    else:
        points = 0.0
    return points, share * 100.0


def rate_bid(
    *,
    bid: int,
    market_value: int | None,
    investment_score: int | None,
    squad_fit_score: int | None,
    balance: int | None,
    max_bid: int | None = None,
    minimum_bid: int | None = None,
    confidence_label: str | None = None,
    investment_horizon: str | None = None,
) -> dict:
    """Return an interpretable bid rating without price double-counting.

    Weighting:
    - underlying player decision (sporting + trading): 45
    - concrete bid relative to Max-Bid: 35
    - budget burden: 20
    """
    bid = max(0, int(bid or 0))
    mv = int(market_value or 0)
    minimum_bid = int(minimum_bid or mv or 0)
    max_bid = int(max_bid or 0) or None
    delta = bid - mv if bid and mv else None
    delta_pct = (delta / mv * 100.0) if delta is not None and mv else None

    decision_points, player_decision = _decision_points(investment_score, squad_fit_score, 45.0)
    # When no personalized Max-Bid was supplied, use only a generic +8% safety
    # ceiling for the rating instead of treating every euro above MW as invalid.
    rating_ceiling = max_bid if max_bid is not None else (int(round(mv * 1.08)) if mv else None)
    price_points, price_reason = _max_bid_points(bid, mv, rating_ceiling, 35.0)
    budget_points, budget_share_pct = _budget_points(bid, balance, 20.0)
    score = round(_clamp(decision_points + price_points + budget_points))
    below_minimum = bool(minimum_bid and bid < minimum_bid)

    if below_minimum:
        signal = "UNTER MINDESTGEBOT"
        score = min(score, 20)
    elif max_bid and bid > max_bid:
        signal = "ZU TEUER" if bid > max_bid * 1.03 else "AGGRESSIV"
        if bid > max_bid * 1.08:
            score = min(score, 35)
    elif score >= 78:
        signal = "GUTES GEBOT"
    elif score >= 62:
        signal = "FAIR"
    elif score >= 48:
        signal = "AGGRESSIV"
    else:
        signal = "NICHT SINNVOLL"

    if delta_pct is None:
        price_text = "Preisvergleich nicht möglich"
    elif delta_pct < 0:
        price_text = f"{abs(delta_pct):.1f} % unter Marktwert"
    elif delta_pct > 0:
        price_text = f"{delta_pct:.1f} % über Marktwert"
    else:
        price_text = "exakt auf Marktwert"

    budget_text = "Budgetanteil nicht bestimmbar" if budget_share_pct is None else f"bindet {budget_share_pct:.1f} % des Kontostands"
    explanation = (
        f"GEBOTSBEWERTUNG · {score}/100\n\n"
        f"Gebot: {bid:,} €\nMarktwert: {mv:,} €\n{price_text}\n\n"
        f"Spielerentscheidung: {decision_points:.1f}/45 ({player_decision:.0f}/100)\n"
        f"Gebot vs. Max-Bid: {price_points:.1f}/35 ({price_reason})\n"
        f"Budgetbelastung: {budget_points:.1f}/20 ({budget_text})\n"
        + (f"Mindestgebot: {minimum_bid:,} €\n" if minimum_bid else "")
        + (f"Max-Bid: {max_bid:,} €\n" if max_bid else "")
        + (f"Datenbasis: {confidence_label}\n" if confidence_label else "")
        + (f"Horizont: {investment_horizon}\n" if investment_horizon else "")
        + ("\nGebot liegt unter dem erforderlichen Marktwert und ist damit nicht ausführbar.\n" if below_minimum else "")
        + f"\n→ {signal}"
    ).replace(",", ".")

    return {
        "bid_score": score,
        "bid_signal": signal,
        "bid_delta": delta,
        "bid_delta_pct": delta_pct,
        "bid_budget_share_pct": budget_share_pct,
        "bid_breakdown": {
            "spielerentscheidung": round(decision_points, 1),
            "max_bid": round(price_points, 1),
            "budget": round(budget_points, 1),
            # compatibility keys
            "preis": round(price_points, 1),
            "investment": round(45.0 * 0.45 * _clamp(float(investment_score or 0)) / 100.0, 1),
            "kader_fit": round(45.0 * 0.55 * _clamp(float(squad_fit_score or 0)) / 100.0, 1),
        },
        "bid_analysis_text": explanation,
    }
