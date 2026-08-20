from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import sqrt
from statistics import mean, median, pstdev
from typing import Any

POSITION_ORDER = {"TW": 0, "ABW": 1, "MF": 2, "ST": 3}
POSITION_TARGETS = {"TW": 1, "ABW": 3, "MF": 4, "ST": 3}
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
STATUS_OK = {None, 0, "0"}

# Kickbase player-status values. The current v4 payload still uses the same
# numeric values exposed by the legacy public client model. Keep unknown values
# explicit instead of inventing a medical description.
STATUS_LABELS = {
    0: "VERFÜGBAR",
    1: "VERLETZT",
    2: "ANGESCHLAGEN",
    4: "REHA",
    8: "ROT GESPERRT",
    16: "GELB-ROT GESPERRT",
    32: "5. GELBE KARTE",
    64: "NICHT IM TEAM",
    128: "NICHT IN LIGA",
    256: "ABWESEND",
}

QUESTIONABLE_STATUS = {2}

def _status_values(player: dict) -> list[int]:
    raw_list = player.get("status_list") or player.get("stl") or []
    values: list[int] = []
    if isinstance(raw_list, (list, tuple)):
        for value in raw_list:
            try:
                values.append(int(value))
            except (TypeError, ValueError):
                pass
    raw_status = player.get("kickbase_status", player.get("status", player.get("player_status_code", player.get("st"))))
    try:
        status_value = int(raw_status or 0)
    except (TypeError, ValueError):
        status_value = 0
    if status_value and status_value not in values:
        values.insert(0, status_value)
    return values

def status_labels(player: dict) -> list[str]:
    values = _status_values(player)
    if not values:
        return ["VERFÜGBAR"]
    return [STATUS_LABELS.get(value, f"STATUS {value}") for value in values]


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def player_form(performance_payload: Any) -> dict:
    """Normalize /players/{id}/performance into human-readable form metrics.

    Kickbase returns multiple seasons. For the in-app form chart we prefer the
    season containing the current fixture marker (``cur``); if none is marked,
    the newest season that already contains scored matches is used.
    """
    groups = performance_payload.get("it", []) if isinstance(performance_payload, dict) else []
    valid_groups = [group for group in groups if isinstance(group, dict)] if isinstance(groups, list) else []

    selected_group = None
    for group in reversed(valid_groups):
        phase = group.get("ph", []) or []
        if any(isinstance(raw, dict) and raw.get("cur") for raw in phase):
            selected_group = group
            break
    if selected_group is None:
        for group in reversed(valid_groups):
            phase = group.get("ph", []) or []
            if any(isinstance(raw, dict) and _num(raw.get("p")) is not None for raw in phase):
                selected_group = group
                break

    matches: list[dict] = []
    groups_to_read = [selected_group] if selected_group is not None else valid_groups[-1:]
    for group in groups_to_read:
        season_id = str(group.get("sid") or "")
        season_title = str(group.get("ti") or "")
        competition_name = str(group.get("n") or "")
        for raw in group.get("ph", []) or []:
            if not isinstance(raw, dict):
                continue
            points = _num(raw.get("p"))
            if points is None:
                continue
            matches.append({
                "match_id": str(raw.get("mi") or ""),
                "day": int(raw.get("day") or 0),
                "points": int(points),
                "minutes": raw.get("mp"),
                "opponent_home": raw.get("t1"),
                "opponent_away": raw.get("t2"),
                "home_goals": raw.get("t1g"),
                "away_goals": raw.get("t2g"),
                "match_date": raw.get("md"),
                "current": bool(raw.get("cur")),
                "status": raw.get("st"),
                "season_id": season_id,
                "season_title": season_title,
                "competition_name": competition_name,
            })
    matches.sort(key=lambda x: x["day"])
    values = [m["points"] for m in matches]
    recent5 = values[-5:]
    recent3 = values[-3:]
    avg = mean(values) if values else None
    avg5 = mean(recent5) if recent5 else None
    avg3 = mean(recent3) if recent3 else None
    volatility = pstdev(recent5) if len(recent5) >= 2 else None
    trend = (avg3 - avg) if avg3 is not None and avg is not None else None

    def percentile(data: list[int], q: float) -> float | None:
        if not data:
            return None
        ordered = sorted(data)
        if len(ordered) == 1:
            return float(ordered[0])
        idx = (len(ordered) - 1) * q
        lower = int(idx)
        upper = min(lower + 1, len(ordered) - 1)
        frac = idx - lower
        return ordered[lower] * (1.0 - frac) + ordered[upper] * frac

    med = percentile(values, 0.5)
    p25 = percentile(values, 0.25)
    p75 = percentile(values, 0.75)
    p90 = percentile(values, 0.9)
    hit70 = (sum(1 for value in values if value >= 70) / len(values) * 100.0) if values else None
    hit100 = (sum(1 for value in values if value >= 100) / len(values) * 100.0) if values else None
    risk = None
    if avg is not None and volatility is not None:
        risk = max(0.0, volatility / max(1.0, abs(avg)))

    return {
        "matches": matches,
        "avg": avg,
        "avg5": avg5,
        "avg3": avg3,
        "trend": trend,
        "volatility": volatility,
        "floor": min(values) if values else None,
        "ceiling": max(values) if values else None,
        "median": med,
        "robust_floor": p25,
        "robust_ceiling": p75,
        "p75": p75,
        "p90": p90,
        "hit70": hit70,
        "hit100": hit100,
        "risk": risk,
    }


def normalize_event_types(payload: Any) -> dict[str, str]:
    """Return Kickbase event-type labels keyed by their event type id.

    The live endpoint has been observed with ``i`` (id) and ``ti`` (title), but
    this parser intentionally accepts common wrapper keys so a small response
    shape change does not break the feature.
    """
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("it", "items", "value", "eventTypes", "eventtypes", "types"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
            if isinstance(value, dict):
                nested = normalize_event_types(value)
                if nested:
                    return nested
        if not items and payload.get("i") is not None:
            items = [payload]

    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("i", item.get("id", item.get("eti")))
        raw_title = item.get("ti", item.get("title", item.get("name", item.get("n"))))
        if raw_id is None or raw_title is None:
            continue
        title = str(raw_title).strip()
        if title:
            result[str(raw_id)] = title
    return result


def normalize_match_events(payload: Any, event_types: dict[str, str] | None = None) -> dict:
    """Normalize a playercenter match payload for the point-breakdown dialog."""
    data = payload if isinstance(payload, dict) else {}
    labels = event_types or {}
    events: list[dict] = []
    for raw in data.get("events", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            points = int(raw.get("p") or 0)
        except (TypeError, ValueError):
            points = 0
        try:
            minute = int(raw.get("mt") or 0)
        except (TypeError, ValueError):
            minute = 0
        event_type_id = str(raw.get("eti") if raw.get("eti") is not None else "")
        events.append({
            "event_id": str(raw.get("ei") or ""),
            "event_type_id": event_type_id,
            "label": labels.get(event_type_id) or (f"Event {event_type_id}" if event_type_id else "Event"),
            "points": points,
            "minute": minute,
            "attribute": raw.get("att"),
            "key_event": raw.get("ke"),
            "detail": raw.get("ddp") if isinstance(raw.get("ddp"), dict) else {},
        })
    events.sort(key=lambda event: (event["minute"], event["event_id"]), reverse=True)
    point_events = [event for event in events if event["points"] != 0]
    try:
        total_points = int(data.get("p")) if data.get("p") is not None else None
    except (TypeError, ValueError):
        total_points = None
    event_points = sum(event["points"] for event in point_events)
    return {
        "player_id": str(data.get("i") or ""),
        "player_name": str(data.get("n") or ""),
        "match_id": str(data.get("mi") or ""),
        "home_team": data.get("t1"),
        "away_team": data.get("t2"),
        "home_goals": data.get("t1g"),
        "away_goals": data.get("t2g"),
        "minutes": data.get("mt"),
        "match_date": data.get("md"),
        "total_points": total_points,
        "event_points": event_points,
        "unmapped_points": (total_points - event_points) if total_points is not None else None,
        "events": events,
        "point_events": point_events,
    }


def parse_fixtures(payload: Any) -> dict:
    value = payload.get("value", payload) if isinstance(payload, dict) else {}
    groups = value.get("it", []) if isinstance(value, dict) else []
    current_day = int(value.get("day") or 0) if isinstance(value, dict) else 0
    fixtures: list[dict] = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        day = int(group.get("day") or 0)
        for match in group.get("it", []) or []:
            if not isinstance(match, dict):
                continue
            fixtures.append({
                "match_id": str(match.get("mi") or ""),
                "day": int(match.get("day") or day),
                "date": match.get("dt"),
                "home_id": str(match.get("t1") or ""),
                "away_id": str(match.get("t2") or ""),
                "home": match.get("t1sy") or match.get("t1") or "–",
                "away": match.get("t2sy") or match.get("t2") or "–",
                "home_goals": match.get("t1g"),
                "away_goals": match.get("t2g"),
                "status": match.get("st"),
            })
    return {"current_day": current_day, "fixtures": fixtures}


def parse_competition_table(payload: Any) -> dict[str, dict]:
    value = payload.get("value", payload) if isinstance(payload, dict) else {}
    rows = value.get("it", []) if isinstance(value, dict) else []
    result = {}
    for idx, row in enumerate(rows if isinstance(rows, list) else [], start=1):
        if not isinstance(row, dict):
            continue
        tid = str(row.get("tid") or "")
        if not tid:
            continue
        result[tid] = {
            "name": row.get("tn") or tid,
            "place": int(row.get("cp") or row.get("pl") or idx),
            "points": int(row.get("sp") or 0),
            "goal_diff": int(row.get("gd") or 0),
        }
    return result


def fixture_run(team_id: str | None, fixtures_payload: Any, table_payload: Any, limit: int = 3) -> list[dict]:
    if not team_id:
        return []
    team_id = str(team_id)
    parsed = parse_fixtures(fixtures_payload)
    table = parse_competition_table(table_payload)
    current_day = parsed["current_day"]
    upcoming = [f for f in parsed["fixtures"] if f["day"] >= current_day and team_id in (f["home_id"], f["away_id"])]
    upcoming.sort(key=lambda f: f["day"])
    total_teams = max(1, len(table))
    out = []
    for f in upcoming[:limit]:
        opponent_id = f["away_id"] if f["home_id"] == team_id else f["home_id"]
        opponent = table.get(opponent_id, {})
        place = int(opponent.get("place") or max(1, total_teams // 2))
        # 100 = easiest opponent, 0 = hardest. Start with table strength and
        # apply only a modest home/away adjustment so fixtures remain transparent.
        base_ease = (place - 1) / max(1, total_teams - 1) * 100
        home_game = f["home_id"] == team_id
        ease = round(base_ease)
        adjusted_ease = round(max(0.0, min(100.0, base_ease + (6.0 if home_game else -6.0))))
        out.append({**f, "opponent_id": opponent_id, "opponent": opponent.get("name") or opponent_id, "opponent_place": place, "ease": ease, "adjusted_ease": adjusted_ease, "home_game": home_game})
    return out


def transfer_price_history(rows: list[dict], player_id: str, limit: int = 8) -> dict:
    relevant = [r for r in rows if str(r.get("player_id")) == str(player_id)]
    relevant.sort(key=lambda r: str(r.get("transferred_at") or ""), reverse=True)
    prices = [int(r.get("price") or 0) for r in relevant if int(r.get("price") or 0) > 0]
    return {
        "rows": relevant[:limit],
        "count": len(relevant),
        "average_price": round(mean(prices)) if prices else None,
        "last_price": prices[0] if prices else None,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
    }


def squad_status(players: list[dict]) -> dict:
    available = questionable = unavailable = 0
    affected = []
    for p in players:
        values = _status_values(p)
        if not values:
            available += 1
            continue

        labels = [STATUS_LABELS.get(value, f"STATUS {value}") for value in values]
        if all(value in QUESTIONABLE_STATUS for value in values):
            questionable += 1
            availability = "FRAGLICH"
        else:
            unavailable += 1
            availability = "NICHT VERFÜGBAR"

        affected.append({
            **p,
            "availability_label": availability,
            "status_labels": labels,
            "status_detail": " · ".join(labels),
        })
    return {"available": available, "questionable": questionable, "unavailable": unavailable, "affected": affected}


def trade_profile(transfers: list[dict]) -> dict:
    buys = [r for r in transfers if str(r.get("transfer_type") or "").upper() == "BUY"]
    sells = [r for r in transfers if str(r.get("transfer_type") or "").upper() == "SELL"]
    volume = sum(int(r.get("price") or 0) for r in transfers)
    count = len(transfers)
    sell_ratio = len(sells) / count if count else 0

    # Match a manager's buys/sells by player chronologically. This produces a
    # conservative realized-P/L and holding-time estimate without inventing
    # budgets or using external information.
    by_player = defaultdict(list)
    for row in sorted(transfers, key=lambda r: str(r.get("transferred_at") or "")):
        by_player[str(row.get("player_id") or "")].append(row)
    realized = []
    holds = []
    from datetime import datetime
    for rows in by_player.values():
        open_buys = []
        for row in rows:
            typ = str(row.get("transfer_type") or "").upper()
            if typ == "BUY":
                open_buys.append(row)
            elif typ == "SELL" and open_buys:
                buy = open_buys.pop(0)
                buy_price = int(buy.get("price") or 0)
                sell_price = int(row.get("price") or 0)
                realized.append(sell_price - buy_price)
                try:
                    bdt = datetime.fromisoformat(str(buy.get("transferred_at") or "").replace("Z", "+00:00"))
                    sdt = datetime.fromisoformat(str(row.get("transferred_at") or "").replace("Z", "+00:00"))
                    holds.append(max(0.0, (sdt - bdt).total_seconds() / 86400.0))
                except (TypeError, ValueError):
                    pass

    avg_hold = mean(holds) if holds else None
    realized_pnl = sum(realized)
    avg_trade_pnl = mean(realized) if realized else None
    if count >= 20 or (avg_hold is not None and avg_hold <= 4 and count >= 8):
        label = "TRADER"
    elif count >= 10:
        label = "AKTIV"
    elif count >= 4:
        label = "AUSGEWOGEN"
    else:
        label = "BUY & HOLD"
    if count >= 8 and sell_ratio >= .55 and (avg_hold is None or avg_hold <= 7):
        label = "HOHE FLUKTUATION"
    return {
        "label": label, "count": count, "buy_count": len(buys), "sell_count": len(sells),
        "volume": volume, "sell_ratio": sell_ratio, "realized_pnl": realized_pnl,
        "avg_trade_pnl": avg_trade_pnl, "avg_hold_days": avg_hold, "matched_trades": len(realized),
    }


def optimize_lineup(
    players: list[dict],
    form_by_player: dict[str, dict] | None = None,
    fixture_by_team: dict[str, list[dict]] | None = None,
    *,
    points_are_current: bool = True,
    formation: str | None = None,
) -> dict:
    """Read-only XI optimizer. Uses current squad only; never writes to Kickbase.

    ``formation=None`` keeps AUTO mode and selects the strongest legal formation.
    Passing a formation forces exactly that positional shape. If the current squad
    cannot field it, the result is marked infeasible instead of silently falling
    back to another system.
    """
    if formation is not None and formation not in VALID_FORMATIONS:
        raise ValueError(f"Unsupported Kickbase formation: {formation}")

    form_by_player = form_by_player or {}
    fixture_by_team = fixture_by_team or {}
    scored = []
    for p in players:
        pid = str(p.get("player_id") or "")
        mv = int(p.get("market_value") or 0)
        avg = float(p.get("average_points") or 0) if points_are_current else 0.0
        form = form_by_player.get(pid, {})
        avg3 = form.get("avg3") if points_are_current else None
        med = form.get("median") if points_are_current else None
        floor = form.get("robust_floor", form.get("floor")) if points_are_current else None
        # Blend recent form with median/floor so one explosive game cannot dominate.
        if points_are_current:
            form_score = (
                float(avg3 if avg3 is not None else avg) * 0.55
                + float(med if med is not None else avg) * 0.30
                + float(floor if floor is not None else avg) * 0.15
            )
        else:
            form_score = 0.0
        fixtures = fixture_by_team.get(str(p.get("team_id") or ""), [])
        fixture_score = mean([f.get("adjusted_ease", f.get("ease", 50)) for f in fixtures[:3]]) if fixtures else 50
        values = _status_values(p)
        if not values:
            available_factor = 1.0
        elif all(value in QUESTIONABLE_STATUS for value in values):
            available_factor = 0.78
        else:
            available_factor = 0.0
        # Season: robust form dominates, fixture is meaningful but secondary.
        # Preseason: no stale points; market value is only a weak quality proxy.
        if points_are_current:
            base = form_score * 0.88 + fixture_score * 0.12
        else:
            base = min(100, mv / 200_000) * 0.35 + fixture_score * 0.65
        scored.append({**p, "optimizer_score": base * available_factor, "fixture_score": fixture_score, "form_score": form_score, "availability_factor": available_factor})

    by_pos = defaultdict(list)
    for p in scored:
        by_pos[str(p.get("position") or "")].append(p)
    for values in by_pos.values():
        values.sort(key=lambda p: p["optimizer_score"], reverse=True)

    formations = {formation: VALID_FORMATIONS[formation]} if formation else VALID_FORMATIONS
    candidates: list[tuple[float, str, list[dict]]] = []
    missing_by_formation: dict[str, dict[str, int]] = {}
    for formation_name, targets in formations.items():
        missing = {
            pos: count - len(by_pos.get(pos, []))
            for pos, count in targets.items()
            if len(by_pos.get(pos, [])) < count
        }
        if missing:
            missing_by_formation[formation_name] = missing
            continue
        lineup: list[dict] = []
        for pos, count in targets.items():
            lineup.extend(by_pos[pos][:count])
        lineup_score = mean([p["optimizer_score"] for p in lineup]) if lineup else 0.0
        candidates.append((lineup_score, formation_name, lineup))

    if candidates:
        lineup_score, selected_formation, chosen = max(candidates, key=lambda item: item[0])
        feasible = True
        missing = {}
    elif formation is not None:
        # A manually selected formation must never morph into a different one.
        selected_formation = formation
        chosen = []
        lineup_score = 0.0
        feasible = False
        missing = missing_by_formation.get(formation, {})
    else:
        # AUTO only: no legal XI can be formed yet. Keep the best partial lineup
        # as a diagnostic preview without pretending that it is legal.
        chosen = []
        for pos in ("TW", "ABW", "MF", "ST"):
            chosen.extend(by_pos.get(pos, []))
        chosen = sorted(chosen, key=lambda p: p["optimizer_score"], reverse=True)[:11]
        counts = {pos: sum(1 for p in chosen if str(p.get("position")) == pos) for pos in ("ABW", "MF", "ST")}
        selected_formation = f"{counts['ABW']}-{counts['MF']}-{counts['ST']} (unvollständig)"
        lineup_score = mean([p["optimizer_score"] for p in chosen]) if chosen else 0.0
        feasible = False
        missing = {}

    chosen.sort(key=lambda p: (POSITION_ORDER.get(str(p.get("position")), 9), -p["optimizer_score"]))
    return {
        "players": chosen,
        "formation": selected_formation,
        "score": round(lineup_score, 1),
        "feasible": feasible,
        "missing": missing,
    }


def parse_activity_feed(payload: Any) -> list[dict]:
    rows = payload.get("af", []) if isinstance(payload, dict) else []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        out.append({
            "activity_id": str(row.get("i") or ""),
            "type": row.get("t"),
            "date": row.get("dt"),
            "comments": int(row.get("coc") or 0),
            "player_id": str(data.get("pi") or "") if data.get("pi") is not None else None,
            "player_name": data.get("pn"),
            "team_id": str(data.get("tid") or "") if data.get("tid") is not None else None,
            "buyer": data.get("byr"),
            "price": int(data.get("trp") or 0),
            "day": data.get("day"),
        })
    return out
