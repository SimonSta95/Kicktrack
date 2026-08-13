from __future__ import annotations

from statistics import median
from typing import Iterable


TARGET_POSITION_DEPTH = {"TW": 2, "ABW": 4, "MF": 4, "ST": 3}
ROLE_SELL_POINTS = {"STAMM": 0.0, "INVEST": 2.0, "OFFEN": 5.0, "TRANSFERLISTE": 10.0}
ROLE_SQUAD_POINTS = {"STAMM": 15.0, "INVEST": 9.0, "OFFEN": 10.0, "TRANSFERLISTE": 2.0}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _score(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def _relative_score(value: float | None, reference: float | None, max_points: float) -> tuple[float, str]:
    if value is None or reference is None or value <= 0 or reference <= 0:
        return max_points * 0.5, "zu wenig Vergleichsdaten"
    ratio = value / reference
    points = max_points * _clamp((ratio - 0.5) / 1.0)
    return points, f"{ratio:.2f}x Positionsmedian"


def _trend_component(player: dict, max_points: float = 50.0) -> tuple[float, str]:
    mv = int(player.get("market_value") or 0)
    if mv <= 0:
        return max_points * 0.5, "kein Marktwert"

    windows = []
    # Longer windows carry more weight and make single-day noise less dominant.
    for key, days, weight in (("d1", 1, 0.15), ("d3", 3, 0.30), ("d7", 7, 0.35), ("d14", 14, 0.20)):
        change = player.get(key)
        if change is None:
            continue
        # Dailyize each window before combining it. Otherwise long windows win
        # purely because they contain more days.
        pct = (float(change) / days) / float(mv) * 100.0
        windows.append((pct, weight, key))
    if not windows:
        return max_points * 0.5, "noch keine Verlaufsdaten"

    weight_sum = sum(weight for _, weight, _ in windows)
    weighted_pct = sum(pct * weight for pct, weight, _ in windows) / weight_sum
    # Daily market-value changes are much smaller than 5%; +/-0.75%/day is
    # already a very strong signal. Add a bounded acceleration adjustment.
    factor = _clamp((weighted_pct + 0.75) / 1.50)
    acceleration = player.get("trend_acceleration")
    acceleration_pct = (float(acceleration) / mv * 100.0) if acceleration is not None else 0.0
    factor = _clamp(factor + max(-0.10, min(0.10, acceleration_pct * 0.20)))
    return max_points * factor, f"MW-Momentum {weighted_pct:+.2f}%/Tag · Beschl. {acceleration_pct:+.2f}%/Tag"


def _momentum_consistency(player: dict, max_points: float = 20.0) -> tuple[float, str]:
    values = [player.get("d1"), player.get("d3"), player.get("d7"), player.get("d14")]
    available = [float(v) for v in values if v is not None]
    if not available:
        return max_points * 0.5, "noch keine Verlaufsdaten"
    positive = sum(1 for value in available if value > 0)
    negative = sum(1 for value in available if value < 0)
    factor = (positive + 0.5 * (len(available) - positive - negative)) / len(available)
    return max_points * factor, f"{positive}/{len(available)} Zeitfenstern positiv"


def _roi_component(player: dict, max_points: float = 30.0) -> tuple[float, str]:
    roi = player.get("roi")
    if roi is None:
        return max_points * 0.5, "kein belastbarer Einstiegspreis"
    roi = float(roi)
    # -10% -> 0, 0% -> half, +10% -> full.
    factor = _clamp((roi + 10.0) / 20.0)
    return max_points * factor, f"Rendite seit Einstieg {roi:+.1f}%"


def _position_importance(position: str, squad: list[dict], max_points: float = 25.0) -> tuple[float, str]:
    target = TARGET_POSITION_DEPTH.get(position)
    if not target:
        return max_points * 0.5, "Position ohne Zielbreite"
    count = sum(1 for player in squad if str(player.get("position") or "") == position)
    # Thin positions are more sensitive to a sale. At/above target depth a base
    # importance remains because quality still matters.
    if count <= 1:
        factor = 1.0
    else:
        factor = 1.0 - 0.70 * _clamp((count - 1) / max(1.0, float(target - 1)))
    return max_points * factor, f"{count} eigene {position} · Zielbreite {target}"


def _replaceability(position: str, quality_ratio: float | None, squad: list[dict], max_points: float = 30.0) -> tuple[float, str]:
    target = TARGET_POSITION_DEPTH.get(position, 3)
    count = sum(1 for player in squad if str(player.get("position") or "") == position)
    depth_factor = _clamp((count - target + 1) / 2.0)  # overstaffed -> easier to replace
    if quality_ratio is None:
        quality_factor = 0.5
    else:
        # 0.5x median -> highly replaceable, 1.5x -> hard to replace.
        quality_factor = 1.0 - _clamp((quality_ratio - 0.5) / 1.0)
    points = max_points * (0.55 * depth_factor + 0.45 * quality_factor)
    return points, f"Positionsbreite {count}/{target} · relative Qualität {quality_ratio:.2f}x" if quality_ratio is not None else f"Positionsbreite {count}/{target}"


def _capital_release(market_value: int, squad_median: float | None, max_points: float = 20.0) -> tuple[float, str]:
    if market_value <= 0 or not squad_median or squad_median <= 0:
        return max_points * 0.5, "zu wenig Wertdaten"
    ratio = market_value / squad_median
    points = max_points * _clamp((ratio - 0.5) / 1.0)
    return points, f"setzt {ratio:.2f}x des Kader-Medianwerts frei"


def _exit_momentum(player: dict, max_points: float = 18.0) -> tuple[float, str]:
    """Score deteriorating market-value momentum as a reason to exit.

    We deliberately use several windows so one red day does not immediately
    become a sell signal. Falling short/medium windows and negative acceleration
    matter most.
    """
    windows = [("d1", 1, 0.20), ("d3", 3, 0.35), ("d7", 7, 0.30), ("d14", 14, 0.15)]
    observed = []
    for key, days, weight in windows:
        value = player.get(key)
        if value is None:
            continue
        observed.append((float(value) / days, weight, key))
    if not observed:
        return max_points * 0.25, "noch keine belastbaren MW-Fenster"

    weight_sum = sum(weight for _, weight, _ in observed)
    negative_share = sum(weight for daily, weight, _ in observed if daily < 0) / weight_sum
    points = max_points * negative_share
    accel = player.get("trend_acceleration")
    if accel is not None and float(accel) < 0:
        points = min(max_points, points + max_points * 0.15)
    negatives = sum(1 for daily, _, _ in observed if daily < 0)
    return points, f"{negatives}/{len(observed)} MW-Fenster negativ" + (" · Trend bremst" if accel is not None and float(accel) < 0 else "")


def _profit_capture(player: dict, max_points: float = 10.0) -> tuple[float, str]:
    roi = player.get("roi")
    if roi is None:
        return max_points * 0.25, "kein belastbarer Einstiegspreis"
    roi = float(roi)
    if roi <= 0:
        # A loss alone is not a reason to sell; avoid classic loss-aversion logic.
        return 0.0, f"Rendite {roi:+.1f}%"
    points = max_points * _clamp(roi / 15.0)
    return points, f"Buchgewinn {roi:+.1f}%"


def _market_replacement(
    player: dict,
    market_rows: list[dict],
    available_budget: int | None,
    max_points: float = 14.0,
) -> tuple[float, str, dict | None]:
    position = str(player.get("position") or "")
    sale_value = int(player.get("market_value") or 0)
    budget_after_sale = int(available_budget or 0) + sale_value
    candidates = []
    for row in market_rows:
        if str(row.get("position") or "") != position:
            continue
        price = int(row.get("price") or 0)
        if price <= 0 or price > budget_after_sale:
            continue
        signal = str(row.get("signal") or "")
        replacement = row.get("replacement_value")
        if signal not in {"KAUFEN", "TOP-CHANCE", "KADER-UPGRADE", "INVEST-CHANCE"} and not (replacement is not None and float(replacement) > 0):
            continue
        candidates.append(row)
    if not candidates:
        return 0.0, "keine klare finanzierbare Alternative am Markt", None

    def rank(row: dict):
        repl = float(row.get("replacement_value") or 0)
        fit = float(row.get("squad_fit_score") or 0)
        invest = float(row.get("investment_score") or 0)
        return (repl, fit, invest)

    best = max(candidates, key=rank)
    repl = float(best.get("replacement_value") or 0)
    fit = float(best.get("squad_fit_score") or 0)
    factor = 0.55 + 0.45 * _clamp((fit - 50.0) / 30.0)
    if repl > 0:
        factor = min(1.0, factor + 0.15)
    points = max_points * factor
    name = best.get("full_name") or best.get("name") or "Alternative"
    price = int(best.get("price") or 0)
    return points, f"{name} für {price/1_000_000:.2f} Mio. finanzierbar", best


def _sell_verdict(total: int, *, role: str, exit_points: float, replacement: dict | None) -> str:
    # Strong wording requires a real contextual reason. An explicit transfer-list
    # role plus clearly negative momentum is itself a valid contextual trigger.
    hard_trigger = role == "TRANSFERLISTE" or exit_points >= 15.0 or replacement is not None
    if total >= 82 and hard_trigger:
        return "JETZT VERKAUFEN"
    if total >= 64:
        return "EHER VERKAUFEN"
    if role == "TRANSFERLISTE" and exit_points >= 12.5:
        return "EHER VERKAUFEN"
    if total >= 52:
        return "VERKAUF PRÜFEN"
    return "HALTEN"


def _simple_action(row: dict, squad_score: int, trading_score: int, sell_score: int) -> str:
    role = str(row.get("player_role") or row.get("role") or "").upper()
    d1 = row.get("d1")
    rising = d1 is not None and float(d1) > 0
    if role == "TRANSFERLISTE":
        return "VERKAUF WARTEN" if trading_score >= 65 and rising else "VERKAUFEN"
    if squad_score >= 70:
        return "HALTEN"
    if trading_score >= 70:
        return "INVEST HALTEN"
    if sell_score >= 60:
        return "VERKAUFEN"
    return "HALTEN"


def _signal(squad_score: int, investment_score: int, sell_score: int) -> str:
    if sell_score >= 75:
        return "VERKAUFSKANDIDAT"
    if squad_score >= 80 and sell_score < 40:
        return "KERN-SPIELER"
    if investment_score >= 75 and sell_score < 55:
        return "INVESTMENT HALTEN"
    if squad_score < 50 and sell_score >= 60:
        return "UPGRADE-KANDIDAT"
    if squad_score >= 65:
        return "HALTEN"
    return "BEOBACHTEN"


def enrich_squad_entries(
    players: Iterable[dict],
    *,
    points_are_current: bool = True,
    market_rows: Iterable[dict] | None = None,
    available_budget: int | None = None,
) -> list[dict]:
    """Add independent sporting, trading and sell-decision scores.

    Sporting value does not use market momentum. Trading does not use historical
    ROI as a predictor. Selling is based on expendability, an actual replacement
    opportunity, exit momentum and the user's explicit player role.
    """
    rows = [dict(player) for player in players]
    market_context = [dict(row) for row in (market_rows or [])]
    if not rows:
        return rows

    position_values: dict[str, list[float]] = {}
    for row in rows:
        pos = str(row.get("position") or "")
        if points_are_current and row.get("average_points") is not None:
            value = float(row.get("average_points") or 0)
        else:
            value = float(row.get("market_value") or 0)
        if pos and value > 0:
            position_values.setdefault(pos, []).append(value)
    position_medians = {pos: float(median(values)) for pos, values in position_values.items() if values}

    for row in rows:
        pos = str(row.get("position") or "")
        role = str(row.get("player_role") or "OFFEN").upper()
        ref = position_medians.get(pos)
        metric_value = (
            float(row.get("average_points") or 0)
            if points_are_current and row.get("average_points") is not None
            else float(row.get("market_value") or 0)
        )

        # SPORTING VALUE: quality 60, positional importance 25, explicit role 15.
        quality_points, quality_reason = _relative_score(metric_value, ref, 60.0)
        quality_ratio = (metric_value / ref) if ref and metric_value > 0 else None
        position_points, position_reason = _position_importance(pos, rows, 25.0)
        role_points = ROLE_SQUAD_POINTS.get(role, 10.0)
        squad_score = _score(quality_points + position_points + role_points)

        # TRADING SCORE: current performance + independent market momentum.
        # ROI is intentionally context only; a past gain/loss does not predict the next move.
        if points_are_current:
            performance_points, performance_reason = _relative_score(metric_value, ref, 30.0)
            momentum_points, momentum_reason = _trend_component(row, 70.0)
        else:
            performance_points, performance_reason = 0.0, "Preseason: Saisonleistung nicht gewertet"
            momentum_points, momentum_reason = _trend_component(row, 100.0)
        investment_score = _score(performance_points + momentum_points)
        roi = row.get("roi")
        roi_reason = f"Rendite seit Einstieg {float(roi):+.1f}% (nur Kontext)" if roi is not None else "kein belastbarer Einstiegspreis"

        # SELL DECISION: one single model, no second layer that reuses the first score.
        sporting_expendability = 30.0 * (1.0 - squad_score / 100.0)
        exit_points, exit_reason = _exit_momentum(row, 25.0)
        market_points, market_reason, market_replacement = _market_replacement(
            row, market_context, available_budget, 35.0
        )
        role_sell_points = ROLE_SELL_POINTS.get(role, 5.0)
        sell_score = _score(sporting_expendability + exit_points + market_points + role_sell_points)
        sell_verdict = _sell_verdict(
            sell_score, role=role, exit_points=exit_points, replacement=market_replacement
        )

        metric_name = "Ø Punkte" if points_are_current else "Marktwert (Preseason)"
        row["squad_value_score"] = squad_score
        row["investment_score"] = investment_score  # legacy name; semantically Trading Score
        row["trading_score"] = investment_score
        row["sell_score"] = sell_score
        row["sell_decision_score"] = sell_score
        row["sell_verdict"] = sell_verdict
        row["squad_signal"] = _signal(squad_score, investment_score, sell_score)
        row["kader_label"] = "STARK" if squad_score >= 80 else "GUT" if squad_score >= 65 else "NEUTRAL" if squad_score >= 45 else "SCHWACH"
        row["trade_label"] = "STARK" if investment_score >= 80 else "GUT" if investment_score >= 65 else "NEUTRAL" if investment_score >= 45 else "SCHWACH"
        row["action"] = _simple_action(row, squad_score, investment_score, sell_score)
        row["squad_score_breakdown"] = {
            "positionsrelevanz": round(position_points, 1),
            "qualitaet": round(quality_points, 1),
            "rolle": round(role_points, 1),
            "trend": 0.0,
        }
        row["own_investment_breakdown"] = {
            "performance": round(performance_points, 1),
            "marktwerttrend": round(momentum_points, 1),
            "rendite": 0.0,
            "momentum": round(momentum_points, 1),
        }
        row["sell_breakdown"] = {
            "sportliche_entbehrlichkeit": round(sporting_expendability, 1),
            "mw_exit_signal": round(exit_points, 1),
            "markt_alternative": round(market_points, 1),
            "eigene_rolle": round(role_sell_points, 1),
            # legacy keys retained for UI compatibility
            "ersetzbarkeit": round(sporting_expendability, 1),
            "kapitalfreisetzung": 0.0,
            "schwacher_kader_fit": round(sporting_expendability, 1),
            "schwaches_investment": 0.0,
        }
        row["sell_decision_breakdown"] = {
            "sportliche_entbehrlichkeit": round(sporting_expendability, 1),
            "mw_exit_signal": round(exit_points, 1),
            "markt_alternative": round(market_points, 1),
            "eigene_rolle": round(role_sell_points, 1),
            "basis": round(sporting_expendability + role_sell_points, 1),
            "gewinnmitnahme": 0.0,
        }
        row["sell_replacement_player"] = market_replacement
        row["sell_decision_text"] = (
            f"VERKAUFSENTSCHEIDUNG · {sell_verdict}\n"
            f"- Sportliche Entbehrlichkeit: {sporting_expendability:.1f}/30\n"
            f"- MW-Exit-Signal: {exit_points:.1f}/25 ({exit_reason})\n"
            f"- Markt-Alternative: {market_points:.1f}/35 ({market_reason})\n"
            f"- Eigene Rolle: {role_sell_points:.1f}/10 ({role})\n"
            f"- ROI: {roi_reason}\n\n"
            f"→ {sell_verdict}"
        )

        if sell_verdict in {"JETZT VERKAUFEN", "EHER VERKAUFEN"}:
            row["squad_signal"] = sell_verdict
        elif sell_verdict == "VERKAUF PRÜFEN" and row["squad_signal"] == "BEOBACHTEN":
            row["squad_signal"] = sell_verdict

        row["squad_analysis_text"] = (
            f"KADERWERT {squad_score}/100\n"
            f"- Qualität {quality_points:.1f}/60 ({metric_name}: {quality_reason})\n"
            f"- Positionsrelevanz {position_points:.1f}/25 ({position_reason})\n"
            f"- Eigene Rolle {role_points:.1f}/15 ({role})\n\n"
            f"TRADING {investment_score}/100\n"
            + (f"- Performance {performance_points:.1f}/30 ({performance_reason})\n" if points_are_current else "- Performance: Preseason nicht gewertet\n")
            + f"- MW-Momentum {momentum_points:.1f}/{70 if points_are_current else 100} ({momentum_reason})\n"
            + f"- ROI: {roi_reason}\n\n"
            + f"Signal: {row['squad_signal']}\n\n"
            + row["sell_decision_text"]
        )

    return rows
