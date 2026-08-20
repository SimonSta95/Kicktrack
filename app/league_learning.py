from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Iterable


PRICE_BUCKETS = (
    (0, 5_000_000, "<5 Mio."),
    (5_000_000, 10_000_000, "5–10 Mio."),
    (10_000_000, 20_000_000, "10–20 Mio."),
    (20_000_000, 10**18, ">20 Mio."),
)

PREMIUM_BANDS = (
    (-10**9, 0.0, "≤0%"),
    (0.0, 4.0, "0–4%"),
    (4.0, 8.0, "4–8%"),
    (8.0, 12.0, "8–12%"),
    (12.0, 10**9, ">12%"),
)


def _premium_band(premium_pct: float) -> str:
    for low, high, label in PREMIUM_BANDS:
        if low <= premium_pct < high:
            return label
    return ">12%"


def _value_on_or_before(history: list[dict], target: date, *, max_age_days: int = 2) -> int | None:
    candidates: list[tuple[int, int]] = []
    for row in history:
        try:
            day = date.fromisoformat(str(row.get("snapshot_date") or "")[:10])
            value = int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        age = (target - day).days
        if 0 <= age <= max_age_days and value > 0:
            candidates.append((age, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _daily_rate(start: int | None, end: int | None, days: int) -> float | None:
    if not start or not end or start <= 0 or end <= 0 or days <= 0:
        return None
    return ((float(end) / float(start)) ** (1.0 / days) - 1.0) * 100.0


def _momentum_profile_from_rates(rate3: float | None, rate7: float | None) -> tuple[str, float | None]:
    values = []
    if rate3 is not None:
        values.append((rate3, 0.65))
    if rate7 is not None:
        values.append((rate7, 0.35))
    if not values:
        return "KEINE DATEN", None
    total_weight = sum(weight for _, weight in values)
    daily = sum(value * weight for value, weight in values) / total_weight
    if daily >= 0.70:
        return "STARK STEIGEND", daily
    if daily >= 0.20:
        return "STEIGEND", daily
    if daily > -0.20:
        return "STABIL", daily
    return "FALLEND", daily


def classify_current_momentum(market_value: int | None, d3: int | float | None, d7: int | float | None) -> dict:
    mv = int(market_value or 0)
    if mv <= 0:
        return {"profile": "KEINE DATEN", "daily_pct": None}
    def rate(delta, days):
        if delta is None:
            return None
        start = float(mv) - float(delta)
        return _daily_rate(int(round(start)), mv, days) if start > 0 else None
    r3 = rate(d3, 3)
    r7 = rate(d7, 7)
    profile, daily = _momentum_profile_from_rates(r3, r7)
    return {"profile": profile, "daily_pct": daily, "rate3_pct": r3, "rate7_pct": r7}


def normalize_market_value_history(payload) -> list[dict]:
    """Normalize Kickbase's different MV-history response shapes."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = []
        for key in ("it", "items", "values", "history", "marketValues", "marketValueHistory"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        if not items and isinstance(payload.get("data"), dict):
            return normalize_market_value_history(payload["data"])
    else:
        return []

    normalized: list[dict] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        raw_value = next((entry.get(k) for k in ("mv", "v", "value", "marketValue", "market_value") if entry.get(k) is not None), None)
        try:
            value = int(float(raw_value))
        except (TypeError, ValueError):
            continue
        raw_date = next((entry.get(k) for k in ("d", "date", "dt", "timestamp", "createdAt", "created_at") if entry.get(k) is not None), None)
        if raw_date is None:
            continue
        text = str(raw_date)
        day = text[:10]
        if len(day) != 10 or day[4:5] != "-":
            try:
                numeric = float(raw_date)
                if 1_000 <= numeric < 1_000_000:
                    day = (datetime(1970, 1, 1) + timedelta(days=int(numeric))).date().isoformat()
                else:
                    if numeric > 10_000_000_000:
                        numeric /= 1000.0
                    day = datetime.fromtimestamp(numeric).date().isoformat()
            except (TypeError, ValueError, OSError, OverflowError):
                continue
        normalized.append({
            "value": value,
            "snapshot_date": day,
            "recorded_at": f"{day}T12:00:00+00:00",
        })
    by_day = {row["snapshot_date"]: row for row in normalized}
    return [by_day[key] for key in sorted(by_day)]


def _event_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _nearest_value(history: list[dict], target: date, *, max_distance_days: int = 2) -> int | None:
    candidates: list[tuple[int, int]] = []
    for row in history:
        raw_day = row.get("snapshot_date")
        try:
            day = date.fromisoformat(str(raw_day)[:10])
            value = int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        distance = abs((day - target).days)
        if distance <= max_distance_days:
            candidates.append((distance, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _bucket(price: int) -> str:
    for low, high, label in PRICE_BUCKETS:
        if low <= price < high:
            return label
    return ">20 Mio."


def build_league_purchase_learning(
    transfers: Iterable[dict],
    *,
    own_manager_id: str | None = None,
    manager_names: dict[str, str] | None = None,
    histories: dict[str, list[dict]] | None = None,
) -> dict:
    """Learn from actual league purchases without teaching the model to overpay.

    Only BUY events are treated as winning bids. SELL events are ignored because
    the manager transfer endpoint can expose both sides of the same ownership
    change. Premiums are calculated only when an MV snapshot exists close to the
    transfer date; missing history remains missing instead of being guessed.
    """
    names = manager_names or {}
    histories = histories or {}
    own_id = str(own_manager_id or "")
    buys: list[dict] = []
    seen: set[tuple] = set()

    for raw in transfers:
        row = dict(raw)
        if str(row.get("transfer_type") or "").upper() != "BUY":
            continue
        manager_id = str(row.get("manager_id") or "")
        if own_id and manager_id == own_id:
            continue
        pid = str(row.get("player_id") or "")
        price = int(row.get("price") or 0)
        transferred_at = str(row.get("transferred_at") or "")
        key = (manager_id, pid, price, transferred_at)
        if not pid or price <= 0 or key in seen:
            continue
        seen.add(key)
        day = _event_date(transferred_at)
        history = histories.get(pid, [])
        mv0 = _nearest_value(history, day) if day else None
        mv3 = _nearest_value(history, day + timedelta(days=3)) if day else None
        mv7 = _nearest_value(history, day + timedelta(days=7)) if day else None
        pre_mv3 = _value_on_or_before(history, day - timedelta(days=3)) if day else None
        pre_mv7 = _value_on_or_before(history, day - timedelta(days=7)) if day else None
        pre_rate3 = _daily_rate(pre_mv3, mv0, 3)
        pre_rate7 = _daily_rate(pre_mv7, mv0, 7)
        momentum_profile, pre_daily_pct = _momentum_profile_from_rates(pre_rate3, pre_rate7)
        premium_pct = ((price - mv0) / mv0 * 100.0) if mv0 else None
        buyer_3d_pct = ((mv3 - price) / price * 100.0) if mv3 else None
        buyer_7d_pct = ((mv7 - price) / price * 100.0) if mv7 else None
        market_3d_pct = ((mv3 - mv0) / mv0 * 100.0) if mv0 and mv3 else None
        market_7d_pct = ((mv7 - mv0) / mv0 * 100.0) if mv0 and mv7 else None
        buys.append({
            **row,
            "manager_id": manager_id,
            "manager_name": names.get(manager_id, manager_id or "Unbekannt"),
            "market_value_at_transfer": mv0,
            "premium_pct": premium_pct,
            "market_value_3d": mv3,
            "market_value_7d": mv7,
            "buyer_return_3d_pct": buyer_3d_pct,
            "buyer_return_7d_pct": buyer_7d_pct,
            "market_return_3d_pct": market_3d_pct,
            "market_return_7d_pct": market_7d_pct,
            "price_bucket": _bucket(price),
            "premium_band": _premium_band(float(premium_pct)) if premium_pct is not None else None,
            "pre_market_value_3d": pre_mv3,
            "pre_market_value_7d": pre_mv7,
            "pre_momentum_3d_daily_pct": pre_rate3,
            "pre_momentum_7d_daily_pct": pre_rate7,
            "pre_momentum_daily_pct": pre_daily_pct,
            "momentum_profile": momentum_profile,
        })

    buys.sort(key=lambda row: str(row.get("transferred_at") or ""), reverse=True)
    premium_rows = [row for row in buys if row.get("premium_pct") is not None]
    out3 = [float(row["buyer_return_3d_pct"]) for row in buys if row.get("buyer_return_3d_pct") is not None]
    out7 = [float(row["buyer_return_7d_pct"]) for row in buys if row.get("buyer_return_7d_pct") is not None]

    bucket_stats = {}
    for _, _, label in PRICE_BUCKETS:
        values = [float(row["premium_pct"]) for row in premium_rows if row.get("price_bucket") == label]
        if values:
            bucket_stats[label] = {"count": len(values), "median_premium_pct": median(values)}

    by_manager: dict[str, list[dict]] = defaultdict(list)
    for row in premium_rows:
        by_manager[str(row.get("manager_id") or "")].append(row)
    manager_profiles = []
    for manager_id, rows in by_manager.items():
        premiums = [float(r["premium_pct"]) for r in rows]
        manager_profiles.append({
            "manager_id": manager_id,
            "manager_name": names.get(manager_id, manager_id or "Unbekannt"),
            "count": len(rows),
            "median_premium_pct": median(premiums),
            "average_price": sum(int(r.get("price") or 0) for r in rows) / len(rows),
        })
    manager_profiles.sort(key=lambda row: (row["count"], row["median_premium_pct"]), reverse=True)

    # Learn whether the *pre-transfer* momentum profile was actually profitable
    # after paying the observed league price. This calibrates investment ideas
    # against outcomes instead of arbitrary score thresholds.
    investment_profiles = {}
    for profile in ("STARK STEIGEND", "STEIGEND", "STABIL", "FALLEND"):
        rows = [r for r in buys if r.get("momentum_profile") == profile and r.get("buyer_return_7d_pct") is not None]
        if not rows:
            continue
        returns = [float(r["buyer_return_7d_pct"]) for r in rows]
        investment_profiles[profile] = {
            "count": len(rows),
            "median_buyer_return_7d_pct": median(returns),
            "profitable_rate_7d": sum(1 for value in returns if value > 0.0) / len(returns),
            "median_pre_momentum_daily_pct": median([float(r["pre_momentum_daily_pct"]) for r in rows if r.get("pre_momentum_daily_pct") is not None]),
        }

    premium_outcomes = {}
    for _, _, label in PREMIUM_BANDS:
        rows = [r for r in buys if r.get("premium_band") == label and r.get("buyer_return_7d_pct") is not None]
        if not rows:
            continue
        returns = [float(r["buyer_return_7d_pct"]) for r in rows]
        premium_outcomes[label] = {
            "count": len(rows),
            "median_buyer_return_7d_pct": median(returns),
            "profitable_rate_7d": sum(1 for value in returns if value > 0.0) / len(returns),
        }

    # A descriptive guardrail only: highest observed premium band that remained
    # non-negative on median with at least 50% profitable deals and n>=3.
    profitable_premium_band = None
    for _, _, label in PREMIUM_BANDS:
        stat = premium_outcomes.get(label) or {}
        if int(stat.get("count") or 0) >= 3 and float(stat.get("median_buyer_return_7d_pct") or -999) >= 0 and float(stat.get("profitable_rate_7d") or 0) >= 0.50:
            profitable_premium_band = label

    return {
        "external_buy_count": len(buys),
        "premium_sample_count": len(premium_rows),
        "median_premium_pct": median([float(r["premium_pct"]) for r in premium_rows]) if premium_rows else None,
        "median_buyer_return_3d_pct": median(out3) if out3 else None,
        "median_buyer_return_7d_pct": median(out7) if out7 else None,
        "outcome_3d_count": len(out3),
        "outcome_7d_count": len(out7),
        "bucket_stats": bucket_stats,
        "manager_profiles": manager_profiles,
        "investment_profiles": investment_profiles,
        "premium_outcomes": premium_outcomes,
        "profitable_premium_band": profitable_premium_band,
        "buys": buys,
    }


def estimate_investment_outcome(
    *, market_value: int | None, d3: int | float | None, d7: int | float | None, learning: dict, min_samples: int = 3
) -> dict:
    current = classify_current_momentum(market_value, d3, d7)
    profile = current["profile"]
    stat = (learning.get("investment_profiles") or {}).get(profile) or {}
    count = int(stat.get("count") or 0)
    if count < min_samples:
        return {**current, "sample_count": count, "median_return_7d_pct": None, "profitable_rate_7d": None, "label": "ZU WENIG DATEN"}
    median_return = float(stat.get("median_buyer_return_7d_pct") or 0.0)
    hit_rate = float(stat.get("profitable_rate_7d") or 0.0)
    if median_return >= 3.0 and hit_rate >= 0.60:
        label = "HISTORISCH STARK"
    elif median_return >= 0.0 and hit_rate >= 0.50:
        label = "HISTORISCH OK"
    else:
        label = "HISTORISCH SCHWACH"
    return {**current, "sample_count": count, "median_return_7d_pct": median_return, "profitable_rate_7d": hit_rate, "label": label}


def evaluate_premium_outcome(
    *, bid: int | None, market_value: int | None, learning: dict, min_samples: int = 3
) -> dict:
    mv = int(market_value or 0)
    amount = int(bid or 0)
    if mv <= 0 or amount <= 0:
        return {"premium_pct": None, "band": None, "sample_count": 0, "median_return_7d_pct": None, "profitable_rate_7d": None, "label": "KEINE DATEN"}
    premium = (amount - mv) / mv * 100.0
    band = _premium_band(premium)
    stat = (learning.get("premium_outcomes") or {}).get(band) or {}
    count = int(stat.get("count") or 0)
    if count < min_samples:
        label = "ZU WENIG DATEN"
        median_return = None
        hit_rate = None
    else:
        median_return = float(stat.get("median_buyer_return_7d_pct") or 0.0)
        hit_rate = float(stat.get("profitable_rate_7d") or 0.0)
        if median_return < 0.0 or hit_rate < 0.45:
            label = "OVERPAY-RISIKO"
        elif median_return >= 2.0 and hit_rate >= 0.60:
            label = "PREMIUM HISTORISCH OK"
        else:
            label = "PREMIUM NEUTRAL"
    return {
        "premium_pct": premium, "band": band, "sample_count": count,
        "median_return_7d_pct": median_return, "profitable_rate_7d": hit_rate, "label": label,
        "profitable_premium_band": learning.get("profitable_premium_band"),
    }


def calibrate_bid_action(base: dict, *, investment_outcome: dict | None = None, premium_outcome: dict | None = None) -> dict:
    """Conservative historical veto: history may stop a chase, never raise the economic ceiling."""
    result = dict(base or {})
    action = str(result.get("bid_action") or "PRÜFEN")
    premium = dict(premium_outcome or {})
    profile = dict(investment_outcome or {})
    reasons = []
    if premium.get("label") == "OVERPAY-RISIKO" and int(premium.get("sample_count") or 0) >= 3:
        reasons.append("dieses Premium-Band war historisch nach 7T schwach")
    if profile.get("label") == "HISTORISCH SCHWACH" and int(profile.get("sample_count") or 0) >= 3:
        reasons.append("vergleichbares Momentum-Profil war historisch nach 7T schwach")
    if reasons and action in {"ERHÖHEN PRÜFEN", "HALTEN"}:
        result["bid_action"] = "NICHT ERHÖHEN"
        result["bid_action_tone"] = "warning"
        result["historical_veto"] = True
        result["historical_veto_reason"] = " · ".join(reasons)
    else:
        result["historical_veto"] = False
        result["historical_veto_reason"] = ""
    return result


def estimate_winning_price(market_value: int | None, learning: dict, *, min_samples: int = 3) -> dict:
    """Estimate likely winning price from observed league premiums.

    This is context only. It never changes the economic max bid.
    """
    mv = int(market_value or 0)
    if mv <= 0:
        return {"price": None, "premium_pct": None, "sample_count": 0, "source": "keine Daten"}
    label = _bucket(mv)
    bucket = (learning.get("bucket_stats") or {}).get(label)
    if bucket and int(bucket.get("count") or 0) >= min_samples:
        premium = float(bucket.get("median_premium_pct") or 0.0)
        count = int(bucket.get("count") or 0)
        source = label
    elif int(learning.get("premium_sample_count") or 0) >= min_samples:
        premium = float(learning.get("median_premium_pct") or 0.0)
        count = int(learning.get("premium_sample_count") or 0)
        source = "Liga gesamt"
    else:
        return {"price": None, "premium_pct": None, "sample_count": int(learning.get("premium_sample_count") or 0), "source": "zu wenig Daten"}
    return {
        "price": int(round(mv * (1.0 + premium / 100.0))),
        "premium_pct": premium,
        "sample_count": count,
        "source": source,
    }


def evaluate_active_bid(
    *,
    bid: int | None,
    max_bid: int | None,
    winning: dict | None,
) -> dict:
    """Turn historical winning-price context into a visible bid decision.

    The historical estimate is deliberately *not* an economic ceiling. It only
    tells us whether the current bid is around the league's observed winning
    level. The action is always constrained by the analytically derived Max-Bid.
    """
    current_bid = max(0, int(bid or 0))
    ceiling = max(0, int(max_bid or 0))
    winning = dict(winning or {})
    expected = max(0, int(winning.get("price") or 0))
    sample_count = max(0, int(winning.get("sample_count") or 0))

    if current_bid <= 0:
        return {
            "league_chance": "KEIN GEBOT",
            "league_chance_tone": "warning",
            "bid_action": "PRÜFEN",
            "bid_action_tone": "warning",
            "league_gap": None,
            "league_gap_pct": None,
        }

    if expected <= 0 or sample_count < 3:
        if ceiling and current_bid > ceiling:
            action, action_tone = "ZURÜCKZIEHEN", "negative"
        elif ceiling and current_bid >= ceiling * 0.98:
            action, action_tone = "NICHT ERHÖHEN", "warning"
        else:
            action, action_tone = "HALTEN", "positive"
        return {
            "league_chance": "ZU WENIG DATEN",
            "league_chance_tone": "warning",
            "bid_action": action,
            "bid_action_tone": action_tone,
            "league_gap": None,
            "league_gap_pct": None,
        }

    gap = current_bid - expected
    gap_pct = gap / expected * 100.0
    ratio = current_bid / expected
    if ratio >= 1.02:
        chance, chance_tone = "GUTE CHANCE", "positive"
    elif ratio >= 0.98:
        chance, chance_tone = "KNAPP", "warning"
    else:
        chance, chance_tone = "UNWAHRSCHEINLICH", "negative"

    # Economic ceiling always wins over the league-price estimate.
    if ceiling and current_bid > ceiling:
        action, action_tone = "ZURÜCKZIEHEN", "negative"
    elif ceiling and current_bid >= ceiling * 0.98:
        action, action_tone = "NICHT ERHÖHEN", "warning"
    elif expected > 0 and ceiling and expected > ceiling:
        # The league normally pays more than we consider rational. Leave the
        # existing bid alive, but do not chase the historical winning level.
        action, action_tone = "NICHT ERHÖHEN", "warning"
    elif expected > current_bid * 1.02 and (not ceiling or expected <= ceiling):
        action, action_tone = "ERHÖHEN PRÜFEN", "warning"
    else:
        action, action_tone = "HALTEN", "positive"

    return {
        "league_chance": chance,
        "league_chance_tone": chance_tone,
        "bid_action": action,
        "bid_action_tone": action_tone,
        "league_gap": gap,
        "league_gap_pct": gap_pct,
    }
