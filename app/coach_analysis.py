from __future__ import annotations

from typing import Iterable

from .squad_rules import MAX_SQUAD_SIZE, active_bid_count, squad_capacity
from .market_value_insights import trend_display


def _money(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _trend_context(row: dict) -> tuple[str, str, list[str]]:
    trend = row.get("mv_trend") or {}
    reversal = row.get("trend_reversal_prediction") or {}
    label = trend_display(trend)
    risk = str(reversal.get("risk") or "UNSICHER")
    facts: list[str] = []
    if trend.get("steps_text"):
        facts.append(f"MW-Schritte: {trend.get('steps_text')}")
    streak = int(trend.get("streak") or 0)
    if streak:
        facts.append(f"{abs(streak)} {'positive' if streak > 0 else 'negative'} Refreshes in Folge")
    if reversal.get("probability") is not None:
        facts.append(
            f"Wende-Risiko {risk}: {float(reversal.get('probability'))*100:.0f}% bei n={int(reversal.get('sample_count') or 0)} Vergleichsfällen"
        )
    return label, risk, facts


def _price_fact(row: dict) -> str | None:
    price = _money(row.get("price"))
    mv = _money(row.get("market_value"))
    if price <= 0 or mv <= 0:
        return None
    pct = (price - mv) / mv * 100.0
    return f"Marktpreis {pct:+.1f}% zum MW"


def _rec(*, kind: str, label: str, priority: int, row: dict | None = None, action: str, reasons: list[str], primary_reason: str, secondary_reason: str | None = None, source: str = "") -> dict:
    row = dict(row or {})
    return {
        "kind": kind,
        "label": label,
        "priority": int(priority),  # internal ordering only; never shown as a score
        "primary_reason": primary_reason,
        "secondary_reason": secondary_reason,
        "secondary_tags": [],
        "planability": "",
        "action": action,
        "reasons": [reason for reason in reasons if reason][:4],
        "player_id": row.get("player_id"),
        "name": row.get("full_name") or row.get("name") or primary_reason,
        "club": row.get("club") or "",
        "position": row.get("position") or "",
        "price": _money(row.get("price") or row.get("market_value")),
        "market_value": _money(row.get("market_value")),
        "own_bid": _money(row.get("own_bid")),
        "source": source or ("Kickbase" if row.get("is_kickbase") else str(row.get("seller_name") or "")),
        "confidence": "",
        "horizon": "",
        "raw": row,
    }


def build_coach_recommendations(
    market_rows: Iterable[dict],
    squad_rows: Iterable[dict],
    *,
    managers: Iterable[dict] | None = None,
    own_manager_id: str | None = None,
    available_budget: int | None = None,
    portfolio_summary: dict | None = None,
    limit: int = 16,
) -> list[dict]:
    """Build Facts-First recommendations without synthetic player scores.

    Recommendations use visible facts: squad capacity, active bids, price-vs-MW,
    actual MW steps, user-assigned squad roles, P/L and model outputs that are
    explicitly labelled as predictions.  ``priority`` is only a deterministic UI
    ordering key and is intentionally not presented to the user.
    """
    market = [dict(row) for row in market_rows or []]
    squad = [dict(row) for row in squad_rows or []]
    capacity = squad_capacity(squad)
    open_bids = active_bid_count(market)
    recs: list[dict] = []

    if capacity.is_full:
        recs.append(_rec(
            kind="warning",
            label="KADER VOLL",
            priority=100,
            action="Vor einem weiteren Zugang muss ein Kaderplatz frei werden.",
            reasons=[f"Kader {capacity.current}/{MAX_SQUAD_SIZE}", "Kickbase erlaubt maximal 18 Spieler."],
            primary_reason="KADERPLÄTZE",
            secondary_reason="KAUF BRAUCHT ABGANG",
            source="Kader",
        ))
    elif open_bids > capacity.free:
        recs.append(_rec(
            kind="warning",
            label="KADERPLÄTZE PRÜFEN",
            priority=96,
            action="Nicht alle aktiven Gebote können gleichzeitig ohne zusätzlichen Abgang in den Kader kommen.",
            reasons=[f"{capacity.free} freie Plätze", f"{open_bids} aktive Gebote"],
            primary_reason="KADERPLÄTZE",
            secondary_reason="AKTIVE GEBOTE",
            source="Kader",
        ))

    if available_budget is not None and int(available_budget) < 0:
        recs.append(_rec(
            kind="warning",
            label="LIQUIDITÄT PRÜFEN",
            priority=98,
            action="Aktive Gebote und geplante Verkäufe prüfen. Zum Spieltags-Stichtag muss der Saldo mindestens 0 € betragen.",
            reasons=[f"Saldo nach aktiven Geboten: {int(available_budget):+d} €"],
            primary_reason="LIQUIDITÄT",
            secondary_reason="SPIELTAGSREGEL",
            source="Budget",
        ))

    for row in market:
        signal = str(row.get("facts_signal") or row.get("action") or "KEINE KLARE EMPFEHLUNG").upper()
        trend_label, risk, trend_facts = _trend_context(row)
        reasons = list(trend_facts)
        price_fact = _price_fact(row)
        if price_fact:
            reasons.append(price_fact)
        d7 = row.get("d7")
        if d7 is not None:
            reasons.append(f"7T MW {int(d7):+d} €")

        if _money(row.get("own_bid")) > 0:
            own_bid = _money(row.get("own_bid"))
            mv = _money(row.get("market_value"))
            bid_pct = ((own_bid - mv) / mv * 100.0) if mv else None
            bid_reason = f"Eigenes Gebot {bid_pct:+.1f}% zum MW" if bid_pct is not None else "Eigenes Gebot aktiv"
            recs.append(_rec(
                kind="bid",
                label="GEBOT LÄUFT",
                priority=88,
                row=row,
                action="Gebot und Ablauf beobachten; nur aufgrund neuer Fakten nachbieten.",
                reasons=[bid_reason, *reasons],
                primary_reason="OFFENES GEBOT",
                secondary_reason=trend_label,
                source="Eigenes Gebot",
            ))
            continue

        if signal == "INTERESSANT":
            recs.append(_rec(
                kind="kickbase_buy" if row.get("is_kickbase") else "manager_buy",
                label="TRADING-KANDIDAT",
                priority=82,
                row=row,
                action="Als Trading-Kandidat prüfen. Preis, MW-Dynamik und Wende-Risiko sind die entscheidenden Fakten.",
                reasons=reasons,
                primary_reason="TRADING",
                secondary_reason=trend_label,
            ))
        elif signal == "ABKÜHLEND":
            recs.append(_rec(
                kind="kickbase_buy" if row.get("is_kickbase") else "manager_buy",
                label="ABKÜHLEND",
                priority=68,
                row=row,
                action="Nicht dem bisherigen Anstieg hinterherlaufen; nächste MW-Schritte abwarten.",
                reasons=reasons,
                primary_reason="MW-DYNAMIK",
                secondary_reason=f"WENDE-RISIKO {risk}",
            ))
        elif signal == "TREND DREHT":
            recs.append(_rec(
                kind="kickbase_buy" if row.get("is_kickbase") else "manager_buy",
                label="TREND DREHT",
                priority=74,
                row=row,
                action="Vor einem Kauf erst bestätigen lassen, dass die neue Richtung nicht nur ein einzelner Ausreißer ist.",
                reasons=reasons,
                primary_reason="MW-TREND",
                secondary_reason="RICHTUNGSWECHSEL",
            ))

    for row in squad:
        role = str(row.get("player_role") or row.get("role") or "OFFEN").upper()
        action = str(row.get("facts_action") or row.get("action") or "").upper()
        trend_label, risk, trend_facts = _trend_context(row)
        reasons = list(trend_facts)
        if row.get("pnl") is not None:
            reasons.insert(0, f"Offenes P/L {int(row.get('pnl')):+d} €")

        if role == "TRANSFERLISTE" or action in {"VERKAUF PRÜFEN", "GEWINN ABSICHERN", "VERKAUF BEOBACHTEN", "EXIT BEOBACHTEN"}:
            if action == "GEWINN ABSICHERN":
                label = "GEWINN ABSICHERN"
                action_text = "Der MW steigt noch, verliert aber Tempo bzw. zeigt erhöhtes Wende-Risiko. Verkauf zeitnah prüfen."
                priority = 86
            elif action == "VERKAUF BEOBACHTEN":
                label = "VERKAUF BEOBACHTEN"
                action_text = "Der MW-Trend trägt noch. Verkauf nicht überstürzen, aber Exit weiter beobachten."
                priority = 70
            elif action == "EXIT BEOBACHTEN":
                label = "EXIT BEOBACHTEN"
                action_text = "Investment weiter beobachten; nachlassende Dynamik kann den Exit näher bringen."
                priority = 76
            else:
                label = "VERKAUF PRÜFEN"
                action_text = "Verkauf anhand von P/L und aktuellem MW-Trend prüfen."
                priority = 82
            recs.append(_rec(
                kind="sell",
                label=label,
                priority=priority,
                row=row,
                action=action_text,
                reasons=reasons,
                primary_reason="EIGENER KADER",
                secondary_reason=trend_label,
                source="Eigener Kader",
            ))

    recs.sort(key=lambda rec: (-int(rec.get("priority") or 0), str(rec.get("name") or "").casefold()))
    return recs[:max(1, int(limit))]
