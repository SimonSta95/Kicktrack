from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class Prediction:
    delta: int | None
    expected_value: int | None
    low_delta: int | None
    high_delta: int | None
    confidence: str
    sample_count: int
    history_days: int
    method: str = "24h persistence + historical calibration"
    baseline_delta: int | None = None

    def as_dict(self) -> dict:
        return {
            "delta": self.delta,
            "expected_value": self.expected_value,
            "low_delta": self.low_delta,
            "high_delta": self.high_delta,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
            "history_days": self.history_days,
            "method": self.method,
            "baseline_delta": self.baseline_delta,
        }


def _iso_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _daily_series(rows: Iterable[dict]) -> dict[str, list[tuple[date, int]]]:
    by_player: dict[str, dict[date, int]] = {}
    for row in rows or []:
        player_id = str(row.get("player_id") or "")
        day = _iso_day(row.get("snapshot_date"))
        try:
            value = int(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id or day is None or value <= 0:
            continue
        by_player.setdefault(player_id, {})[day] = value
    return {pid: sorted(values.items()) for pid, values in by_player.items()}


def _historical_samples(series: dict[str, list[tuple[date, int]]]) -> list[dict]:
    samples: list[dict] = []
    # The newest stored calendar day may have been captured *before* the 22:00
    # refresh and therefore still contain yesterday's value. Never use a sample
    # whose target is that newest global day. We intentionally lag calibration
    # by one day rather than training on an incomplete pseudo-zero move.
    newest_day = max((day for points in series.values() for day, _ in points), default=None)
    for player_id, points in series.items():
        values = dict(points)
        for day, current in points:
            previous_day = day - timedelta(days=1)
            next_day = day + timedelta(days=1)
            if previous_day not in values or next_day not in values:
                continue
            if newest_day is not None and next_day == newest_day:
                continue
            previous = values[previous_day]
            d1 = current - previous
            target = values[next_day] - current
            samples.append(
                {
                    "player_id": player_id,
                    "market_value": current,
                    "d1": d1,
                    "target": target,
                    "error": target - d1,
                }
            )
    return samples


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(int(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return int(round(ordered[lo] * (1 - frac) + ordered[hi] * frac))


def build_predictions(
    rows: Iterable[dict],
    current_values: dict[str, int] | None = None,
    current_deltas: dict[str, int] | None = None,
    *,
    target_date: date | str | None = None,
) -> dict[str, dict]:
    """Predict the next daily Kickbase market-value refresh.

    Kickbase market-value changes in the supplied history are strongly persistent
    from one refresh to the next.  The model deliberately uses that robust signal
    instead of pretending to know an exact future price:

    * point forecast = latest 24h change, lightly bias-corrected from comparable
      historical observations;
    * interval = empirical 80% absolute error of comparable historical cases;
    * confidence = history depth + recent direction consistency + interval width.

    No external ML package is required and every output remains explainable.
    """
    series = _daily_series(rows)
    samples = _historical_samples(series)
    # Index historical samples once. Previously every prediction scanned the
    # complete calibration corpus one or two times, which became very expensive
    # after reliable 365-day histories were introduced for hundreds of players.
    samples_by_sign: dict[int, list[dict]] = {-1: [], 0: [], 1: []}
    for sample in samples:
        sample_sign = 1 if sample["d1"] > 0 else (-1 if sample["d1"] < 0 else 0)
        samples_by_sign[sample_sign].append(sample)
    magnitudes_by_sign: dict[int, list[int]] = {}
    for sample_sign, bucket in samples_by_sign.items():
        bucket.sort(key=lambda item: abs(int(item["d1"])))
        magnitudes_by_sign[sample_sign] = [abs(int(item["d1"])) for item in bucket]

    def magnitude_candidates(sample_sign: int, low: float, high: float) -> list[dict]:
        bucket = samples_by_sign.get(sample_sign) or []
        magnitudes = magnitudes_by_sign.get(sample_sign) or []
        if not bucket:
            return []
        left = bisect_left(magnitudes, max(0, int(low)))
        right = bisect_right(magnitudes, max(0, int(high)))
        return bucket[left:right]

    current_values = {str(k): int(v) for k, v in (current_values or {}).items() if v is not None}
    current_deltas = {str(k): int(v) for k, v in (current_deltas or {}).items() if v is not None}
    if isinstance(target_date, date):
        forecast_target = target_date
    elif target_date:
        forecast_target = date.fromisoformat(str(target_date)[:10])
    else:
        forecast_target = date.today()

    result: dict[str, dict] = {}

    active_player_ids = set(current_values) if current_values else None
    for player_id, points in series.items():
        if active_player_ids is not None and player_id not in active_player_ids:
            continue
        if not points:
            continue
        latest_day, latest_stored = points[-1]
        current = int(current_values.get(player_id, latest_stored))
        values = dict(points)

        # Before the 22:00 refresh today's persisted snapshot still contains the
        # *previous* refresh value. Deriving the signal from today's/yesterday's
        # rows therefore produces a false 0. Kickbase already exposes the live
        # 24h change; use that as the authoritative next-refresh signal whenever
        # available. The daily DB history is only the calibration/backtest base.
        if player_id in current_deltas:
            latest_delta = int(current_deltas[player_id])
        else:
            previous_day = latest_day - timedelta(days=1)

            # A pre-22:00 live snapshot for the target day still contains the
            # value from the previous completed refresh. Comparing it with the
            # previous calendar day therefore creates an artificial 0 € signal.
            # For players without Kickbase's live d1 field (notably cached
            # MANAGER_SQUAD players), use the last *completed* history move.
            if latest_day >= forecast_target:
                completed_day = latest_day - timedelta(days=1)
                completed_previous = completed_day - timedelta(days=1)
                if completed_day in values and completed_previous in values:
                    latest_delta = int(values[completed_day]) - int(values[completed_previous])
                elif previous_day in values:
                    latest_delta = current - int(values[previous_day])
                elif len(points) >= 3:
                    latest_delta = int(points[-2][1]) - int(points[-3][1])
                else:
                    result[player_id] = Prediction(
                        None, None, None, None, "UNSICHER", 0, len(points),
                        baseline_delta=None,
                    ).as_dict()
                    continue
            elif previous_day in values:
                latest_delta = current - int(values[previous_day])
            elif len(points) >= 2:
                latest_delta = current - int(points[-2][1])
            else:
                result[player_id] = Prediction(
                    None, None, None, None, "UNSICHER", 0, len(points),
                    baseline_delta=None,
                ).as_dict()
                continue

        # Comparable historical cases: same direction and broadly similar daily
        # change magnitude.  Prefer a comparable market-value band, then relax it
        # if that would leave too little evidence.
        sign = 1 if latest_delta > 0 else (-1 if latest_delta < 0 else 0)
        magnitude = max(abs(latest_delta), 1)
        candidates = magnitude_candidates(sign, magnitude * 0.50, magnitude * 1.50)
        analogs = [
            s for s in candidates
            if s["market_value"] >= current * 0.40
            and s["market_value"] <= current * 2.50
        ]
        if len(analogs) < 20:
            analogs = magnitude_candidates(sign, magnitude * 0.40, magnitude * 1.80)

        bias = int(round(median([s["error"] for s in analogs]))) if analogs else 0
        # Calibration is intentionally weak. The persistence signal is the part
        # that backtests well; the historical correction must never dominate it.
        bias_cap = max(25_000, int(magnitude * 0.20))
        bias = max(-bias_cap, min(bias_cap, bias))
        prediction = int(round(latest_delta + bias))

        abs_errors = [abs(int(s["error"])) for s in analogs]
        radius = _percentile(abs_errors, 0.80) if abs_errors else max(75_000, int(magnitude * 0.60))
        # Do not display a deceptively narrow range merely because a tiny sample
        # happened to be homogeneous.
        radius = max(25_000, radius)
        low = prediction - radius
        high = prediction + radius

        # Recent direction consistency is a useful confidence signal without
        # changing the point forecast itself.
        recent_deltas: list[int] = []
        for idx in range(len(points) - 1, 0, -1):
            day, value = points[idx]
            prev_day, prev_value = points[idx - 1]
            if (day - prev_day).days != 1:
                continue
            recent_deltas.append(int(value) - int(prev_value))
            if len(recent_deltas) >= 3:
                break
        same_direction = sum(
            1 for value in recent_deltas
            if (1 if value > 0 else (-1 if value < 0 else 0)) == sign
        )
        ratio = radius / max(abs(prediction), 50_000)
        has_live_signal = player_id in current_deltas
        if has_live_signal and len(points) >= 4 and len(analogs) >= 50 and same_direction >= 2 and ratio <= 0.75:
            confidence = "HOCH"
        elif has_live_signal and len(analogs) >= 20 and ratio <= 1.25:
            # A trusted live 24h signal plus a broad historical analogue set is
            # useful even if this particular player has only a short local
            # history. Keep that at MITTEL, never HOCH without own trend depth.
            confidence = "MITTEL"
        elif len(points) >= 4 and len(analogs) >= 12 and ratio <= 1.50:
            confidence = "MITTEL"
        else:
            confidence = "UNSICHER"

        result[player_id] = Prediction(
            delta=prediction,
            expected_value=max(0, current + prediction),
            low_delta=low,
            high_delta=high,
            confidence=confidence,
            sample_count=len(analogs),
            history_days=len(points),
            baseline_delta=latest_delta,
        ).as_dict()

    return result
