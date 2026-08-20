from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .squad_rules import MAX_SQUAD_SIZE, active_bid_count, squad_capacity


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _listing_age_days(row: dict) -> float | None:
    dt = _parse_dt(row.get('listed_at'))
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


def _manager_context(managers: Iterable[dict], seller_id: str | None, own_manager_id: str | None) -> tuple[str | None, int | None, int | None]:
    seller = None
    own = None
    for manager in managers:
        mid = str(manager.get('manager_id') or '')
        if seller_id and mid == str(seller_id):
            seller = manager
        if own_manager_id and mid == str(own_manager_id):
            own = manager
    seller_place = int(seller.get('place')) if seller and seller.get('place') is not None else None
    own_place = int(own.get('place')) if own and own.get('place') is not None else None
    seller_name = str(seller.get('name') or '') if seller else None
    return seller_name, seller_place, own_place



def _market_purpose(row: dict) -> tuple[str, str | None]:
    """User-facing purpose from the shared portfolio model."""
    role = str(row.get("portfolio_role") or "").upper()
    if role == "KADERZIEL":
        return "KADERZIEL", "STARTKADER"
    if role == "INVEST":
        return "INVEST", "KAPITALAUFBAU"
    if role == "BEOBACHTEN":
        return "BEOBACHTEN", "TRADING"

    investment = int(row.get("investment_score") or 0)
    squad_fit = int(row.get("squad_fit_score") or 0)
    if squad_fit >= 75 and investment >= 75:
        return "KADER-UPGRADE", "INVESTMENT"
    if squad_fit >= 75:
        return "KADER-UPGRADE", None
    if investment >= 75:
        return "INVESTMENT", None
    return "PREIS / OPTION", None

def _sell_purpose(row: dict) -> tuple[str, str | None]:
    breakdown = row.get("sell_decision_breakdown") or {}
    portfolio_role = str(row.get("portfolio_role") or "").upper()
    if portfolio_role == "ROTATE/SELL":
        return "KAPITAL ROTIEREN", "KADERPLATZ FREIMACHEN"
    if breakdown.get("market_replacement"):
        return "KADERUMBAU", "VERKAUF ZUR FINANZIERUNG"
    role = str(row.get("player_role") or row.get("role") or "").upper()
    d1 = row.get("d1")
    d7 = row.get("d7")
    falling = (d1 is not None and float(d1) < 0) or (d7 is not None and float(d7) < 0)
    if role == "TRANSFERLISTE":
        return "VERKAUF", "BUDGET FREIMACHEN"
    if falling:
        return "RISIKO REDUZIEREN", "KAPITAL ROTIEREN"
    return "VERKAUF PRÜFEN", "KAPITAL EFFIZIENTER NUTZEN"



def _market_secondary_tags(row: dict, primary_reason: str, secondary_reason: str | None) -> list[str]:
    """Compact, user-facing reasons that explain *why* the Coach cares.

    These are deliberately not raw score components. They are short decision
    signals that can be scanned in the Coach card.
    """
    tags: list[str] = []

    def add(value: str | None) -> None:
        value = str(value or "").strip()
        if value and value != primary_reason and value not in tags:
            tags.append(value)

    add(secondary_reason)

    investment = int(row.get("investment_score") or 0)
    squad_fit = int(row.get("squad_fit_score") or 0)
    d1 = row.get("d1")
    d7 = row.get("d7")
    trend_positive = (d1 is not None and float(d1) > 0) or (d7 is not None and float(d7) > 0) or row.get("market_trend") == 1
    trend_negative = (d1 is not None and float(d1) < 0) or (d7 is not None and float(d7) < 0) or row.get("market_trend") == 2
    minimum_bid = int(row.get("minimum_bid") or row.get("market_value") or 0)
    max_bid = int(row.get("max_bid") or 0)

    if squad_fit >= 75 and primary_reason != "KADER-UPGRADE":
        add("KADER-UPGRADE")
    elif row.get("replacement_reason"):
        add("BESSERE KADEROPTION")

    if investment >= 75 and primary_reason != "INVESTMENT":
        add("INVESTMENT")

    if trend_positive:
        add("MW-TREND POSITIV")
    elif trend_negative:
        add("MW-TREND NEGATIV")

    if max_bid and minimum_bid and minimum_bid <= max_bid:
        add("INNERHALB MAX-BID")

    value_score = row.get("value_score")
    if value_score is not None and int(value_score) >= 80:
        add("TOP PREIS-LEISTUNG")
    return tags[:4]


def _sell_secondary_tags(row: dict, primary_reason: str, secondary_reason: str | None) -> list[str]:
    tags: list[str] = []

    def add(value: str | None) -> None:
        value = str(value or "").strip()
        if value and value != primary_reason and value not in tags:
            tags.append(value)

    add(secondary_reason)
    breakdown = row.get("sell_decision_breakdown") or {}
    pnl = int(row.get("pnl") or 0)
    d1 = row.get("d1")
    d7 = row.get("d7")
    falling = (d1 is not None and float(d1) < 0) or (d7 is not None and float(d7) < 0)
    role = str(row.get("player_role") or row.get("role") or "").upper()

    if breakdown.get("market_replacement"):
        add("ERSATZ VERFÜGBAR")
    if pnl > 0:
        add("BUCHGEWINN")
    if falling:
        add("MW-TREND NEGATIV")
    if role == "TRANSFERLISTE":
        add("TRANSFERLISTE")
    return tags[:3]

def _manager_offer_advice(row: dict, managers: list[dict], own_manager_id: str | None) -> dict:
    listed_price = int(row.get('price') or 0)
    mv = int(row.get('market_value') or 0)
    minimum_bid = int(row.get('minimum_bid') or mv or 0)
    effective_price = max(listed_price, minimum_bid) if listed_price else minimum_bid
    max_bid = int(row.get('max_bid') or 0)
    listed_delta_pct = ((listed_price - mv) / mv * 100.0) if listed_price > 0 and mv > 0 else None
    age = _listing_age_days(row)
    d1 = row.get('d1')
    d7 = row.get('d7')
    momentum_positive = (d1 is not None and float(d1) > 0) or (d7 is not None and float(d7) > 0) or row.get('market_trend') == 1
    seller_name, seller_place, own_place = _manager_context(managers, row.get('seller_id'), own_manager_id)
    direct_rival = seller_place is not None and own_place is not None and abs(seller_place - own_place) <= 2

    reasons: list[str] = []
    if listed_delta_pct is not None:
        reasons.append(f"Listing {listed_delta_pct:+.1f}% zum aktuellen MW")
    if age is not None:
        reasons.append(f"seit {age:.1f} Tagen auf dem Markt")
    if momentum_positive:
        reasons.append("Marktwert-Momentum positiv")
    if direct_rival:
        reasons.append("Verkäufer ist direkter Tabellenkonkurrent")
    if listed_price and minimum_bid and listed_price < minimum_bid:
        reasons.append("sichtbarer Listingpreis liegt unter dem zulässigen Mindestgebot")

    # Underpay is disabled in this league: even stale manager listings cannot be
    # acquired below the current MW. Therefore they are never Lowball-Chancen.
    if max_bid and minimum_bid and max_bid < minimum_bid:
        label = "NICHT SINNVOLL"
        priority = 24
        planability = "GERING"
        action = f"Mindestgebot {minimum_bid:,.0f} € liegt über deinem Max-Bid {max_bid:,.0f} €. Passen.".replace(',', '.')
    elif max_bid and effective_price > max_bid:
        over = (effective_price - max_bid) / max_bid * 100.0 if max_bid else 0.0
        label = "NUR BEI PREISNACHLASS" if over <= 20 else "NICHT SINNVOLL"
        priority = 50 if over <= 20 else 25
        planability = "GERING"
        action = f"Nicht hinterherlaufen; mindestens {minimum_bid:,.0f} €, maximal {max_bid:,.0f} € sinnvoll.".replace(',', '.')
        reasons.append(f"ausführbarer Preis {over:.1f}% über deinem Max-Bid")
    elif max_bid:
        label = "MANAGER-DEAL PRÜFEN"
        priority = 66
        planability = "MITTEL"
        action = f"Mindestens {minimum_bid:,.0f} € bieten; deine Obergrenze liegt bei etwa {max_bid:,.0f} €. Manager muss aktiv zustimmen.".replace(',', '.')
        if listed_price < minimum_bid:
            action = f"Listing ist veraltet. Unter {minimum_bid:,.0f} € ist der Deal nicht ausführbar; maximal etwa {max_bid:,.0f} € sinnvoll.".replace(',', '.')
    else:
        label = "VERHANDELN"
        priority = 46
        planability = "GERING"
        action = f"Mindestens aktuellen MW von {minimum_bid:,.0f} € bieten; ohne belastbare Obergrenze nicht fest einplanen.".replace(',', '.')

    if direct_rival and label in {"MANAGER-DEAL PRÜFEN", "VERHANDELN"}:
        priority -= 6
        action += " Kapital fließt an einen direkten Konkurrenten."

    primary_reason, secondary_reason = _market_purpose(row)
    return {
        "kind": "manager_buy",
        "label": label,
        "primary_reason": primary_reason,
        "secondary_reason": secondary_reason,
        "secondary_tags": _market_secondary_tags(row, primary_reason, secondary_reason),
        "priority": priority,
        "planability": planability,
        "action": action,
        "reasons": reasons,
        "listing_age_days": age,
        "seller_name": seller_name or row.get('seller_name') or "Manager",
    }


def _kickbase_offer_advice(row: dict) -> dict | None:
    role = str(row.get("portfolio_role") or "").upper()
    if role == "PASS":
        return None

    role_mapping = {
        "KADERZIEL": ("KADERZIEL", 92),
        "INVEST": ("INVEST", 86),
        "BEOBACHTEN": ("BEOBACHTEN", 60),
    }
    signal = str(row.get('signal') or '')
    if role in role_mapping:
        label, priority = role_mapping[role]
    else:
        if signal not in {"KAUFEN", "TOP-CHANCE", "KADER-UPGRADE", "INVEST-CHANCE", "KAUFPRÜFUNG"}:
            return None
        mapping = {
            "KAUFEN": ("KAUFEN", 82),
            "TOP-CHANCE": ("TOP-CHANCE", 84),
            "KADER-UPGRADE": ("KADER-UPGRADE", 76),
            "INVEST-CHANCE": ("INVEST", 80),
            "KAUFPRÜFUNG": ("KAUF PRÜFEN", 58),
        }
        label, priority = mapping[signal]

    max_bid = int(row.get('max_bid') or 0)
    price = int(row.get('effective_price') or row.get('price') or 0)
    minimum_bid = int(row.get('minimum_bid') or row.get('market_value') or 0)
    expected_profit = int(row.get("expected_trade_profit") or 0)
    expected_return = float(row.get("expected_capital_return_pct") or 0.0)
    projected = row.get("projected_deadline_balance")
    reserve = int(row.get("safety_reserve") or 0)
    days = float(row.get("days_to_deadline") or 0.0)

    reasons: list[str] = []
    if role in {"INVEST", "BEOBACHTEN"}:
        reasons.append(
            f"Trade-Schätzung {expected_profit:+,.0f} € / {expected_return:+.1f}% bis Exit".replace(',', '.')
        )
    elif role == "KADERZIEL":
        reasons.append("passt als Ziel für den Startkader")
    reasons.append(f"noch {days:.1f} Tage bis Freitag 20:00")

    if row.get("portfolio_block_reason"):
        return None
    if max_bid and minimum_bid and max_bid < minimum_bid:
        return None

    if max_bid:
        action = f"Gebotskorridor ca. {minimum_bid:,.0f}–{max_bid:,.0f} €.".replace(',', '.')
    else:
        action = f"Mindestens aktuellen MW von {minimum_bid:,.0f} € bieten; Preisgrenze prüfen.".replace(',', '.')

    if role == "INVEST":
        action += " Kaufen zum Kapitalaufbau; Exit neu bewerten, sobald das MW-Momentum bricht."
    elif role == "KADERZIEL":
        action += " Für den Startkader einplanen; Trading-Upside ist Bonus, nicht Voraussetzung."
    elif role == "BEOBACHTEN":
        action += " Noch kein Kaufzwang; Momentum weiter beobachten."

    primary_reason, secondary_reason = _market_purpose(row)
    return {
        "kind": "kickbase_buy",
        "label": label,
        "primary_reason": primary_reason,
        "secondary_reason": secondary_reason,
        "secondary_tags": _market_secondary_tags(row, primary_reason, secondary_reason),
        "priority": priority,
        "planability": "HOCH",
        "action": action,
        "reasons": reasons[:3],
    }

def _active_bid_advice(row: dict) -> dict | None:
    """Coach advice for the user's own active bid on a market player."""
    own_bid = int(row.get("own_bid") or 0)
    if own_bid <= 0:
        return None

    mv = int(row.get("market_value") or 0)
    minimum_bid = int(row.get("minimum_bid") or mv or 0)
    max_bid = int(row.get("max_bid") or 0)
    expires = str(row.get("expiry_text") or row.get("expires_text") or "").strip()
    reasons: list[str] = []

    if mv > 0:
        diff = own_bid - mv
        reasons.append(f"Gebot {diff:+,.0f} € zum aktuellen MW".replace(',', '.'))
    if max_bid > 0:
        reasons.append(f"Analytische Obergrenze {max_bid:,.0f} €".replace(',', '.'))
    if expires and expires != "–":
        reasons.append(f"Ablauf {expires}")

    if minimum_bid > 0 and own_bid < minimum_bid:
        gap = minimum_bid - own_bid
        return {
            "kind": "bid",
            "label": "GEBOT ANPASSEN",
            "primary_reason": "OFFENES GEBOT",
            "secondary_reason": "MINDESTGEBOT GESTIEGEN",
            "secondary_tags": ["GEBOT AKTIV", "PREIS PRÜFEN"],
            "priority": 97,
            "planability": "HOCH",
            "action": f"Dein Gebot liegt {gap:,.0f} € unter dem aktuellen Mindestgebot. Vor Ablauf erhöhen oder bewusst aussteigen.".replace(',', '.'),
            "reasons": reasons[:3],
        }

    if max_bid > 0 and own_bid > max_bid:
        over = own_bid - max_bid
        return {
            "kind": "bid",
            "label": "GEBOT PRÜFEN",
            "primary_reason": "RISIKOLIMIT",
            "secondary_reason": "ÜBER MAX-BID",
            "secondary_tags": ["GEBOT AKTIV", "LIMIT ÜBERSCHRITTEN"],
            "priority": 94,
            "planability": "HOCH",
            "action": f"Dein Gebot liegt {over:,.0f} € über unserer aktuellen Obergrenze. Wenn möglich Gebot korrigieren oder das zusätzliche Risiko bewusst akzeptieren.".replace(',', '.'),
            "reasons": reasons[:3],
        }

    role = str(row.get("portfolio_role") or "").upper()
    investment = int(row.get("investment_score") or 0)
    squad_fit = int(row.get("squad_fit_score") or 0)
    if role in {"KADERZIEL", "INVEST"} or max(investment, squad_fit) >= 75:
        return {
            "kind": "bid",
            "label": "GEBOT LÄUFT",
            "primary_reason": "OFFENES GEBOT",
            "secondary_reason": "INNERHALB LIMIT",
            "secondary_tags": ["GEBOT AKTIV", "NICHT NACHBIETEN"],
            "priority": 76,
            "planability": "HOCH",
            "action": "Gebot liegt aktuell innerhalb unserer Preisgrenze. Nicht unnötig nachbieten; nur Marktwert und Ablauf im Blick behalten.",
            "reasons": reasons[:3],
        }
    return None


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
    managers_list = [dict(m) for m in (managers or [])]
    market_rows = [dict(r) for r in market_rows]
    squad_rows = [dict(r) for r in squad_rows]
    capacity = squad_capacity(squad_rows)
    open_bids = active_bid_count(market_rows)
    recs: list[dict] = []

    explicit_sale_rows = [
        row for row in squad_rows
        if str(row.get("player_role") or row.get("portfolio_role") or row.get("action") or "").upper()
        in {"TRANSFERLISTE", "ROTATE/SELL", "VERKAUFEN", "VERKAUF WARTEN"}
    ]
    sale_name = str((explicit_sale_rows[0] if explicit_sale_rows else {}).get("name") or "").strip()

    if capacity.is_full:
        recs.append({
            "kind": "warning",
            "label": "KADER VOLL",
            "primary_reason": "18/18 KADERPLÄTZE",
            "secondary_reason": "KAUF BRAUCHT VERKAUF",
            "secondary_tags": ["KADER 18/18", "KEIN FREIER SLOT"],
            "priority": 96,
            "planability": "HOCH",
            "action": (f"Vor einem weiteren Kauf zuerst einen Kaderplatz freimachen – aktuell bietet sich {sale_name} als bereits markierter Verkauf an." if sale_name else "Vor einem weiteren Kauf zuerst einen Kaderplatz freimachen. Marktchancen nur als Upgrade zusammen mit einem Verkauf betrachten."),
            "reasons": ["Kickbase-Kadergrenze: maximal 18 Spieler"],
            "player_id": None,
            "name": "Kaderplätze",
            "club": "",
            "position": "",
            "price": 0,
            "market_value": 0,
            "source": "Kader",
            "confidence": "HOCH",
            "horizon": "JETZT",
            "raw": {},
        })
    elif open_bids > capacity.free:
        recs.append({
            "kind": "warning",
            "label": "KADERPLÄTZE PRÜFEN",
            "primary_reason": f"{capacity.current}/{MAX_SQUAD_SIZE} SPIELER",
            "secondary_reason": f"{open_bids} AKTIVE GEBOTE",
            "secondary_tags": [f"{capacity.free} FREIE PLÄTZE", "GEBOTE KÖNNEN KOLLIDIEREN"],
            "priority": 93,
            "planability": "HOCH",
            "action": f"Du hast {capacity.free} freie Kaderplätze, aber {open_bids} aktive Gebote. Nicht alle Zugänge können ohne zusätzlichen Verkauf gleichzeitig in den Kader.",
            "reasons": ["Kickbase-Kadergrenze: maximal 18 Spieler"],
            "player_id": None,
            "name": "Kaderplätze",
            "club": "",
            "position": "",
            "price": 0,
            "market_value": 0,
            "source": "Kader",
            "confidence": "HOCH",
            "horizon": "JETZT",
            "raw": {},
        })

    for raw in market_rows:
        row = dict(raw)
        bid_advice = _active_bid_advice(row)
        if bid_advice:
            if capacity.is_full:
                bid_advice = dict(bid_advice)
                bid_advice["label"] = "GEBOT + VERKAUF NÖTIG"
                bid_advice["primary_reason"] = "KADER 18/18"
                bid_advice["secondary_reason"] = "KADERPLATZ FREIMACHEN"
                bid_advice["secondary_tags"] = list(dict.fromkeys(["KADER VOLL", *(bid_advice.get("secondary_tags") or [])]))
                bid_advice["priority"] = max(90, int(bid_advice.get("priority") or 0))
                bid_advice["action"] = ((bid_advice.get("action") or "") + (f" Vor Zuschlag {sale_name} verkaufen oder einen anderen Kaderplatz freimachen." if sale_name else " Vor Zuschlag einen Kaderplatz freimachen.")).strip()
            recs.append({
                **bid_advice,
                "player_id": row.get('player_id'),
                "name": row.get('full_name') or row.get('name') or 'Unbekannter Spieler',
                "club": row.get('club') or '',
                "position": row.get('position') or '',
                "price": int(row.get('price') or 0),
                "market_value": int(row.get('market_value') or 0),
                "max_bid": int(row.get('max_bid') or 0),
                "own_bid": int(row.get('own_bid') or 0),
                "source": "Eigenes Gebot",
                "confidence": row.get('confidence_label') or 'MITTEL',
                "horizon": row.get('investment_horizon') or '',
                "raw": row,
            })
        if str(row.get("portfolio_role") or "").upper() == "PASS":
            continue
        if row.get('is_kickbase'):
            advice = _kickbase_offer_advice(row)
        else:
            advice = _manager_offer_advice(row, managers_list, own_manager_id)
            # Ordinary manager listings need a materially strong reason to enter
            # the Coach at all. A price merely being inside Max-Bid is not enough.
            # This keeps the Coach focused on decisions instead of mirroring the
            # manager side of the transfer market.
            investment = int(row.get('investment_score') or 0)
            squad_fit = int(row.get('squad_fit_score') or 0)
            if advice['label'] == 'VERHANDELN' and max(investment, squad_fit) < 68:
                continue
            if advice['label'] == 'MANAGER-DEAL PRÜFEN' and max(investment, squad_fit) < 70:
                continue
        if not advice:
            continue
        if capacity.is_full:
            advice = dict(advice)
            original_label = str(advice.get("label") or "")
            if original_label not in {"PASS", "PASSEN"}:
                advice["label"] = "UPGRADE + VERKAUF"
                advice["primary_reason"] = "KADER 18/18"
                advice["secondary_reason"] = "NUR MIT ABGANG"
                advice["secondary_tags"] = list(dict.fromkeys(["KADER VOLL", *(advice.get("secondary_tags") or [])]))
                advice["action"] = ((advice.get("action") or "") + (f" Kauf nur zusammen mit Verkauf von {sale_name} oder einem anderen Kaderspieler einplanen." if sale_name else " Kauf nur zusammen mit einem Kaderverkauf einplanen.")).strip()
        recs.append({
            **advice,
            "player_id": row.get('player_id'),
            "name": row.get('full_name') or row.get('name') or 'Unbekannter Spieler',
            "club": row.get('club') or '',
            "position": row.get('position') or '',
            "price": int(row.get('price') or 0),
            "market_value": int(row.get('market_value') or 0),
            "max_bid": int(row.get('max_bid') or 0),
            "source": "Kickbase" if row.get('is_kickbase') else str(row.get('seller_name') or 'Manager'),
            "confidence": row.get('confidence_label') or 'GERING',
            "horizon": row.get('investment_horizon') or '',
            "raw": row,
        })

    own_context_recs: list[dict] = []
    for raw in squad_rows:
        row = dict(raw)
        portfolio_role = str(row.get("portfolio_role") or "")
        verdict = str(row.get('sell_verdict') or '')

        action_label = str(row.get("action") or "")
        if action_label in {"VERKAUFEN", "VERKAUF WARTEN"} or portfolio_role == "ROTATE/SELL" or verdict in {"VERKAUF PRÜFEN", "EHER VERKAUFEN", "JETZT VERKAUFEN"}:
            label = "VERKAUF WARTEN" if action_label == "VERKAUF WARTEN" else "VERKAUFEN"
            priority = 72 if label == "VERKAUF WARTEN" else 88
            reasons = []
            pnl = row.get('pnl')
            if pnl is not None:
                reasons.append(f"Buch-P/L {int(pnl):+,.0f} €".replace(',', '.'))
            if row.get('d1') is not None:
                reasons.append(f"24h MW {int(row.get('d1') or 0):+,.0f} €".replace(',', '.'))
            primary_reason, secondary_reason = _sell_purpose(row)
            recs.append({
                "kind": "sell",
                "label": label,
                "primary_reason": primary_reason,
                "secondary_reason": secondary_reason,
                "secondary_tags": _sell_secondary_tags(row, primary_reason, secondary_reason),
                "priority": priority,
                "planability": "HOCH",
                "action": "Verkauf timen: bei starkem MW-Momentum warten, sonst Kapital für Trades oder Startkader freimachen.",
                "reasons": reasons[:3],
                "player_id": row.get('player_id'),
                "name": row.get('name') or 'Unbekannter Spieler',
                "club": row.get('club') or '',
                "position": row.get('position') or '',
                "price": int(row.get('market_value') or 0),
                "market_value": int(row.get('market_value') or 0),
                "source": "Eigener Kader",
                "confidence": "MITTEL",
                "horizon": "",
                "raw": row,
            })
            continue

        if portfolio_role == "INVEST/TRADE":
            ret = float(row.get("expected_capital_return_pct") or 0.0)
            profit = int(row.get("expected_trade_profit") or 0)
            own_context_recs.append({
                "kind": "squad_hold",
                "label": "INVEST HALTEN",
                "primary_reason": "KAPITALAUFBAU",
                "secondary_reason": "EXIT BEOBACHTEN",
                "secondary_tags": ["EIGENER KADER", "MW-TREND"],
                "priority": min(84, 70 + int(max(0.0, ret) * 2)),
                "planability": "HOCH",
                "action": "Weiter traden, solange das MW-Momentum trägt; nicht automatisch als finalen Starter einplanen.",
                "reasons": [f"Trade-Schätzung {profit:+,.0f} € / {ret:+.1f}%".replace(',', '.')],
                "player_id": row.get('player_id'),
                "name": row.get('name') or 'Unbekannter Spieler',
                "club": row.get('club') or '',
                "position": row.get('position') or '',
                "price": int(row.get('market_value') or 0),
                "market_value": int(row.get('market_value') or 0),
                "source": "Eigener Kader",
                "confidence": "MITTEL",
                "horizon": "SHORT",
                "raw": row,
            })
        elif str(row.get("player_role") or "").upper() == "STAMM":
            own_context_recs.append({
                "kind": "squad_hold",
                "label": "HALTEN",
                "primary_reason": "STARTKADER",
                "secondary_reason": None,
                "secondary_tags": [],
                "priority": 66,
                "planability": "HOCH",
                "action": "Als geplanten Startkader-Spieler halten, solange kein klar besseres Ziel auftaucht.",
                "reasons": [],
                "player_id": row.get('player_id'),
                "name": row.get('name') or 'Unbekannter Spieler',
                "club": row.get('club') or '',
                "position": row.get('position') or '',
                "price": int(row.get('market_value') or 0),
                "market_value": int(row.get('market_value') or 0),
                "source": "Eigener Kader",
                "confidence": "MITTEL",
                "horizon": "LONG",
                "raw": row,
            })

    # Only surface the most useful own-squad hold context; sells remain uncapped.
    own_context_recs.sort(key=lambda r: (-int(r.get("priority") or 0), str(r.get("name") or "").casefold()))
    recs.extend(own_context_recs[:6])

    summary = dict(portfolio_summary or {})
    legacy_negative_budget = portfolio_summary is None and available_budget is not None and int(available_budget) < 0
    if legacy_negative_budget:
        recs.append({
            "kind": "warning",
            "label": "BUDGET ENTLASTEN",
            "primary_reason": "BUDGET FREIMACHEN",
            "secondary_reason": "GEBOTE / VERKÄUFE PRÜFEN",
            "secondary_tags": ["GEBOTE PRÜFEN", "VERKÄUFE PRÜFEN"],
            "priority": 100,
            "planability": "HOCH",
            "action": f"Aktuell fehlen {abs(int(available_budget)):,.0f} €. Verkäufe oder Gebote prüfen.".replace(',', '.'),
            "reasons": ["laufende Gebote binden mehr Kapital als aktuell verfügbar"],
            "player_id": None,
            "name": "Finanzielle Situation",
            "club": "",
            "position": "",
            "price": 0,
            "market_value": 0,
            "source": "Budget",
            "confidence": "HOCH",
            "horizon": "JETZT",
            "raw": {},
        })
    projected = summary.get("projected_balance_before_new_buys")
    days = float(summary.get("days_to_deadline") or 0.0)
    reserve = int(summary.get("safety_reserve") or 0)
    if not legacy_negative_budget and projected is not None and int(projected) < 0:
        recs.append({
            "kind": "warning",
            "label": "FREITAGSSALDO SICHERN",
            "primary_reason": "LIQUIDITÄT",
            "secondary_reason": "20:00 DEADLINE",
            "secondary_tags": ["VERKÄUFE PRIORISIEREN"],
            "priority": 100,
            "planability": "HOCH",
            "action": f"Selbst mit rotierbarem Kaderkapital fehlen prognostiziert {abs(int(projected)):,.0f} € bis Freitag 20:00.".replace(',', '.'),
            "reasons": [f"noch {days:.1f} Tage bis zur Deadline"],
            "player_id": None,
            "name": "Finanzielle Situation",
            "club": "",
            "position": "",
            "price": 0,
            "market_value": 0,
            "source": "Budget",
            "confidence": "HOCH",
            "horizon": "JETZT",
            "raw": {},
        })
    elif not legacy_negative_budget and available_budget is not None and int(available_budget) < 0 and days <= 1.0:
        recs.append({
            "kind": "warning",
            "label": "JETZT INS PLUS",
            "primary_reason": "LIQUIDITÄT",
            "secondary_reason": "20:00 DEADLINE",
            "secondary_tags": ["KEINE NEUEN INVESTS"],
            "priority": 100,
            "planability": "HOCH",
            "action": f"Kontostand {int(available_budget):+,.0f} €. Vor 20:00 muss der Saldo mindestens 0 € erreichen.".replace(',', '.'),
            "reasons": [f"Zielreserve heute {reserve:,.0f} €".replace(',', '.')],
            "player_id": None,
            "name": "Finanzielle Situation",
            "club": "",
            "position": "",
            "price": 0,
            "market_value": 0,
            "source": "Budget",
            "confidence": "HOCH",
            "horizon": "JETZT",
            "raw": {},
        })

    # Coach prioritisation is intentionally much stricter than the market view.
    # The market may contain dozens of valid ideas; the Coach should surface only
    # the handful that deserve attention *now*.
    manager_deals = [r for r in recs if r.get("kind") == "manager_buy"]
    other_primary = [r for r in recs if r.get("kind") != "manager_buy"]

    if legacy_negative_budget:
        urgent = [r for r in other_primary if r.get("kind") in {"warning", "sell"}]
        urgent.sort(key=lambda r: (-int(r.get('priority') or 0), str(r.get('name') or '').casefold()))
        return urgent[:max(1, int(limit))]

    other_primary.sort(key=lambda r: (-int(r.get('priority') or 0), str(r.get('name') or '').casefold()))
    manager_deals.sort(
        key=lambda r: (
            -max(
                int((r.get("raw") or {}).get("investment_score") or 0),
                int((r.get("raw") or {}).get("squad_fit_score") or 0),
            ),
            int(r.get("price") or 0) - int(r.get("market_value") or 0),
            str(r.get('name') or '').casefold(),
        )
    )
    # Hard cap: manager offers are secondary because they still require explicit
    # acceptance by the selling manager. Only the two strongest survive.
    selected_manager = manager_deals[:4]
    selected = other_primary + selected_manager
    selected.sort(key=lambda r: (-int(r.get('priority') or 0), str(r.get('name') or '').casefold()))
    return selected[:max(1, int(limit))]
