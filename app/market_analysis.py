from __future__ import annotations

from itertools import combinations
from statistics import median
from typing import Iterable


POSITION_LABELS = {1: "TW", 2: "ABW", 3: "MF", 4: "ST", "1": "TW", "2": "ABW", "3": "MF", "4": "ST"}
TARGET_POSITION_DEPTH = {"TW": 2, "ABW": 4, "MF": 4, "ST": 3}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _round_score(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def points_per_million(avg_points: int | float | None, price: int | None) -> float | None:
    if avg_points is None or not price or price <= 0:
        return None
    return float(avg_points) / (float(price) / 1_000_000.0)


def _price_score(delta_pct: float | None, max_points: float) -> float:
    """Map price-vs-market-value to a transparent linear score.

    -10% or cheaper => full points, market value => 50%, +15% or more => 0.
    """
    if delta_pct is None:
        return max_points * 0.5
    if delta_pct <= -10.0:
        return max_points
    if delta_pct >= 15.0:
        return 0.0
    # Linear interpolation from -10 -> 100% to +15 -> 0%.
    return max_points * ((15.0 - delta_pct) / 25.0)


def _affordability_score(price: int, available_budget: int | None, max_points: float = 25.0) -> float:
    if price <= 0 or available_budget is None:
        return max_points * 0.5
    available_budget = max(0, int(available_budget))
    if price <= available_budget:
        return max_points
    if available_budget <= 0:
        return 0.0
    # A target at 2x the available cash reaches 0; anything between is linear.
    ratio = available_budget / float(price)
    return max_points * _clamp((ratio - 0.5) / 0.5)


def _position_need_score(position: str, squad: list[dict], max_points: float = 20.0) -> tuple[float, str]:
    """Pure depth need. Quality is evaluated separately to avoid double counting."""
    target = TARGET_POSITION_DEPTH.get(position)
    if not target:
        return max_points * 0.5, "Position ohne Zielbreite"
    count = sum(1 for p in squad if str(p.get("position") or "") == position)
    coverage = _clamp(count / float(target), 0.0, 1.0)
    # Empty = full need; target depth = small 10% residual need for optional upgrades.
    factor = 1.0 - 0.90 * coverage
    return max_points * factor, f"{count} eigene {position} · Zielbreite {target}"


def _quality_score(row: dict, squad: list[dict], points_are_current: bool, max_points: float = 55.0) -> tuple[float, str]:
    """Sporting quality relative to own positional peers, independent of price."""
    position = str(row.get("position") or "")
    peers = [p for p in squad if str(p.get("position") or "") == position]
    if points_are_current and row.get("average_points") is not None:
        candidate = float(row.get("average_points") or 0)
        values = [float(p.get("average_points")) for p in peers if p.get("average_points") is not None]
        metric = "Ø Punkte"
    else:
        candidate = float(row.get("market_value") or 0)
        values = [float(p.get("market_value") or 0) for p in peers if int(p.get("market_value") or 0) > 0]
        metric = "Marktwert (Preseason)"
    if not values or candidate <= 0:
        return max_points * 0.5, f"{metric}: zu wenig eigene Vergleichsdaten"
    reference = float(median(values))
    if reference <= 0:
        return max_points * 0.5, f"{metric}: zu wenig eigene Vergleichsdaten"
    ratio = candidate / reference
    points = max_points * _clamp((ratio - 0.5) / 1.0)
    return points, f"{metric} vs. eigener {position}-Median: {ratio:.2f}x"


def _upgrade_score(row: dict, squad: list[dict], points_are_current: bool, max_points: float = 25.0) -> tuple[float, str]:
    position = str(row.get("position") or "")
    peers = [p for p in squad if str(p.get("position") or "") == position]
    if not peers:
        return max_points, "keine eigene Positionsreferenz"

    candidate_metric = None
    peer_values: list[float] = []
    metric_name = "Marktwert"
    if points_are_current and row.get("average_points") is not None:
        candidate_metric = float(row.get("average_points") or 0)
        peer_values = [float(p.get("average_points")) for p in peers if p.get("average_points") is not None]
        metric_name = "Ø Punkte"

    if candidate_metric is None or not peer_values:
        candidate_metric = float(row.get("market_value") or 0)
        peer_values = [float(p.get("market_value") or 0) for p in peers if int(p.get("market_value") or 0) > 0]
        metric_name = "Marktwert"

    if not peer_values or candidate_metric <= 0:
        return max_points * 0.5, f"{metric_name}: zu wenig Vergleichsdaten"

    reference = float(median(peer_values))
    if reference <= 0:
        return max_points * 0.5, f"{metric_name}: zu wenig Vergleichsdaten"
    ratio = candidate_metric / reference
    # 50% of own positional median => 0; same level => 50%; 150% => full.
    score = max_points * _clamp((ratio - 0.5) / 1.0)
    return score, f"{metric_name} vs. eigener {position}-Median: {ratio:.2f}x"


def _trend_score(market_trend: int | None, max_points: float) -> tuple[float, str]:
    if market_trend == 1:
        return max_points, "Marktwerttrend steigend"
    if market_trend == 2:
        return max_points * 0.10, "Marktwerttrend fallend"
    return max_points * 0.5, "Marktwerttrend neutral/unklar"


def _ppm_score(row: dict, position_median: float | None, max_points: float) -> tuple[float, str]:
    ppm = row.get("points_per_million")
    if ppm is None or not position_median or position_median <= 0:
        return max_points * 0.5, "Punkte/Mio: zu wenig aktuelle Daten"
    ratio = float(ppm) / float(position_median)
    score = max_points * _clamp((ratio - 0.5) / 1.0)
    return score, f"Punkte/Mio vs. Markt-{row.get('position')}-Median: {ratio:.2f}x"


def _daily_pct_from_delta(current_mv: int, delta: float, days: int) -> float | None:
    if current_mv <= 0 or days <= 0:
        return None
    start = float(current_mv) - float(delta)
    if start <= 0:
        return None
    ratio = float(current_mv) / start
    return (ratio ** (1.0 / days) - 1.0) * 100.0


def _advanced_trend_score(row: dict, max_points: float) -> tuple[float, str]:
    """Momentum from non-overlapping intervals to avoid counting the same days repeatedly."""
    mv = int(row.get("market_value") or 0)
    if mv <= 0:
        return _trend_score(row.get("market_trend"), max_points)

    cumulative = {key: row.get(key) for key in ("d1", "d3", "d7", "d14")}
    intervals: list[tuple[float, float, str]] = []
    # Recent intervals carry more weight, but each calendar day belongs to one interval only.
    specs = [
        ("d1", None, 1, 0.35, "0–1T"),
        ("d3", "d1", 2, 0.30, "2–3T"),
        ("d7", "d3", 4, 0.22, "4–7T"),
        ("d14", "d7", 7, 0.13, "8–14T"),
    ]
    for key, previous_key, days, weight, label in specs:
        current_delta = cumulative.get(key)
        if current_delta is None:
            continue
        if previous_key is None:
            segment_delta = float(current_delta)
            segment_end_mv = mv
        else:
            previous_delta = cumulative.get(previous_key)
            if previous_delta is None:
                continue
            segment_delta = float(current_delta) - float(previous_delta)
            # Value at the end of the older segment boundary.
            segment_end_mv = int(round(mv - float(previous_delta)))
        pct = _daily_pct_from_delta(segment_end_mv, segment_delta, days)
        if pct is not None:
            intervals.append((pct, weight, label))

    if not intervals:
        return _trend_score(row.get("market_trend"), max_points)
    weight_sum = sum(weight for _, weight, _ in intervals)
    daily_pct = sum(value * weight for value, weight, _ in intervals) / weight_sum
    factor = _clamp((daily_pct + 0.75) / 1.5)
    accel = row.get("trend_acceleration")
    accel_pct = (float(accel) / mv * 100.0) if accel is not None else 0.0
    factor = _clamp(factor + max(-0.08, min(0.08, accel_pct * 0.15)))
    return max_points * factor, f"MW-Momentum {daily_pct:+.2f}%/Tag · Beschleunigung {accel_pct:+.2f}%/Tag"


def _fair_value(row: dict, position_ppm_median: float | None) -> tuple[int | None, float | None]:
    ap = row.get("average_points")
    if ap is None or not position_ppm_median or position_ppm_median <= 0:
        return None, None
    fair = int(round(float(ap) / float(position_ppm_median) * 1_000_000.0))
    price = int(row.get("price") or row.get("market_value") or 0)
    delta_pct = ((price - fair) / fair * 100.0) if fair > 0 and price > 0 else None
    return fair, delta_pct


def _league_deal_context(row: dict, league_transfers: list[dict]) -> dict:
    pid = str(row.get("player_id") or "")
    prices = [int(r.get("price") or 0) for r in league_transfers if str(r.get("player_id") or "") == pid and int(r.get("price") or 0) > 0]
    if not prices:
        return {"count": 0, "median": None, "last": None, "delta_pct": None}
    med = float(median(prices))
    price = int(row.get("price") or 0)
    delta_pct = ((price - med) / med * 100.0) if price > 0 and med > 0 else None
    return {"count": len(prices), "median": int(round(med)), "last": prices[0], "delta_pct": delta_pct}


def _deal_score(delta_pct: float | None, max_points: float) -> tuple[float, str]:
    if delta_pct is None:
        return max_points * 0.5, "keine belastbare Liga-Preishistorie"
    # 15% unter dem Liga-Median => full; 20% darüber => zero.
    factor = _clamp((20.0 - delta_pct) / 35.0)
    return max_points * factor, f"aktueller Preis {delta_pct:+.1f}% vs. Liga-Deal-Median"


def _scarcity_score(position: str, rows: list[dict], max_points: float) -> tuple[float, str]:
    position_rows = [r for r in rows if str(r.get("position") or "") == position]
    count = len(position_rows)
    if not rows or not position:
        return max_points * 0.5, "Marktknappheit nicht bestimmbar"
    expected = len(rows) / max(1, len({str(r.get("position") or "") for r in rows if r.get("position")}))
    ratio = count / expected if expected else 1.0
    # Fewer available players at the position -> higher scarcity score.
    factor = _clamp((1.6 - ratio) / 1.2)
    return max_points * factor, f"{count} {position} aktuell auf dem Markt"


def _signal_for(fit_score: int, investment_score: int) -> str:
    if fit_score >= 75 and investment_score >= 75:
        return "TOP-CHANCE"
    if fit_score >= 75:
        return "KADER-UPGRADE"
    if investment_score >= 75:
        return "INVEST-CHANCE"
    if max(fit_score, investment_score) >= 60:
        return "KAUFPRÜFUNG"
    if fit_score < 35 and investment_score < 35:
        return "PASSEN"
    return "BEOBACHTEN"


def enrich_market_entries(
    entries: list[dict],
    available_budget: int | None = None,
    squad: Iterable[dict] | None = None,
    *,
    points_are_current: bool = True,
    league_transfers: Iterable[dict] | None = None,
) -> list[dict]:
    """Add transparent market, squad-fit and investment metrics.

    Two independent 0-100 scores are produced:
    - squad_fit_score: personalized to the current squad and available cash.
    - investment_score: trading/value opportunity independent of squad need.

    Every component and weight is stored on the row so the UI can explain the
    exact calculation instead of exposing a black-box recommendation.
    """
    squad_rows = [dict(p) for p in (squad or [])]
    transfer_rows = [dict(r) for r in (league_transfers or [])]
    rows: list[dict] = []
    for raw in entries:
        row = dict(raw)
        price = int(row.get("price") or 0)
        mv = int(row.get("market_value") or 0)
        # In this league bids must be at least the current market value. Keep the
        # visible listing price for UI/context, but rate the deal against the lowest
        # actually executable bid. This also prevents stale manager listings far
        # below MW from being misclassified as huge bargains.
        minimum_bid = mv if mv > 0 else price
        effective_price = max(price, minimum_bid) if price > 0 else minimum_bid
        row["listing_price"] = price
        row["minimum_bid"] = minimum_bid
        row["effective_price"] = effective_price
        ap = row.get("average_points") if points_are_current else None
        pos = row.get("position") or POSITION_LABELS.get(row.get("pos"), "")
        row["position"] = pos
        delta = effective_price - mv if effective_price and mv else None
        delta_pct = (delta / mv * 100.0) if delta is not None and mv else None
        ppm = points_per_million(ap, effective_price or mv)
        row["price_delta"] = delta
        row["price_delta_pct"] = delta_pct
        row["points_per_million"] = ppm
        row["affordable"] = available_budget is not None and effective_price > 0 and effective_price <= int(available_budget)
        rows.append(row)

    position_ppm: dict[str, list[float]] = {}
    for row in rows:
        ppm = row.get("points_per_million")
        pos = str(row.get("position") or "")
        if ppm is not None and pos:
            position_ppm.setdefault(pos, []).append(float(ppm))
    medians = {pos: median(values) for pos, values in position_ppm.items() if values}

    for row in rows:
        pos = str(row.get("position") or "")
        delta_pct = row.get("price_delta_pct")

        # -------- Sporting / squad fit (100) --------
        # Deliberately independent from price, affordability and market scarcity.
        position_points, position_reason = _position_need_score(pos, squad_rows, 20.0)
        quality_points, quality_reason = _quality_score(row, squad_rows, points_are_current, 55.0)
        replacement_value, replacement_reason = _replacement_value(row, squad_rows, points_are_current=points_are_current)
        if replacement_value is None:
            replacement_points = 12.5
        elif points_are_current:
            # +50 average points over the weakest own option reaches full replacement value.
            replacement_points = 25.0 * _clamp((float(replacement_value) + 25.0) / 75.0)
        else:
            # Preseason uses relative market-value uplift only as a weak proxy.
            mv = max(1, int(row.get("market_value") or 0))
            replacement_points = 25.0 * _clamp((float(replacement_value) / mv + 0.25) / 0.75)
        fit_score = _round_score(position_points + quality_points + replacement_points)
        fit_breakdown = {
            "positionsbedarf": round(position_points, 1),
            "qualitaet": round(quality_points, 1),
            "replacement": round(replacement_points, 1),
        }
        fit_reasons = [
            f"Positionsbedarf {position_points:.1f}/20 ({position_reason})",
            f"Spielerqualität {quality_points:.1f}/55 ({quality_reason})",
            f"Replacement {replacement_points:.1f}/25 ({replacement_reason})",
        ]

        # League deals remain useful context, but no longer feed a synthetic fair value.
        row["fair_value"] = None  # legacy compatibility; intentionally retired from scoring
        row["fair_value_delta_pct"] = None
        deal_context = _league_deal_context(row, transfer_rows)
        row["league_deal_count"] = deal_context["count"]
        row["league_deal_median"] = deal_context["median"]
        row["league_deal_delta_pct"] = deal_context["delta_pct"]

        # -------- Trading opportunity (100) --------
        # Three largely independent dimensions: performance, value and momentum.
        if points_are_current:
            performance_max, value_max, trend_max = 35.0, 35.0, 30.0
            performance_points, performance_reason = _ppm_score(
                {**row, "points_per_million": row.get("average_points")},
                median([float(r.get("average_points")) for r in rows if str(r.get("position") or "") == pos and r.get("average_points") is not None])
                if any(str(r.get("position") or "") == pos and r.get("average_points") is not None for r in rows) else None,
                performance_max,
            )
            # _ppm_score is reused as a relative-score mapper here; its input is raw average points.
            performance_reason = performance_reason.replace("Punkte/Mio", "Ø Punkte").replace("Markt-", "Markt-")
        else:
            performance_max, value_max, trend_max = 0.0, 55.0, 45.0
            performance_points, performance_reason = 0.0, "Preseason: Saisonleistung nicht gewertet"

        value_points = _price_score(delta_pct, value_max)
        value_reason = "Preis relativ zum aktuellen Marktwert"
        trend_points, trend_reason = _advanced_trend_score(row, trend_max)
        investment_score = _round_score(performance_points + value_points + trend_points)

        investment_breakdown = {
            "performance": round(performance_points, 1),
            "preisvorteil": round(value_points, 1),
            "markttrend": round(trend_points, 1),
            # compatibility keys kept at zero so older UI code does not crash
            "fair_value": 0.0,
            "liga_deals": 0.0,
            "punkte_effizienz": round(performance_points, 1),
        }
        investment_reasons = [
            f"Performance {performance_points:.1f}/{int(performance_max)} ({performance_reason})" if performance_max else performance_reason,
            f"Preis/MW {value_points:.1f}/{int(value_max)} ({value_reason})",
            f"MW-Momentum {trend_points:.1f}/{int(trend_max)} ({trend_reason})",
        ]
        if deal_context["count"]:
            investment_reasons.append(f"Liga-Deals nur Kontext: Median {int(deal_context['median'] or 0):,} €".replace(",", "."))

        # Decision layer: convert component scores into concrete, explainable outputs.
        row["squad_fit_score"] = fit_score
        row["investment_score"] = investment_score
        row["replacement_value"] = replacement_value
        row["replacement_reason"] = replacement_reason
        confidence_score, confidence_label, confidence_reasons = _confidence(
            row, points_are_current=points_are_current, deal_count=int(deal_context["count"] or 0)
        )
        row["confidence_score"] = confidence_score  # legacy key
        row["confidence_label"] = confidence_label  # legacy key
        row["confidence_reasons"] = confidence_reasons
        row["data_quality_score"] = confidence_score
        row["data_quality_label"] = confidence_label
        row["data_quality_reasons"] = confidence_reasons
        horizon, horizon_reason = _investment_horizon(row)
        row["investment_horizon"] = horizon
        row["investment_horizon_reason"] = horizon_reason
        max_bid, max_bid_reasons = _max_bid(
            row, available_budget=available_budget, replacement=replacement_value, points_are_current=points_are_current
        )
        row["max_bid"] = max_bid
        row["max_bid_reasons"] = max_bid_reasons

        price_now = int(row.get("effective_price") or row.get("price") or 0)
        minimum_bid = int(row.get("minimum_bid") or 0)
        signal = _signal_for(fit_score, investment_score)
        # The executable floor is the current MW. If our own Max-Bid is already
        # below that floor, there is no rational bid range and we must pass.
        if max_bid and minimum_bid and max_bid < minimum_bid:
            signal = "PASSEN"
        elif max_bid and price_now > max_bid * 1.08:
            signal = "PASSEN"
        elif max_bid and minimum_bid <= max_bid and price_now <= max_bid and fit_score >= 65 and investment_score >= 60:
            signal = "KAUFEN"
        elif max_bid and minimum_bid <= max_bid and price_now <= max_bid and investment_score >= 75:
            signal = "INVEST-CHANCE"
        row["squad_fit_score"] = fit_score
        row["fit_breakdown"] = fit_breakdown
        row["investment_breakdown"] = investment_breakdown
        row["fit_reasons"] = fit_reasons
        row["investment_reasons"] = investment_reasons
        row["signal"] = signal
        row["verdict"] = signal
        row["position_ppm_median"] = medians.get(pos)
        row["analysis_reasons"] = [f"Kader-Fit {fit_score}/100", f"Investment {investment_score}/100", signal]
        max_bid_text = f"{max_bid:,.0f} €".replace(",", ".") if max_bid else "nicht berechenbar"
        min_bid_text = f"{int(row.get('minimum_bid') or 0):,.0f} €".replace(",", ".") if row.get("minimum_bid") else "nicht berechenbar"
        row["analysis_text"] = (
            f"FÜR DEINEN KADER {fit_score}/100\n- " + "\n- ".join(fit_reasons)
            + f"\n\nINVESTMENT {investment_score}/100\n- " + "\n- ".join(investment_reasons)
            + f"\n\nENTSCHEIDUNG\n- Replacement: {replacement_reason}"
            + f"\n- Mindestgebot: {min_bid_text}"
            + f"\n- Max-Bid: {max_bid_text}"
        )
        row["analysis_text"] += (
            f"\n- Investment-Horizont: {horizon} ({horizon_reason})"
            f"\n- Datenbasis: {confidence_label} ({confidence_score}/100)"
            f"\n\n→ {signal}"
        )

    return rows


def financing_scenarios(
    target_price: int,
    available_budget: int,
    squad: Iterable[dict],
    *,
    max_sales: int = 3,
    limit: int = 5,
) -> dict:
    """Return practical sale combinations that would finance a target purchase.

    The current market value is used as the sale assumption. Transfer-list players
    are preferred, while selling Stamm players receives a penalty.
    """
    target_price = max(0, int(target_price or 0))
    available_budget = int(available_budget or 0)
    gap = max(0, target_price - available_budget)
    if gap == 0:
        return {
            "gap": 0,
            "directly_affordable": True,
            "remaining_budget": available_budget - target_price,
            "scenarios": [],
        }

    players = []
    for player in squad:
        value = int(player.get("market_value") or 0)
        if value <= 0:
            continue
        role = str(player.get("player_role") or "OFFEN").upper()
        players.append({
            "player_id": str(player.get("player_id") or ""),
            "name": str(player.get("name") or "Unbekannt"),
            "club": player.get("club") or "",
            "position": player.get("position") or "",
            "market_value": value,
            "role": role,
        })

    role_penalty = {"TRANSFERLISTE": 0, "OFFEN": 1, "INVEST": 2, "STAMM": 5}
    candidates = []
    for count in range(1, min(max_sales, len(players)) + 1):
        for combo in combinations(players, count):
            proceeds = sum(p["market_value"] for p in combo)
            if proceeds < gap:
                continue
            penalty = sum(role_penalty.get(p["role"], 1) for p in combo)
            overfund = proceeds - gap
            candidates.append((count, penalty, overfund, combo, proceeds))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    scenarios = []
    for _, penalty, overfund, combo, proceeds in candidates[:limit]:
        scenarios.append({
            "players": [dict(p) for p in combo],
            "sale_value": proceeds,
            "overfund": overfund,
            "role_penalty": penalty,
            "remaining_budget": available_budget + proceeds - target_price,
        })

    return {
        "gap": gap,
        "directly_affordable": False,
        "remaining_budget": None,
        "scenarios": scenarios,
    }

# ---------------------------------------------------------------------------
# Decision layer: interpretable outputs above the raw 0-100 component scores.
# ---------------------------------------------------------------------------

def _confidence(row: dict, *, points_are_current: bool, deal_count: int) -> tuple[int, str, list[str]]:
    """Data quality only. This is explicitly not a probability that a call is correct."""
    points = 25
    reasons = ["aktueller Preis und Marktwert vorhanden"]
    history_windows = sum(row.get(key) is not None for key in ("d1", "d3", "d7", "d14"))
    hist_points = min(40, history_windows * 10)
    points += hist_points
    if history_windows:
        reasons.append(f"{history_windows}/4 MW-Zeitfenster vorhanden")
    if deal_count:
        deal_points = min(15, 5 + deal_count * 3)
        points += deal_points
        reasons.append(f"{deal_count} Liga-Deal(s) als Kontext")
    if points_are_current and row.get("average_points") is not None:
        points += 20
        reasons.append("aktuelle Saisonleistung vorhanden")
    score = _round_score(points)
    label = "HOCH" if score >= 75 else "MITTEL" if score >= 50 else "GERING"
    return score, label, reasons


def _replacement_value(row: dict, squad: list[dict], *, points_are_current: bool) -> tuple[float | None, str]:
    """Return candidate uplift over the weakest realistic own player at the same position."""
    pos = str(row.get("position") or "")
    peers = [p for p in squad if str(p.get("position") or "") == pos]
    if not peers:
        return None, f"kein eigener {pos}-Spieler als Referenz"
    if points_are_current and row.get("average_points") is not None:
        own = [float(p.get("average_points")) for p in peers if p.get("average_points") is not None]
        if own:
            baseline = min(own)
            candidate = float(row.get("average_points") or 0)
            return candidate - baseline, f"{candidate:.0f} ØP vs. schwächste eigene Option {baseline:.0f} ØP"
    own_mv = [int(p.get("market_value") or 0) for p in peers if int(p.get("market_value") or 0) > 0]
    if own_mv and int(row.get("market_value") or 0) > 0:
        baseline = min(own_mv)
        candidate = int(row.get("market_value") or 0)
        return float(candidate - baseline), f"Preseason: {candidate/1e6:.2f} Mio. vs. schwächste eigene Option {baseline/1e6:.2f} Mio."
    return None, "zu wenig Daten für Replacement Value"


def _investment_horizon(row: dict) -> tuple[str, str]:
    """Classify the likely use case from observable price and momentum data."""
    delta_pct = row.get("price_delta_pct")
    mv = int(row.get("market_value") or 0)
    d1 = row.get("d1")
    d7 = row.get("d7")
    one_day_pct = (float(d1) / mv * 100.0) if d1 is not None and mv else None
    seven_day_daily = (float(d7) / 7 / mv * 100.0) if d7 is not None and mv else None
    if delta_pct is not None and delta_pct <= 0 and one_day_pct is not None and one_day_pct >= 0.35:
        return "FLIP 1–3T", f"unter/nahe MW und starkes 24h-Momentum ({one_day_pct:+.2f}%)"
    if seven_day_daily is not None and seven_day_daily >= 0.12:
        return "TRADING 1W", f"7T-Momentum stabil positiv ({seven_day_daily:+.2f}%/Tag)"
    if int(row.get("investment_score") or 0) >= 70 and (delta_pct is None or delta_pct <= 8):
        return "HOLD", "attraktive Gesamtbewertung ohne kurzfristigen Flip-Zwang"
    return "KEIN KLARER HORIZONT", "kein belastbares kurzfristiges oder mittelfristiges Setup"


def _max_bid(row: dict, *, available_budget: int | None, replacement: float | None, points_are_current: bool) -> tuple[int | None, list[str]]:
    """Conservative ceiling anchored exclusively to the observable market value.

    Premiums are explicit and capped at 8%. No synthetic fair-value anchor and no
    recursive use of the final investment score as a multiplier.
    """
    mv = int(row.get("market_value") or 0)
    price = int(row.get("effective_price") or row.get("price") or 0)
    if mv <= 0:
        return None, ["kein Marktwert verfügbar"]

    squad_score = int(row.get("squad_fit_score") or 0)
    trading_score = int(row.get("investment_score") or 0)
    momentum_score = float((row.get("investment_breakdown") or {}).get("markttrend") or 0)
    momentum_max = 30.0 if points_are_current else 45.0

    premium = 0.0
    reasons = ["Basis: aktueller Marktwert"]
    if trading_score >= 75:
        premium += 0.03
        reasons.append("+3,0% starkes Trading-Setup")
    elif trading_score < 40:
        reasons.append("kein Trading-Premium")
    if squad_score >= 75:
        premium += 0.03
        reasons.append("+3,0% klarer Kader-Upgrade")
    if momentum_max > 0 and momentum_score / momentum_max >= 0.75:
        premium += 0.02
        reasons.append("+2,0% starkes MW-Momentum")

    premium = min(0.08, max(0.0, premium))
    max_bid = int(round(mv * (1.0 + premium) / 10_000.0) * 10_000)
    reasons.append(f"Premium gesamt {premium*100:.1f}% · hart gedeckelt bei 8,0%")
    if available_budget is not None and available_budget < mv:
        reasons.append("aktuell nicht direkt finanzierbar; Verkäufe nötig")
    if price and max_bid:
        reasons.append(f"ausführbarer Preis liegt {(price-max_bid)/max_bid*100:+.1f}% zum Max-Bid")
    return max_bid, reasons

