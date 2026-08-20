from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable


def _parse_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day(value) -> str:
    dt = _parse_dt(value)
    if dt:
        return dt.date().isoformat()
    return str(value or "")[:10]


def _pct(delta: int | None, base: int | None) -> float | None:
    if delta is None or not base:
        return None
    return float(delta) / float(base) * 100.0


def _history_sorted(rows: Iterable[dict]) -> list[dict]:
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (str(row.get("snapshot_date") or ""), str(row.get("recorded_at") or "")),
    )


def _history_on_or_before(history: list[dict], target_day: str) -> dict | None:
    candidate = None
    for row in history:
        day = str(row.get("snapshot_date") or "")[:10]
        if day and day <= target_day:
            candidate = row
        elif day and day > target_day:
            break
    return candidate


def _history_on_or_after(history: list[dict], target_day: str, *, max_lag_days: int = 2) -> dict | None:
    try:
        target = datetime.fromisoformat(target_day).date()
    except ValueError:
        return None
    for row in history:
        day_text = str(row.get("snapshot_date") or "")[:10]
        if not day_text:
            continue
        try:
            day = datetime.fromisoformat(day_text).date()
        except ValueError:
            continue
        lag = (day - target).days
        if 0 <= lag <= max_lag_days:
            return row
        if lag > max_lag_days:
            break
    return None


def _mv_at_deal(history: list[dict], transfer_day: str) -> int | None:
    if not transfer_day:
        return None
    row = _history_on_or_before(history, transfer_day)
    if row is None:
        row = _history_on_or_after(history, transfer_day, max_lag_days=1)
    return int(row.get("value") or 0) if row and int(row.get("value") or 0) > 0 else None


def _post_sale_point(history: list[dict], sale_day: str, days: int) -> dict | None:
    try:
        target = datetime.fromisoformat(sale_day).date() + timedelta(days=days)
    except ValueError:
        return None
    return _history_on_or_after(history, target.isoformat(), max_lag_days=1)


def _post_metrics(history: list[dict], sale_day: str, base_value: int | None, days: int) -> tuple[int | None, int | None, float | None]:
    row = _post_sale_point(history, sale_day, days)
    if row is None:
        return None, None, None
    value = int(row.get("value") or 0)
    if value <= 0:
        return None, None, None
    delta = value - int(base_value) if base_value else None
    return value, delta, _pct(delta, base_value)


def _exit_verdict(post_7_pct: float | None, post_3_pct: float | None) -> str:
    # Seven days is the real timing verdict. +3d is only an early indication.
    value = post_7_pct if post_7_pct is not None else post_3_pct
    if value is None:
        return "EXIT NOCH OFFEN"
    suffix = "" if post_7_pct is not None else " (VORL.)"
    if value <= -8:
        return "TOP-EXIT" + suffix
    if value <= -2.5:
        return "GUTES TIMING" + suffix
    if value >= 10:
        return "DEUTLICH ZU FRÜH" + suffix
    if value >= 3:
        return "ZU FRÜH" + suffix
    return "SOLIDES TIMING" + suffix


def _financial_verdict(roi: float | None, *, closed: bool) -> str:
    if roi is None:
        return "NICHT BEWERTBAR"
    if not closed:
        if roi >= 10:
            return "FINANZIELL STARK"
        if roi <= -10:
            return "FINANZIELL SCHWACH"
        return "FINANZIELL NEUTRAL"
    if roi >= 12:
        return "STARKER GEWINN"
    if roi >= 3:
        return "GEWINN"
    if roi <= -12:
        return "KLARER VERLUST"
    if roi <= -3:
        return "VERLUST"
    return "FINANZIELL NEUTRAL"


def _performance_matches(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    matches: list[dict] = []
    for group in payload.get("it", []) or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get("ph", []) or []:
            if not isinstance(raw, dict):
                continue
            try:
                points = int(float(raw.get("p")))
            except (TypeError, ValueError):
                continue
            dt = _parse_dt(raw.get("md") or raw.get("date") or raw.get("d"))
            if dt is None:
                continue
            matches.append({"date": dt, "points": points})
    return sorted(matches, key=lambda row: row["date"])


def _sport_between(payload: dict | None, start, end=None) -> dict:
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end) if end else datetime.now(timezone.utc)
    if start_dt is None or end_dt is None:
        return {"points": None, "games": 0, "avg": None, "verdict": "NOCH KEINE DATEN"}
    matches = [m for m in _performance_matches(payload) if start_dt <= m["date"] <= end_dt]
    if not matches:
        return {"points": None, "games": 0, "avg": None, "verdict": "NOCH KEINE DATEN"}
    points = sum(int(m["points"]) for m in matches)
    avg = points / len(matches)
    if len(matches) < 2:
        verdict = "SPORTLICH OFFEN"
    elif avg >= 100:
        verdict = "SPORTLICH STARK"
    elif avg >= 60:
        verdict = "SPORTLICH OK"
    else:
        verdict = "SPORTLICH SCHWACH"
    return {"points": points, "games": len(matches), "avg": avg, "verdict": verdict}


def _combined_trade_verdict(roi: float | None, sport: dict, exit_verdict: str) -> str:
    # A financial drawdown alone is NOT a failed transfer. Fehlkauf requires
    # both a material realized loss and real sporting evidence that the player
    # did not compensate for it.
    games = int(sport.get("games") or 0)
    avg = sport.get("avg")
    if roi is not None and roi <= -10 and games >= 2 and avg is not None and float(avg) < 60:
        return "FEHLKAUF"
    if roi is not None and roi >= 10:
        if "TOP-EXIT" in exit_verdict or "GUTES TIMING" in exit_verdict:
            return "TOP-TRADE"
        return "STARKER TRADE"
    if roi is not None and roi >= 3:
        return "GUTER TRADE"
    if roi is not None and roi <= -10:
        return "VERLUST-TRADE"
    if roi is not None and roi <= -3:
        return "SCHWACHER TRADE"
    if games >= 2 and avg is not None and float(avg) >= 100:
        return "SPORTLICH GUTER TRADE"
    return "SOLIDER TRADE"



def _live_holding_verdict(role: str | None, financial_verdict: str | None = None) -> str:
    role = str(role or "OFFEN").upper()
    if role == "STAMM":
        return "LIVE · STAMM"
    if role == "INVEST":
        return "LIVE · INVEST"
    if role == "TRANSFERLISTE":
        return "LIVE · VERKAUF GEPLANT"
    if role == "OFFEN":
        return "OFFENER TRADE"
    if financial_verdict and financial_verdict not in {"OFFEN", "NOCH OFFEN"}:
        return f"LIVE · {financial_verdict}"
    return "LIVE"

def evaluate_trade_cycles(
    transfers: Iterable[dict],
    market_history_by_player: dict[str, list[dict]] | None = None,
    performance_by_player: dict[str, dict] | None = None,
    acquisition_by_player: dict[str, dict] | None = None,
) -> list[dict]:
    """Pair BUY→SELL events into one evaluated trade cycle per holding period.

    Open buys remain one live trade row. If a player's first observed transfer is
    a SELL and persisted market-value history already exists before that sale, the
    position is treated as reconstructed start inventory and graded from the earliest
    known start MW. Sales without either a BUY or historical start evidence remain
    separate exit rows, so acquisition cost is never invented.
    Exit timing is measured from the player's market value at sale to +3d/+7d.
    """
    histories = market_history_by_player or {}
    performances = performance_by_player or {}
    acquisitions = acquisition_by_player or {}
    events = [dict(row) for row in transfers]
    events.sort(key=lambda row: str(row.get("transferred_at") or ""))

    by_player: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        by_player[str(row.get("player_id") or "")].append(row)

    cycles: list[dict] = []
    for player_id, player_events in by_player.items():
        history = _history_sorted(histories.get(player_id, []))
        latest = history[-1] if history else None
        latest_value = int(latest.get("value") or 0) if latest else None
        latest_at = latest.get("recorded_at") if latest else None
        open_buys: list[dict] = []

        for event in player_events:
            kind = str(event.get("transfer_type") or "").upper()
            if kind == "BUY":
                open_buys.append(event)
                continue
            if kind != "SELL":
                continue

            buy = open_buys.pop(0) if open_buys else None
            sell_price = int(event.get("price") or 0)
            sell_day = _day(event.get("transferred_at"))
            mv_sale = _mv_at_deal(history, sell_day)
            timing_base = mv_sale or sell_price or None
            post3_value, post3_delta, post3_pct = _post_metrics(history, sell_day, timing_base, 3)
            post7_value, post7_delta, post7_pct = _post_metrics(history, sell_day, timing_base, 7)
            exit_verdict = _exit_verdict(post7_pct, post3_pct)

            if buy:
                buy_price = int(buy.get("price") or 0)
                buy_day = _day(buy.get("transferred_at"))
                mv_buy = _mv_at_deal(history, buy_day)
                pnl = sell_price - buy_price
                roi = _pct(pnl, buy_price)
                buy_dt = _parse_dt(buy.get("transferred_at"))
                sell_dt = _parse_dt(event.get("transferred_at"))
                holding_days = max(0, (sell_dt - buy_dt).days) if buy_dt and sell_dt else None
                sport = _sport_between(performances.get(player_id), buy.get("transferred_at"), event.get("transferred_at"))
                verdict = _combined_trade_verdict(roi, sport, exit_verdict)
                cycles.append({
                    "cycle_type": "CLOSED_TRADE",
                    "player_id": player_id,
                    "player_name": event.get("player_name") or buy.get("player_name") or "Unbekannt",
                    "club": event.get("club") or buy.get("club") or "",
                    "team_id": event.get("team_id") or buy.get("team_id"),
                    "team_image": event.get("team_image") or buy.get("team_image"),
                    "buy_date": buy.get("transferred_at"),
                    "sell_date": event.get("transferred_at"),
                    "sort_date": event.get("transferred_at"),
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "current_market_value": latest_value,
                    "market_value_at_buy": mv_buy,
                    "market_value_at_sale": mv_sale,
                    "result_pnl": pnl,
                    "roi_pct": roi,
                    "holding_days": holding_days,
                    "financial_verdict": _financial_verdict(roi, closed=True),
                    "sport_points": sport.get("points"),
                    "sport_games": sport.get("games"),
                    "sport_avg": sport.get("avg"),
                    "sport_verdict": sport.get("verdict"),
                    "post_3d_value": post3_value,
                    "post_3d_delta": post3_delta,
                    "post_3d_pct": post3_pct,
                    "post_7d_value": post7_value,
                    "post_7d_delta": post7_delta,
                    "post_7d_pct": post7_pct,
                    "exit_verdict": exit_verdict,
                    "verdict": verdict,
                })
            else:
                acquisition = acquisitions.get(player_id) or {}
                explicit_start_squad = str(acquisition.get("origin") or "").upper() == "STARTKADER"

                # Historical reconstruction for players sold before we ever saw a BUY.
                # If the first observed manager transfer is a SELL and an MW point already
                # exists on/before that sale, the player must have been held before our
                # transfer history began (normally the league's start inventory). This is
                # stronger evidence than treating every unmatched sale as unknown.
                first_event_is_sell = bool(player_events) and str(player_events[0].get("transfer_type") or "").upper() == "SELL"
                first_pre_sale_history = next(
                    (
                        h for h in history
                        if str(h.get("snapshot_date") or "")[:10]
                        and str(h.get("snapshot_date") or "")[:10] <= sell_day
                        and int(h.get("value") or 0) > 0
                    ),
                    None,
                )
                inferred_start_squad = bool(first_event_is_sell and first_pre_sale_history is not None)
                is_start_squad = explicit_start_squad or inferred_start_squad

                start_value = None
                start_date = None
                entry_source = "STARTKADER_MW" if explicit_start_squad else "STARTBESTAND_REKONSTRUIERT"
                if is_start_squad:
                    if explicit_start_squad:
                        try:
                            candidate = int(acquisition.get("entry_value") or 0)
                        except (TypeError, ValueError):
                            candidate = 0
                        if candidate > 0:
                            start_value = candidate
                    # Fallback / reconstructed start inventory: earliest persisted MW
                    # that is not after the sale. The history is already sorted ascending.
                    if start_value is None and first_pre_sale_history is not None:
                        start_value = int(first_pre_sale_history.get("value") or 0) or None
                    if first_pre_sale_history is not None:
                        start_date = first_pre_sale_history.get("recorded_at") or first_pre_sale_history.get("snapshot_date")
                    start_date = start_date or acquisition.get("purchase_date")

                if is_start_squad and start_value:
                    pnl = sell_price - start_value
                    roi = _pct(pnl, start_value)
                    start_dt = _parse_dt(start_date)
                    sell_dt = _parse_dt(event.get("transferred_at"))
                    holding_days = max(0, (sell_dt - start_dt).days) if start_dt and sell_dt else None
                    sport = _sport_between(performances.get(player_id), start_date, event.get("transferred_at")) if start_date else {
                        "points": None, "games": 0, "avg": None, "verdict": "NOCH KEINE DATEN"
                    }
                    verdict = _combined_trade_verdict(roi, sport, exit_verdict)
                    cycles.append({
                        "cycle_type": "CLOSED_START_SQUAD_TRADE",
                        "player_id": player_id,
                        "player_name": event.get("player_name") or "Unbekannt",
                        "club": event.get("club") or acquisition.get("club") or "",
                        "team_id": event.get("team_id") or acquisition.get("team_id"),
                        "team_image": event.get("team_image") or acquisition.get("team_image"),
                        "buy_date": start_date,
                        "sell_date": event.get("transferred_at"),
                        "sort_date": event.get("transferred_at"),
                        "buy_price": start_value,
                        "entry_source": entry_source,
                        "sell_price": sell_price,
                        "market_value_at_buy": start_value,
                        "market_value_at_sale": mv_sale,
                        "result_pnl": pnl,
                        "roi_pct": roi,
                        "holding_days": holding_days,
                        "financial_verdict": _financial_verdict(roi, closed=True),
                        "sport_points": sport.get("points"),
                        "sport_games": sport.get("games"),
                        "sport_avg": sport.get("avg"),
                        "sport_verdict": sport.get("verdict"),
                        "post_3d_value": post3_value,
                        "post_3d_delta": post3_delta,
                        "post_3d_pct": post3_pct,
                        "post_7d_value": post7_value,
                        "post_7d_delta": post7_delta,
                        "post_7d_pct": post7_pct,
                        "exit_verdict": exit_verdict,
                        "verdict": verdict,
                    })
                else:
                    cycles.append({
                        "cycle_type": "UNPAIRED_SALE",
                        "player_id": player_id,
                        "player_name": event.get("player_name") or "Unbekannt",
                        "club": event.get("club") or "",
                        "team_id": event.get("team_id"),
                        "team_image": event.get("team_image"),
                        "buy_date": None,
                        "sell_date": event.get("transferred_at"),
                        "sort_date": event.get("transferred_at"),
                        "buy_price": None,
                        "entry_source": "UNKNOWN",
                        "sell_price": sell_price,
                        "market_value_at_sale": mv_sale,
                        "result_pnl": None,
                        "roi_pct": None,
                        "holding_days": None,
                        "financial_verdict": "KAUFPREIS UNBEKANNT",
                        "sport_points": None,
                        "sport_games": 0,
                        "sport_avg": None,
                        "sport_verdict": "NICHT BEWERTBAR",
                        "post_3d_value": post3_value,
                        "post_3d_delta": post3_delta,
                        "post_3d_pct": post3_pct,
                        "post_7d_value": post7_value,
                        "post_7d_delta": post7_delta,
                        "post_7d_pct": post7_pct,
                        "exit_verdict": exit_verdict,
                        "verdict": exit_verdict,
                    })

        # Every remaining BUY is still in progress. Never label it a Fehlkauf.
        for buy in open_buys:
            buy_price = int(buy.get("price") or 0)
            buy_day = _day(buy.get("transferred_at"))
            mv_buy = _mv_at_deal(history, buy_day)
            pnl = latest_value - buy_price if latest_value else None
            roi = _pct(pnl, buy_price)
            buy_dt = _parse_dt(buy.get("transferred_at"))
            end_dt = _parse_dt(latest_at) or datetime.now(timezone.utc)
            holding_days = max(0, (end_dt - buy_dt).days) if buy_dt and end_dt else None
            sport = _sport_between(performances.get(player_id), buy.get("transferred_at"), None)
            acquisition = acquisitions.get(player_id) or {}
            player_role = str(acquisition.get("player_role") or "OFFEN").upper()
            financial_verdict = _financial_verdict(roi, closed=False)
            cycles.append({
                "cycle_type": "OPEN_TRADE",
                "player_id": player_id,
                "player_name": buy.get("player_name") or "Unbekannt",
                "club": buy.get("club") or "",
                "team_id": buy.get("team_id"),
                "team_image": buy.get("team_image"),
                "buy_date": buy.get("transferred_at"),
                "sell_date": None,
                "sort_date": buy.get("transferred_at"),
                "buy_price": buy_price,
                "sell_price": None,
                "current_market_value": latest_value,
                "market_value_at_buy": mv_buy,
                "result_pnl": pnl,
                "roi_pct": roi,
                "holding_days": holding_days,
                "financial_verdict": financial_verdict,
                "player_role": player_role,
                "sport_points": sport.get("points"),
                "sport_games": sport.get("games"),
                "sport_avg": sport.get("avg"),
                "sport_verdict": sport.get("verdict"),
                "post_3d_value": None,
                "post_3d_delta": None,
                "post_3d_pct": None,
                "post_7d_value": None,
                "post_7d_delta": None,
                "post_7d_pct": None,
                "exit_verdict": "–",
                "verdict": _live_holding_verdict(player_role, financial_verdict),
            })

        # Current STARTKADER holdings may never have produced a BUY event. They
        # are still live positions and must be evaluated against their start MW.
        # Exit timing only exists after an actual SELL event.
        represented_current = bool(open_buys)
        acquisition = acquisitions.get(player_id) or {}
        if (
            str(acquisition.get("player_status") or "").upper() == "KADER"
            and str(acquisition.get("origin") or "").upper() == "STARTKADER"
            and not represented_current
        ):
            # This branch is only reachable for players that also have historic
            # events. Pure start-squad holdings are added in the second pass below.
            pass

    # Add current start-squad players even when they have no transfer events at all.
    existing_live_ids = {
        str(row.get("player_id") or "")
        for row in cycles
        if row.get("cycle_type") in {"OPEN_TRADE", "OPEN_START_SQUAD"}
    }
    for player_id, acquisition in acquisitions.items():
        if str(acquisition.get("player_status") or "").upper() != "KADER":
            continue
        if str(acquisition.get("origin") or "").upper() != "STARTKADER":
            continue
        if str(player_id) in existing_live_ids:
            continue
        history = _history_sorted(histories.get(str(player_id), []))
        latest = history[-1] if history else None
        latest_value = int(latest.get("value") or 0) if latest else int(acquisition.get("market_value") or 0) or None
        latest_at = latest.get("recorded_at") if latest else None
        try:
            start_value = int(acquisition.get("entry_value") or 0) or None
        except (TypeError, ValueError):
            start_value = None
        if start_value is None:
            for hist_row in history:
                value = int(hist_row.get("value") or 0)
                if value > 0:
                    start_value = value
                    break
        start_date = acquisition.get("purchase_date")
        if not start_date and history:
            start_date = history[0].get("recorded_at") or history[0].get("snapshot_date")
        pnl = latest_value - start_value if latest_value is not None and start_value else None
        roi = _pct(pnl, start_value)
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(latest_at) or datetime.now(timezone.utc)
        holding_days = max(0, (end_dt - start_dt).days) if start_dt and end_dt else None
        sport = _sport_between(performances.get(str(player_id)), start_date, None) if start_date else {
            "points": None, "games": 0, "avg": None, "verdict": "NOCH KEINE DATEN"
        }
        player_role = str(acquisition.get("player_role") or "OFFEN").upper()
        financial_verdict = _financial_verdict(roi, closed=False)
        cycles.append({
            "cycle_type": "OPEN_START_SQUAD",
            "player_id": str(player_id),
            "player_name": acquisition.get("full_name") or acquisition.get("name") or "Unbekannt",
            "club": acquisition.get("club") or "",
            "team_id": acquisition.get("team_id"),
            "team_image": acquisition.get("team_image"),
            "buy_date": start_date,
            "sell_date": None,
            "sort_date": start_date or latest_at or "",
            "buy_price": start_value,
            "entry_source": "STARTKADER_MW",
            "sell_price": None,
            "current_market_value": latest_value,
            "market_value_at_buy": start_value,
            "result_pnl": pnl,
            "roi_pct": roi,
            "holding_days": holding_days,
            "financial_verdict": financial_verdict,
            "player_role": player_role,
            "sport_points": sport.get("points"),
            "sport_games": sport.get("games"),
            "sport_avg": sport.get("avg"),
            "sport_verdict": sport.get("verdict"),
            "post_3d_value": None,
            "post_3d_delta": None,
            "post_3d_pct": None,
            "post_7d_value": None,
            "post_7d_delta": None,
            "post_7d_pct": None,
            "exit_verdict": "–",
            "verdict": _live_holding_verdict(player_role, financial_verdict),
        })

    cycles.sort(key=lambda row: str(row.get("sort_date") or ""), reverse=True)
    return cycles


def evaluate_transfer_history(
    transfers: Iterable[dict],
    market_history_by_player: dict[str, list[dict]] | None = None,
    performance_by_player: dict[str, dict] | None = None,
    acquisition_by_player: dict[str, dict] | None = None,
) -> list[dict]:
    """Compatibility wrapper. New code should use evaluate_trade_cycles()."""
    return evaluate_trade_cycles(transfers, market_history_by_player, performance_by_player, acquisition_by_player)


def transfer_evaluation_summary(rows: Iterable[dict]) -> dict:
    rows = [dict(row) for row in rows]
    closed = [row for row in rows if row.get("cycle_type") in {"CLOSED_TRADE", "CLOSED_START_SQUAD_TRADE"}]
    roi_rows = [row for row in closed if row.get("roi_pct") is not None]
    timed = [row for row in rows if row.get("sell_date") and (row.get("post_7d_pct") is not None or row.get("post_3d_pct") is not None)]
    good_exits = [row for row in timed if "TOP-EXIT" in str(row.get("exit_verdict")) or "GUTES TIMING" in str(row.get("exit_verdict"))]
    early_exits = [row for row in timed if "ZU FRÜH" in str(row.get("exit_verdict"))]
    avg_roi = sum(float(row["roi_pct"]) for row in roi_rows) / len(roi_rows) if roi_rows else None
    open_trades = [row for row in rows if row.get("cycle_type") == "OPEN_TRADE"]
    return {
        "evaluated_trades": len(closed),
        "open_trades": len(open_trades),
        "avg_realized_roi_pct": avg_roi,
        "timed_sales": len(timed),
        "good_exits": len(good_exits),
        "early_exits": len(early_exits),
    }
