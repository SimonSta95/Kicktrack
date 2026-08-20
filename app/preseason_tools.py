from __future__ import annotations

from itertools import combinations
from statistics import median
from typing import Iterable

from .squad_rules import MAX_SQUAD_SIZE, required_sales

VALID_FORMATIONS = {
    "3-4-3": {"TW": 1, "ABW": 3, "MF": 4, "ST": 3},
    "3-5-2": {"TW": 1, "ABW": 3, "MF": 5, "ST": 2},
    "3-6-1": {"TW": 1, "ABW": 3, "MF": 6, "ST": 1},
    "4-2-4": {"TW": 1, "ABW": 4, "MF": 2, "ST": 4},
    "4-3-3": {"TW": 1, "ABW": 4, "MF": 3, "ST": 3},
    "4-4-2": {"TW": 1, "ABW": 4, "MF": 4, "ST": 2},
    "4-5-1": {"TW": 1, "ABW": 4, "MF": 5, "ST": 1},
    "5-2-3": {"TW": 1, "ABW": 5, "MF": 2, "ST": 3},
    "5-3-2": {"TW": 1, "ABW": 5, "MF": 3, "ST": 2},
    "5-4-1": {"TW": 1, "ABW": 5, "MF": 4, "ST": 1},
}
POSITION_ORDER = {"TW": 0, "ABW": 1, "MF": 2, "ST": 3}


def add_value_scores(rows: Iterable[dict]) -> list[dict]:
    """Add a position-relative preseason price/performance score.

    This is intentionally relative, not a fake fair-value model. A player's
    sporting/portfolio quality is divided by the square-root of his executable
    price and then ranked against transfer-market peers at the same position.
    """
    result = [dict(r) for r in rows]
    by_pos: dict[str, list[float]] = {}
    for row in result:
        fit = float(row.get("squad_fit_score") or 0)
        trade = float(row.get("investment_score") or 0)
        price = int(row.get("effective_price") or row.get("price") or row.get("market_value") or 0)
        if price <= 0:
            row["value_raw"] = None
            continue
        quality = 0.70 * fit + 0.30 * trade
        price_m = max(0.25, price / 1_000_000.0)
        raw = quality / (price_m ** 0.5)
        row["value_raw"] = raw
        pos = str(row.get("position") or "")
        if pos:
            by_pos.setdefault(pos, []).append(raw)

    for row in result:
        raw = row.get("value_raw")
        pos = str(row.get("position") or "")
        values = sorted(by_pos.get(pos, []))
        if raw is None or not values:
            row["value_score"] = None
            row["value_label"] = "–"
            continue
        if len(values) == 1:
            percentile = 50.0
        else:
            below = sum(1 for v in values if v < raw)
            equal = sum(1 for v in values if v == raw)
            percentile = (below + max(0, equal - 1) / 2) / (len(values) - 1) * 100.0
        score = int(round(max(0.0, min(100.0, percentile))))
        row["value_score"] = score
        row["value_label"] = "TOP" if score >= 80 else "GUT" if score >= 65 else "OK" if score >= 45 else "TEUER"
        row["value_reason"] = f"Preis-Leistung im {pos}-Vergleich: {score}/100 ({row['value_label']})"
    return result




def _candidate_score(row: dict, *, own: bool) -> float:
    if own:
        return float(row.get("squad_value_score") or 50)
    fit = float(row.get("squad_fit_score") or 0)
    value = float(row.get("value_score") if row.get("value_score") is not None else 50)
    trade = float(row.get("investment_score") or 0)
    return 0.72 * fit + 0.18 * value + 0.10 * trade


def optimize_starting_squad(
    squad_rows: Iterable[dict],
    market_rows: Iterable[dict],
    available_budget: int,
    *,
    max_market_buys: int = 6,
) -> dict:
    """Optimize an attainable XI across legal formations and current market.

    Own players have zero incremental acquisition cost. Current market players
    use effective_price/minimum_bid. Candidate pools are pruned per position for
    predictable runtime, then an exact combination search is run per position.
    """
    budget = max(0, int(available_budget or 0))
    squad_rows = [dict(r) for r in squad_rows]
    current_squad_size = len(squad_rows)
    by_pos: dict[str, list[dict]] = {p: [] for p in POSITION_ORDER}

    for raw in squad_rows:
        row = dict(raw)
        pos = str(row.get("position") or "")
        if pos not in by_pos:
            continue
        by_pos[pos].append({
            **row,
            "optimizer_source": "KADER",
            "optimizer_cost": 0,
            "optimizer_score": _candidate_score(row, own=True),
        })

    for raw in market_rows:
        row = dict(raw)
        pos = str(row.get("position") or "")
        if pos not in by_pos:
            continue
        if str(row.get("portfolio_role") or row.get("action") or "").upper() == "PASS":
            continue
        cost = int(row.get("effective_price") or row.get("minimum_bid") or row.get("price") or 0)
        if cost <= 0 or cost > budget:
            continue
        by_pos[pos].append({
            **row,
            "optimizer_source": "MARKT",
            "optimizer_cost": cost,
            "optimizer_score": _candidate_score(row, own=False),
        })

    # Preserve every own player, plus strongest market alternatives; prevents
    # expensive combinatorial explosions without hiding current-squad options.
    for pos, candidates in by_pos.items():
        own = [c for c in candidates if c["optimizer_source"] == "KADER"]
        market = sorted(
            [c for c in candidates if c["optimizer_source"] == "MARKT"],
            key=lambda c: (-float(c["optimizer_score"]), int(c["optimizer_cost"])),
        )[:8]
        by_pos[pos] = own + market

    best = None
    for formation, needs in VALID_FORMATIONS.items():
        position_options: list[list[dict]] = []
        feasible = True
        for pos in ("TW", "ABW", "MF", "ST"):
            need = needs[pos]
            candidates = by_pos[pos]
            if len(candidates) < need:
                feasible = False
                break
            options = []
            for combo in combinations(candidates, need):
                cost = sum(int(c["optimizer_cost"]) for c in combo)
                buys = sum(1 for c in combo if c["optimizer_source"] == "MARKT")
                if cost > budget or buys > max_market_buys:
                    continue
                options.append({
                    "players": combo,
                    "cost": cost,
                    "buys": buys,
                    "score": sum(float(c["optimizer_score"]) for c in combo),
                })
            # Keep Pareto-ish strongest options; enough diversity across cost levels.
            options.sort(key=lambda o: (-o["score"], o["cost"], o["buys"]))
            position_options.append(options[:220])
        if not feasible or any(not opts for opts in position_options):
            continue

        states = [{"players": tuple(), "cost": 0, "buys": 0, "score": 0.0}]
        for options in position_options:
            next_states = []
            for state in states:
                for option in options:
                    cost = state["cost"] + option["cost"]
                    buys = state["buys"] + option["buys"]
                    if cost > budget or buys > max_market_buys:
                        continue
                    next_states.append({
                        "players": state["players"] + option["players"],
                        "cost": cost,
                        "buys": buys,
                        "score": state["score"] + option["score"],
                    })
            # Bucket by 250k and purchase count; retain best sporting result per bucket.
            buckets = {}
            for state in next_states:
                key = (state["cost"] // 250_000, state["buys"])
                if key not in buckets or state["score"] > buckets[key]["score"]:
                    buckets[key] = state
            states = sorted(buckets.values(), key=lambda s: (-s["score"], s["cost"]))[:1800]
            if not states:
                break
        if not states:
            continue
        candidate = max(states, key=lambda s: (s["score"], -s["cost"]))
        candidate["formation"] = formation
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if best is None:
        return {"feasible": False, "players": [], "formation": None, "spent": 0, "remaining": budget, "market_buys": 0, "score": None, "current_squad_size": current_squad_size, "max_squad_size": MAX_SQUAD_SIZE, "free_squad_slots": max(0, MAX_SQUAD_SIZE - current_squad_size), "required_sales": 0, "sale_candidates": []}

    players = sorted(best["players"], key=lambda p: (POSITION_ORDER.get(str(p.get("position")), 9), -float(p["optimizer_score"])))
    market_buys = int(best["buys"])
    sales_needed = required_sales(current_squad_size, market_buys)
    selected_own_ids = {str(p.get("player_id") or "") for p in players if p.get("optimizer_source") == "KADER"}
    sale_pool = [
        dict(p) for p in squad_rows
        if str(p.get("player_id") or "") not in selected_own_ids
    ]
    # Prefer players already marked for sale/rotation; otherwise use the weakest
    # non-XI squad values. These are suggestions only, never assumed sales.
    def _sale_rank(p: dict) -> tuple:
        role = str(p.get("player_role") or p.get("portfolio_role") or p.get("action") or "").upper()
        explicit = 0 if role in {"TRANSFERLISTE", "ROTATE/SELL", "VERKAUFEN", "VERKAUF WARTEN"} else 1
        return (explicit, float(p.get("squad_value_score") or 50), int(p.get("market_value") or 0))
    sale_pool.sort(key=_sale_rank)
    sale_candidates = sale_pool[:sales_needed]
    # A plan that would require more exits than we can identify outside the XI is
    # not roster-feasible even if it is financially feasible.
    if len(sale_candidates) < sales_needed:
        return {"feasible": False, "players": [], "formation": None, "spent": 0, "remaining": budget, "market_buys": 0, "score": None, "current_squad_size": current_squad_size, "max_squad_size": MAX_SQUAD_SIZE, "free_squad_slots": max(0, MAX_SQUAD_SIZE - current_squad_size), "required_sales": sales_needed, "sale_candidates": []}
    return {
        "feasible": True,
        "players": [dict(p) for p in players],
        "formation": best["formation"],
        "spent": int(best["cost"]),
        "remaining": budget - int(best["cost"]),
        "market_buys": market_buys,
        "score": round(float(best["score"]) / 11.0, 1),
        "current_squad_size": current_squad_size,
        "max_squad_size": MAX_SQUAD_SIZE,
        "free_squad_slots": max(0, MAX_SQUAD_SIZE - current_squad_size),
        "required_sales": sales_needed,
        "sale_candidates": sale_candidates,
    }
