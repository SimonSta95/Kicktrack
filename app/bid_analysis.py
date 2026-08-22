from __future__ import annotations


def rate_bid(
    *,
    bid: int,
    market_value: int | None,
    investment_score: int | None = None,
    squad_fit_score: int | None = None,
    balance: int | None,
    max_bid: int | None = None,
    minimum_bid: int | None = None,
    confidence_label: str | None = None,
    investment_horizon: str | None = None,
) -> dict:
    """Describe a bid with factual price/budget context, not a synthetic score.

    The caller performs the real Kickbase 33%-rule pre-flight separately.  This
    function intentionally ignores legacy player scores and personalized Max-Bid
    estimates; those were subjective weights presented with false precision.
    """
    bid = max(0, int(bid or 0))
    mv = max(0, int(market_value or 0))
    minimum = max(0, int(minimum_bid or mv or 0))
    delta = bid - mv if bid and mv else None
    delta_pct = (delta / mv * 100.0) if delta is not None and mv else None
    budget_share_pct = None
    if balance is not None and int(balance) != 0 and bid > 0:
        budget_share_pct = bid / abs(int(balance)) * 100.0

    if minimum and bid < minimum:
        signal = "UNTER MINDESTGEBOT"
        summary = "Das Gebot liegt unter dem aktuell erforderlichen Mindestgebot."
    elif delta_pct is None:
        signal = "PREIS PRÜFEN"
        summary = "Für den Preisvergleich fehlen belastbare Marktwertdaten."
    elif delta_pct <= 0:
        signal = "AUF MARKTWERT"
        summary = "Das Gebot liegt auf oder unter dem aktuellen Marktwert."
    elif delta_pct <= 2.0:
        signal = "GERINGER AUFPREIS"
        summary = "Das Gebot liegt nur leicht über dem aktuellen Marktwert."
    elif delta_pct <= 5.0:
        signal = "AUFPREIS PRÜFEN"
        summary = "Der Aufpreis ist sichtbar und sollte durch konkrete Gründe gerechtfertigt sein."
    else:
        signal = "HOHER AUFPREIS"
        summary = "Das Gebot liegt deutlich über dem aktuellen Marktwert."

    lines = [
        "GEBOT · FAKTEN",
        "",
        f"Gebot: {bid:,} €".replace(",", "."),
        f"Marktwert: {mv:,} €".replace(",", "."),
    ]
    if delta is not None:
        lines.append(f"Differenz: {delta:+,} € ({delta_pct:+.1f} %)".replace(",", "."))
    if minimum:
        lines.append(f"Mindestgebot: {minimum:,} €".replace(",", "."))
    if budget_share_pct is not None:
        lines.append(f"Anteil am angegebenen Budget: {budget_share_pct:.1f} %")
    lines.extend(["", summary, f"→ {signal}"])

    return {
        "bid_score": None,  # legacy key: intentionally retired
        "bid_signal": signal,
        "bid_delta": delta,
        "bid_delta_pct": delta_pct,
        "bid_budget_share_pct": budget_share_pct,
        "bid_breakdown": {
            "price_vs_market_value_pct": delta_pct,
            "budget_share_pct": budget_share_pct,
            "minimum_bid": minimum,
        },
        "bid_analysis_text": "\n".join(lines),
    }
