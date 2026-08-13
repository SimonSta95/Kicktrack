from __future__ import annotations

from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _berlin_timezone():
    """Return Europe/Berlin without making Windows startup depend on OS tzdata.

    Python on Windows often has no IANA zone database. The packaged ``tzdata``
    dependency normally supplies it; the local-zone fallback keeps the app
    usable even when dependencies have not been reinstalled yet.
    """
    try:
        return ZoneInfo("Europe/Berlin")
    except ZoneInfoNotFoundError:
        # KickTrack is a Germany-focused personal app. On the user's Windows
        # machine the configured local timezone is therefore the best safe
        # fallback and, unlike a hard-coded UTC offset, does not assume +01/+02.
        return datetime.now().astimezone().tzinfo


BERLIN = _berlin_timezone()
FIRST_MATCHDAY_DEADLINES = {
    # Bundesliga/Kickbase 2026/27: first hard solvency checkpoint for this app.
    2026: date(2026, 8, 28),
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _now_local(reference: datetime | None = None) -> datetime:
    if reference is None:
        return datetime.now(BERLIN)
    if reference.tzinfo is None:
        return reference.replace(tzinfo=BERLIN)
    return reference.astimezone(BERLIN)


def next_solvency_deadline(*, season_started: bool, reference: datetime | None = None) -> datetime:
    """Return the next Friday 20:00 solvency checkpoint.

    Before the first matchday we use the configured season-opening Friday. Once
    the season has started, every Friday at 20:00 is treated as a hard deadline.
    """
    now = _now_local(reference)
    if not season_started:
        configured = FIRST_MATCHDAY_DEADLINES.get(now.year)
        if configured and datetime.combine(configured, time(20, 0), BERLIN) >= now:
            return datetime.combine(configured, time(20, 0), BERLIN)

    days_ahead = (4 - now.weekday()) % 7  # Monday=0, Friday=4
    deadline = datetime.combine(now.date() + timedelta(days=days_ahead), time(20, 0), BERLIN)
    if deadline <= now:
        deadline += timedelta(days=7)
    return deadline


def deadline_context(*, season_started: bool, reference: datetime | None = None) -> dict:
    now = _now_local(reference)
    deadline = next_solvency_deadline(season_started=season_started, reference=now)
    hours = max(0.0, (deadline - now).total_seconds() / 3600.0)
    days = hours / 24.0

    # Target reserve, not a Kickbase rule. The actual hard rule remains >= 0 €.
    if days > 7:
        reserve = 3_000_000
        phase = "BUILD + TRADE"
    elif days > 3:
        reserve = 2_000_000
        phase = "LINEUP + LIQUIDITÄT"
    elif days > 1:
        reserve = 1_000_000
        phase = "READY MODE"
    else:
        reserve = 0
        phase = "DEADLINE"
    return {
        "deadline": deadline,
        "hours_to_deadline": hours,
        "days_to_deadline": days,
        "safety_reserve": reserve,
        "phase": phase,
    }


def _recent_daily_change(row: dict) -> float:
    """Conservative recent absolute MW velocity using disjoint recent windows."""
    weighted: list[tuple[float, float]] = []
    d1, d3, d7 = row.get("d1"), row.get("d3"), row.get("d7")
    if d1 is not None:
        weighted.append((float(d1), 0.50))
    if d3 is not None and d1 is not None:
        weighted.append(((float(d3) - float(d1)) / 2.0, 0.30))
    elif d3 is not None:
        weighted.append((float(d3) / 3.0, 0.30))
    if d7 is not None and d3 is not None:
        weighted.append(((float(d7) - float(d3)) / 4.0, 0.20))
    elif d7 is not None:
        weighted.append((float(d7) / 7.0, 0.20))
    if not weighted:
        return 0.0
    total_weight = sum(weight for _, weight in weighted)
    return sum(value * weight for value, weight in weighted) / total_weight


def _expected_trade_return(row: dict, *, days_to_deadline: float) -> tuple[int, float, int]:
    """Return expected profit, expected capital return %, and planned hold days.

    This is intentionally a short-horizon planning estimate, not a fair-value
    forecast. We cap the holding period to five days and haircut the observed
    recent velocity by 25% to avoid extrapolating hot streaks one-for-one.
    """
    price = int(row.get("effective_price") or row.get("market_value") or row.get("price") or 0)
    if price <= 0:
        return 0, 0.0, 0
    hold_days = max(1, min(5, int(max(1.0, days_to_deadline - 1.0))))
    daily = _recent_daily_change(row)
    conservative_daily = daily * 0.75
    expected_profit = int(round(conservative_daily * hold_days / 10_000.0) * 10_000)
    expected_return_pct = expected_profit / price * 100.0
    return expected_profit, expected_return_pct, hold_days


def _quality_component(row: dict) -> float:
    fit = row.get("fit_breakdown") or {}
    # Market rows use /55; own squad rows use /60.
    if "qualitaet" in fit:
        return float(fit.get("qualitaet") or 0)
    own = row.get("squad_score_breakdown") or {}
    return float(own.get("qualitaet") or 0)


def _market_core_score(row: dict) -> int:
    fit = float(row.get("squad_fit_score") or 0)
    quality = _quality_component(row)
    replacement = float((row.get("fit_breakdown") or {}).get("replacement") or 0)
    # The threshold is deliberately strict. In preseason this remains a proxy,
    # so only exceptional squad-fit profiles become a long-term target.
    score = 0.55 * fit + 0.30 * min(100.0, quality / 55.0 * 100.0) + 0.15 * min(100.0, replacement / 25.0 * 100.0)
    return int(round(max(0.0, min(100.0, score))))


def _own_core_score(row: dict) -> int:
    sporting = float(row.get("squad_value_score") or 0)
    role = str(row.get("player_role") or row.get("role") or "").upper()
    role_bonus = 10.0 if role in {"STAMM", "STARTER", "KERN"} else 0.0
    return int(round(min(100.0, sporting + role_bonus)))


def _sellable_capacity(squad_rows: list[dict]) -> int:
    """Only capital explicitly marked for sale by the manager.

    HOLD/INVEST players are not imaginary liquidity. Their market value may be
    useful context, but it must not make Friday solvency look safer than it is.
    """
    total = 0
    for row in squad_rows:
        manager_role = str(row.get("player_role") or row.get("role") or "").upper()
        if manager_role == "TRANSFERLISTE":
            total += int(row.get("market_value") or 0)
    return total


def _label(score: int | float | None) -> str:
    value = int(score or 0)
    if value >= 80:
        return "STARK"
    if value >= 65:
        return "GUT"
    if value >= 45:
        return "NEUTRAL"
    return "SCHWACH"


def _squad_action(row: dict, *, trading: int, core_score: int, sell: int) -> str:
    manager_role = str(row.get("player_role") or row.get("role") or "").upper()
    d1 = row.get("d1")
    rising = d1 is not None and float(d1) > 0
    if manager_role == "TRANSFERLISTE":
        return "VERKAUF WARTEN" if trading >= 65 and rising else "VERKAUFEN"
    if manager_role in {"STAMM", "STARTER"}:
        return "HALTEN"
    if manager_role == "INVEST":
        return "INVEST HALTEN" if trading >= 60 and (rising or trading >= 70) else "VERKAUFEN"
    if core_score >= 70:
        return "HALTEN"
    if trading >= 70:
        return "INVEST HALTEN"
    if sell >= 65:
        return "VERKAUFEN"
    return "HALTEN"


def _classify_squad_row(row: dict, *, days_to_deadline: float) -> dict:
    result = dict(row)
    core_score = _own_core_score(result)
    trading = int(result.get("trading_score") or result.get("investment_score") or 0)
    sell = int(result.get("sell_decision_score") or result.get("sell_score") or 0)
    expected_profit, expected_return_pct, hold_days = _expected_trade_return(result, days_to_deadline=days_to_deadline)

    if core_score >= 82 and sell < 55:
        role = "STARTKADER"
    elif sell >= 64:
        role = "ROTATE/SELL"
    elif trading >= 72 and expected_return_pct >= 1.0:
        role = "INVEST/TRADE"
    elif core_score >= 62:
        role = "HOLD"
    elif trading >= 62 and expected_return_pct > 0:
        role = "INVEST/TRADE"
    else:
        role = "ROTATE/SELL" if sell >= 52 else "HOLD"

    result["portfolio_role"] = role
    result["core_score"] = core_score
    result["kader_label"] = _label(result.get("squad_value_score") or core_score)
    result["trade_label"] = _label(trading)
    result["action"] = _squad_action(result, trading=trading, core_score=core_score, sell=sell)
    result["expected_trade_profit"] = expected_profit
    result["expected_capital_return_pct"] = expected_return_pct
    result["planned_hold_days"] = hold_days
    result["capital_efficiency"] = expected_return_pct
    return result


def _classify_market_row(row: dict, *, days_to_deadline: float) -> dict:
    result = dict(row)
    core_score = _market_core_score(result)
    trading = int(result.get("investment_score") or 0)
    fit = int(result.get("squad_fit_score") or 0)
    expected_profit, expected_return_pct, hold_days = _expected_trade_return(result, days_to_deadline=days_to_deadline)

    # Preseason has exactly three useful market states: final-squad target,
    # short-term trade, or observation/pass. Do not pretend we can identify
    # season-long "can't miss" players before current-season performance exists.
    if fit >= 80 and core_score >= 78:
        role = "KADERZIEL"
    elif trading >= 74 and expected_return_pct >= 1.0:
        role = "INVEST"
    elif fit >= 72:
        role = "KADERZIEL"
    elif trading >= 65 and expected_return_pct > 0:
        role = "BEOBACHTEN"
    else:
        role = "PASS"

    result["portfolio_role"] = role
    result["core_score"] = core_score
    result["kader_label"] = _label(fit)
    result["trade_label"] = _label(trading)
    result["action"] = role
    result["expected_trade_profit"] = expected_profit
    result["expected_capital_return_pct"] = expected_return_pct
    result["planned_hold_days"] = hold_days
    result["capital_efficiency"] = expected_return_pct
    return result


def analyze_portfolio(
    market_rows: Iterable[dict],
    squad_rows: Iterable[dict],
    *,
    available_budget: int | None,
    season_started: bool,
    committed_budget: int = 0,
    reference: datetime | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Apply one capital-allocation model to market and own squad.

    Goal hierarchy:
    1. hard solvency at Friday 20:00,
    2. keep true core players,
    3. grow capital with short-horizon investments,
    4. rotate inefficient capital into better opportunities.
    """
    ctx = deadline_context(season_started=season_started, reference=reference)
    days = float(ctx["days_to_deadline"])
    squad = [_classify_squad_row(dict(row), days_to_deadline=days) for row in squad_rows]
    market = [_classify_market_row(dict(row), days_to_deadline=days) for row in market_rows]
    for row in squad:
        row["days_to_deadline"] = days
        row["deadline_iso"] = ctx["deadline"].isoformat()
        row["safety_reserve"] = int(ctx["safety_reserve"])
        row["portfolio_phase"] = ctx["phase"]

    budget = int(available_budget or 0)
    committed = max(0, int(committed_budget or 0))
    free_after_commitments = budget - committed
    sellable = _sellable_capacity(squad)
    reserve = int(ctx["safety_reserve"])

    for row in market:
        price = int(row.get("effective_price") or row.get("price") or row.get("market_value") or 0)
        balance_after = free_after_commitments - price
        # Hard Friday solvency is real cash after commitments. Explicit
        # transfer-list capital remains separate context until actually sold.
        projected = balance_after
        row["days_to_deadline"] = days
        row["deadline_iso"] = ctx["deadline"].isoformat()
        row["safety_reserve"] = reserve
        row["portfolio_phase"] = ctx["phase"]
        row["balance_after_buy"] = balance_after
        row["projected_deadline_balance"] = projected
        row["portfolio_sellable_capacity"] = sellable
        row["deadline_safe"] = projected >= 0
        row["reserve_safe"] = projected >= reserve

        # Deadline pressure overrides speculative buys first. A genuine core target
        # may consume the reserve, but never the hard >= 0 deadline constraint.
        role = str(row.get("portfolio_role") or "PASS")
        if projected < 0:
            row["portfolio_role"] = "PASS"
            row["portfolio_block_reason"] = "würde den prognostizierten Freitagssaldo unter 0 € drücken"
        elif days <= 3 and role in {"INVEST", "BEOBACHTEN"} and projected < reserve:
            row["portfolio_role"] = "PASS"
            row["portfolio_block_reason"] = "zu wenig Liquidität kurz vor Freitag 20:00"
        elif days <= 1 and role in {"INVEST", "BEOBACHTEN"}:
            row["portfolio_role"] = "PASS"
            row["portfolio_block_reason"] = "kein neuer Trading-Risk am Deadline-Tag"

    summary = {
        **ctx,
        "available_budget": budget,
        "committed_budget": committed,
        "balance_after_commitments": free_after_commitments,
        "sellable_capacity": sellable,
        "transfer_list_capital": sellable,
        "projected_balance_before_new_buys": free_after_commitments,
        "squad_roles": {
            role: sum(1 for row in squad if row.get("portfolio_role") == role)
            for role in ("STARTKADER", "HOLD", "INVEST/TRADE", "ROTATE/SELL")
        },
    }
    return market, squad, summary
