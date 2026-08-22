from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean, median
from typing import Iterable


TREND_LABELS = {
    "ACCELERATING_UP": "BESCHLEUNIGEND",
    "STABLE_UP": "STABIL STEIGEND",
    "SLOWING_UP": "VERLANGSAMEND",
    "TURNING_UP": "WENDE AUFWÄRTS",
    "TURNING_DOWN": "WENDE ABWÄRTS",
    "SIDEWAYS": "SEITWÄRTS",
    "RECOVERING": "ERHOLUNG",
    "STABLE_DOWN": "STABIL FALLEND",
    "ACCELERATING_DOWN": "BESCHLEUNIGT FALLEND",
    "UNKNOWN": "ZU WENIG DATEN",
}


TREND_SYMBOLS = {
    "ACCELERATING_UP": "⇈",
    "STABLE_UP": "↑",
    "SLOWING_UP": "↗",
    "TURNING_UP": "↗",
    "TURNING_DOWN": "↘",
    "SIDEWAYS": "→",
    "RECOVERING": "↘",
    "STABLE_DOWN": "↓",
    "ACCELERATING_DOWN": "⇊",
    "UNKNOWN": "·",
}


def trend_display(trend: dict | None) -> str:
    """Compact CI-friendly trend label with a monochrome direction symbol."""
    trend = trend or {}
    code = str(trend.get("code") or "UNKNOWN")
    label = str(trend.get("label") or TREND_LABELS.get(code) or TREND_LABELS["UNKNOWN"])
    return f"{TREND_SYMBOLS.get(code, '·')} {label}"


def trend_tone(code: str | None) -> str:
    """Semantic tone used by Qt views; keeps trend visuals consistent."""
    code = str(code or "UNKNOWN")
    if code in {"SLOWING_UP", "RECOVERING"}:
        return "warning"
    if code in {"ACCELERATING_UP", "STABLE_UP", "TURNING_UP"}:
        return "positive"
    if code in {"STABLE_DOWN", "ACCELERATING_DOWN", "TURNING_DOWN"}:
        return "negative"
    return "muted"


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _series(history: Iterable[dict]) -> list[tuple[date, int]]:
    by_day: dict[date, int] = {}
    for row in history or []:
        day = _day(row.get("snapshot_date"))
        try:
            value = int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if day and value > 0:
            by_day[day] = value
    return sorted(by_day.items())


def market_value_steps(history: Iterable[dict], *, current_delta: int | None = None, limit: int = 8) -> list[int]:
    points = _series(history)
    steps: list[int] = []
    for index in range(1, len(points)):
        previous_day, previous = points[index - 1]
        current_day, current = points[index]
        if (current_day - previous_day).days != 1:
            continue
        steps.append(int(current) - int(previous))
    if current_delta is not None:
        current_delta = int(current_delta)
        # API 24h is the latest live refresh movement. If it already equals the
        # final historical step, duplicate insertion would exaggerate persistence.
        if not steps or steps[-1] != current_delta:
            steps.append(current_delta)
    return steps[-max(2, int(limit or 8)):]


def _noise_floor(market_value: int | None, steps: list[int]) -> float:
    mv_floor = abs(int(market_value or 0)) * 0.0005  # 0.05 % of MW
    observed = median([abs(value) for value in steps[-6:] if value]) if any(steps[-6:]) else 0
    return max(10_000.0, mv_floor, observed * 0.10)


def _streak(steps: list[int]) -> int:
    if not steps or steps[-1] == 0:
        return 0
    sign = 1 if steps[-1] > 0 else -1
    count = 0
    for value in reversed(steps):
        if value == 0 or (1 if value > 0 else -1) != sign:
            break
        count += 1
    return sign * count


def analyze_market_value_trend(
    history: Iterable[dict],
    *,
    market_value: int | None = None,
    current_delta: int | None = None,
) -> dict:
    steps = market_value_steps(history, current_delta=current_delta, limit=8)
    if len(steps) < 2:
        return {
            "code": "UNKNOWN",
            "label": TREND_LABELS["UNKNOWN"],
            "direction": "UNKNOWN",
            "recent_steps": steps,
            "older_velocity": None,
            "recent_velocity": None,
            "velocity_change": None,
            "streak": _streak(steps),
            "reason": "Zu wenig echte tägliche Marktwert-Schritte.",
        }

    recent_count = min(3, max(1, len(steps) // 2))
    older_count = min(3, len(steps) - recent_count)
    recent = steps[-recent_count:]
    older = steps[-recent_count - older_count:-recent_count] if older_count else []
    recent_velocity = mean(recent)
    older_velocity = mean(older) if older else steps[-2]
    noise = _noise_floor(market_value, steps)

    if abs(recent_velocity) <= noise:
        code = "SIDEWAYS"
        direction = "SIDEWAYS"
    elif recent_velocity > 0:
        direction = "UP"
        if older_velocity < -noise:
            code = "TURNING_UP"
        elif older_velocity <= noise:
            code = "ACCELERATING_UP"
        else:
            ratio = recent_velocity / max(abs(older_velocity), noise)
            if ratio >= 1.20 and recent_velocity - older_velocity >= noise:
                code = "ACCELERATING_UP"
            elif ratio <= 0.70 and older_velocity - recent_velocity >= noise:
                code = "SLOWING_UP"
            else:
                code = "STABLE_UP"
    else:
        direction = "DOWN"
        if older_velocity > noise:
            code = "TURNING_DOWN"
        elif older_velocity >= -noise:
            code = "ACCELERATING_DOWN"
        else:
            ratio = abs(recent_velocity) / max(abs(older_velocity), noise)
            if ratio >= 1.20 and abs(recent_velocity) - abs(older_velocity) >= noise:
                code = "ACCELERATING_DOWN"
            elif ratio <= 0.70 and abs(older_velocity) - abs(recent_velocity) >= noise:
                code = "RECOVERING"
            else:
                code = "STABLE_DOWN"

    change = recent_velocity - older_velocity
    streak = _streak(steps)
    compact_steps = " · ".join(f"{value/1000:+.0f}k" for value in steps[-4:])
    reason_map = {
        "ACCELERATING_UP": "Die jüngsten positiven MW-Schritte werden deutlich größer.",
        "STABLE_UP": "Die jüngsten MW-Schritte bleiben positiv und ähnlich groß.",
        "SLOWING_UP": "Der MW steigt noch, die jüngsten Zuwächse werden aber deutlich kleiner.",
        "TURNING_UP": "Der MW dreht von fallender in steigende Dynamik.",
        "TURNING_DOWN": "Der MW dreht von steigender in fallende Dynamik.",
        "SIDEWAYS": "Die jüngsten MW-Schritte liegen nahe am normalen Rauschen.",
        "RECOVERING": "Der MW fällt noch, die Verluste werden aber kleiner.",
        "STABLE_DOWN": "Die jüngsten MW-Schritte bleiben negativ und ähnlich groß.",
        "ACCELERATING_DOWN": "Die jüngsten negativen MW-Schritte werden deutlich größer.",
    }
    return {
        "code": code,
        "label": TREND_LABELS[code],
        "direction": direction,
        "recent_steps": steps[-6:],
        "older_velocity": int(round(older_velocity)),
        "recent_velocity": int(round(recent_velocity)),
        "velocity_change": int(round(change)),
        "streak": streak,
        "noise_floor": int(round(noise)),
        "steps_text": compact_steps,
        "reason": reason_map[code],
    }


def _training_series(rows: Iterable[dict]) -> dict[str, list[tuple[date, int]]]:
    by_player: dict[str, dict[date, int]] = defaultdict(dict)
    for row in rows or []:
        pid = str(row.get("player_id") or "")
        day = _day(row.get("snapshot_date"))
        try:
            value = int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if pid and day and value > 0:
            by_player[pid][day] = value
    return {pid: sorted(values.items()) for pid, values in by_player.items()}


def _sample_features(values: list[int], current_value: int) -> dict | None:
    if len(values) < 4 or current_value <= 0:
        return None
    recent = values[-2:]
    older = values[-4:-2]
    recent_velocity = mean(recent)
    older_velocity = mean(older)
    if abs(recent_velocity) < max(10_000, current_value * 0.0005):
        direction = 0
    else:
        direction = 1 if recent_velocity > 0 else -1
    if direction == 0:
        dynamics = "SIDEWAYS"
    elif older_velocity * recent_velocity < 0:
        dynamics = "TURNING"
    else:
        ratio = abs(recent_velocity) / max(abs(older_velocity), max(10_000, current_value * 0.0005))
        if ratio <= 0.70:
            dynamics = "SLOWING"
        elif ratio >= 1.20:
            dynamics = "ACCELERATING"
        else:
            dynamics = "STABLE"
    magnitude_pct = abs(recent_velocity) / current_value * 100.0
    return {
        "direction": direction,
        "dynamics": dynamics,
        "magnitude_pct": magnitude_pct,
        "recent_velocity": recent_velocity,
    }


def _historical_reversal_samples(rows: Iterable[dict]) -> list[dict]:
    samples: list[dict] = []
    for _pid, points in _training_series(rows).items():
        day_values = {day: value for day, value in points}
        days = [day for day, _ in points]
        for idx in range(4, len(days) - 2):
            day = days[idx]
            required = [day.fromordinal(day.toordinal() - offset) for offset in range(4, -3, -1)]
            if any(req not in day_values for req in required):
                continue
            prior_values = [day_values[req] for req in required[:5]]
            deltas = [prior_values[i] - prior_values[i - 1] for i in range(1, len(prior_values))]
            features = _sample_features(deltas, prior_values[-1])
            if not features or features["direction"] == 0:
                continue
            next_values = [day_values[required[4]], day_values[required[5]], day_values[required[6]]]
            future = [next_values[1] - next_values[0], next_values[2] - next_values[1]]
            future_velocity = mean(future)
            threshold = max(10_000, prior_values[-1] * 0.0005)
            reversed_direction = (
                future_velocity * features["direction"] < -threshold
            )
            samples.append({**features, "reversal": bool(reversed_direction)})
    return samples


def build_reversal_reference(history_rows: Iterable[dict]) -> list[dict]:
    """Precompute historical reversal samples once per refresh.

    Building these samples scans the full market-value history.  The previous
    implementation rebuilt the same corpus once per player, which turned a
    linear operation into an expensive N×history CPU loop and could starve the
    Qt GUI thread despite running in a worker.
    """
    return _historical_reversal_samples(history_rows)


def predict_trend_reversal(
    history_rows: Iterable[dict],
    player_history: Iterable[dict],
    *,
    market_value: int | None,
    current_delta: int | None = None,
    reference_samples: Iterable[dict] | None = None,
) -> dict:
    trend = analyze_market_value_trend(
        player_history,
        market_value=market_value,
        current_delta=current_delta,
    )
    steps = market_value_steps(player_history, current_delta=current_delta, limit=6)
    current_features = _sample_features(steps[-4:], int(market_value or 0))
    if not current_features or current_features["direction"] == 0:
        return {
            "probability": None,
            "risk": "UNSICHER",
            "sample_count": 0,
            "horizon_refreshes": 2,
            "reason": "Zu wenig eindeutige Trendbewegung für eine Wende-Prognose.",
            "trend": trend,
        }

    samples = list(reference_samples) if reference_samples is not None else _historical_reversal_samples(history_rows)
    analogs = [
        sample for sample in samples
        if sample["direction"] == current_features["direction"]
        and sample["dynamics"] == current_features["dynamics"]
        and sample["magnitude_pct"] >= current_features["magnitude_pct"] * 0.35
        and sample["magnitude_pct"] <= max(0.01, current_features["magnitude_pct"] * 2.8)
    ]
    if len(analogs) < 20:
        analogs = [
            sample for sample in samples
            if sample["direction"] == current_features["direction"]
            and sample["dynamics"] == current_features["dynamics"]
        ]
    if len(analogs) < 20:
        return {
            "probability": None,
            "risk": "UNSICHER",
            "sample_count": len(analogs),
            "horizon_refreshes": 2,
            "reason": "Noch zu wenige historische Vergleichsfälle für eine belastbare Wende-Prognose.",
            "trend": trend,
        }

    probability = sum(1 for sample in analogs if sample["reversal"]) / len(analogs)
    if probability >= 0.55:
        risk = "HOCH"
    elif probability >= 0.30:
        risk = "MITTEL"
    else:
        risk = "NIEDRIG"
    return {
        "probability": probability,
        "risk": risk,
        "sample_count": len(analogs),
        "horizon_refreshes": 2,
        "reason": (
            f"{probability * 100:.0f}% der {len(analogs)} historisch ähnlichen Fälle drehten "
            "innerhalb der nächsten zwei Refreshes."
        ),
        "trend": trend,
    }


def _price_context(row: dict) -> tuple[int | None, float | None]:
    mv = int(row.get("market_value") or 0)
    price = int(row.get("price") or 0)
    if mv <= 0 or price <= 0:
        return None, None
    delta = price - mv
    return delta, delta / mv * 100.0


def facts_first_market_signal(row: dict) -> tuple[str, list[str]]:
    trend = row.get("mv_trend") or {}
    reversal = row.get("trend_reversal_prediction") or {}
    delta, delta_pct = _price_context(row)
    reasons: list[str] = []

    streak = int(trend.get("streak") or 0)
    if streak:
        reasons.append(f"{abs(streak)} {'positive' if streak > 0 else 'negative'} MW-Refreshes in Folge")
    if trend.get("steps_text"):
        reasons.append(f"Letzte Schritte: {trend['steps_text']}")
    if delta_pct is not None:
        reasons.append(f"Marktpreis {delta_pct:+.1f}% zum aktuellen MW")
    if reversal.get("probability") is not None:
        reasons.append(
            f"Wende-Risiko {reversal.get('risk')} · {float(reversal['probability']) * 100:.0f}% · n={int(reversal.get('sample_count') or 0)}"
        )

    code = str(trend.get("code") or "UNKNOWN")
    risk = str(reversal.get("risk") or "UNSICHER")
    if code in {"ACCELERATING_DOWN", "STABLE_DOWN"}:
        signal = "MEIDEN"
    elif code == "TURNING_DOWN":
        signal = "TREND DREHT"
    elif code == "TURNING_UP":
        signal = "BEOBACHTEN"
    elif code in {"SLOWING_UP"} or risk == "HOCH":
        signal = "ABKÜHLEND"
    elif code in {"ACCELERATING_UP", "STABLE_UP"}:
        signal = "INTERESSANT" if delta_pct is None or delta_pct <= 2.0 else "BEOBACHTEN"
    elif code == "RECOVERING":
        signal = "BEOBACHTEN"
    else:
        signal = "KEINE KLARE EMPFEHLUNG"
    return signal, reasons


def apply_facts_first_market(
    rows: Iterable[dict],
    histories: dict[str, list[dict]],
    all_history_rows: Iterable[dict],
    *,
    reversal_reference: Iterable[dict] | None = None,
) -> list[dict]:
    result: list[dict] = []
    all_rows = list(all_history_rows or [])
    reversal_reference = list(reversal_reference) if reversal_reference is not None else build_reversal_reference(all_rows)
    for raw in rows or []:
        row = dict(raw)
        pid = str(row.get("player_id") or "")
        history = histories.get(pid) or []
        trend = analyze_market_value_trend(
            history,
            market_value=int(row.get("market_value") or 0),
            current_delta=row.get("d1"),
        )
        reversal = predict_trend_reversal(
            all_rows,
            history,
            market_value=int(row.get("market_value") or 0),
            current_delta=row.get("d1"),
            reference_samples=reversal_reference,
        )
        row["mv_trend"] = trend
        row["trend_reversal_prediction"] = reversal
        signal, reasons = facts_first_market_signal(row)
        row["facts_signal"] = signal
        row["signal"] = signal
        row["verdict"] = signal
        row["action"] = signal
        row["analysis_reasons"] = reasons
        row["analysis_text"] = "\n".join(reasons)
        result.append(row)
    return result


def facts_first_squad_action(row: dict, trend: dict, reversal: dict) -> tuple[str, list[str]]:
    role = str(row.get("player_role") or row.get("role") or "OFFEN").upper()
    code = str(trend.get("code") or "UNKNOWN")
    risk = str(reversal.get("risk") or "UNSICHER")
    pnl = row.get("pnl")
    reasons: list[str] = []
    if pnl is not None:
        reasons.append(f"Offenes P/L {int(pnl):+d} €")
    if trend.get("steps_text"):
        reasons.append(f"Letzte MW-Schritte: {trend['steps_text']}")
    if reversal.get("probability") is not None:
        reasons.append(f"Wende-Risiko {risk} ({float(reversal['probability'])*100:.0f}%, n={int(reversal.get('sample_count') or 0)})")

    if role in {"STAMM", "STARTER"}:
        if code in {"ACCELERATING_DOWN", "STABLE_DOWN", "TURNING_DOWN"}:
            return "BEOBACHTEN", reasons
        return "HALTEN", reasons
    if role == "TRANSFERLISTE":
        if code in {"ACCELERATING_UP", "STABLE_UP"} and risk != "HOCH":
            return "VERKAUF BEOBACHTEN", reasons
        if code == "SLOWING_UP" or risk == "HOCH":
            return "GEWINN ABSICHERN", reasons
        return "VERKAUF PRÜFEN", reasons
    if role == "INVEST":
        if code in {"ACCELERATING_UP", "STABLE_UP"} and risk != "HOCH":
            return "HALTEN", reasons
        if code == "SLOWING_UP" or risk in {"MITTEL", "HOCH"}:
            return "EXIT BEOBACHTEN", reasons
        if code in {"TURNING_DOWN", "STABLE_DOWN", "ACCELERATING_DOWN"}:
            return "VERKAUF PRÜFEN", reasons
    return "KEINE KLARE EMPFEHLUNG", reasons
