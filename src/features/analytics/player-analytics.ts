import type { MarketValuePoint, PlayerPerformanceEntry } from "../player-detail/types";

export type MarketDynamicsCode =
  | "ACCELERATING_UP"
  | "STABLE_UP"
  | "SLOWING_UP"
  | "TURNING_UP"
  | "TURNING_DOWN"
  | "SIDEWAYS"
  | "RECOVERING"
  | "STABLE_DOWN"
  | "ACCELERATING_DOWN"
  | "UNKNOWN";

export type MarketDynamics = {
  code: MarketDynamicsCode;
  label: string;
  tone: "positive" | "negative" | "warning" | "neutral";
  reason: string;
  recentSteps: number[];
  recentVelocity: number | null;
  olderVelocity: number | null;
  streak: number;
};

export type PointsAnalytics = {
  sampleSize: number;
  seasonAverage: number | null;
  rolling3: number | null;
  rolling5: number | null;
  median: number | null;
  floor: number | null;
  ceiling: number | null;
  minutesAverage: number | null;
  form: "UP" | "DOWN" | "STABLE" | "UNKNOWN";
  formLabel: string;
  volatility: "VERY_STABLE" | "NORMAL" | "VOLATILE" | "UNKNOWN";
  volatilityLabel: string;
};

const LABELS: Record<MarketDynamicsCode, string> = {
  ACCELERATING_UP: "Beschleunigend",
  STABLE_UP: "Stabil steigend",
  SLOWING_UP: "Verlangsamend",
  TURNING_UP: "Wende aufwärts",
  TURNING_DOWN: "Wende abwärts",
  SIDEWAYS: "Seitwärts",
  RECOVERING: "Erholung",
  STABLE_DOWN: "Stabil fallend",
  ACCELERATING_DOWN: "Beschleunigt fallend",
  UNKNOWN: "Zu wenig Daten",
};

const REASONS: Record<MarketDynamicsCode, string> = {
  ACCELERATING_UP: "Die jüngsten positiven MW-Schritte werden deutlich größer.",
  STABLE_UP: "Die jüngsten MW-Schritte bleiben positiv und ähnlich groß.",
  SLOWING_UP: "Der MW steigt noch, die jüngsten Zuwächse werden aber deutlich kleiner.",
  TURNING_UP: "Der MW dreht von fallender in steigende Dynamik.",
  TURNING_DOWN: "Der MW dreht von steigender in fallende Dynamik.",
  SIDEWAYS: "Die jüngsten MW-Schritte liegen nahe am normalen Rauschen.",
  RECOVERING: "Der MW fällt noch, die Verluste werden aber kleiner.",
  STABLE_DOWN: "Die jüngsten MW-Schritte bleiben negativ und ähnlich groß.",
  ACCELERATING_DOWN: "Die jüngsten negativen MW-Schritte werden deutlich größer.",
  UNKNOWN: "Für eine belastbare Dynamik fehlen noch tägliche Marktwert-Schritte.",
};

export function analyzeMarketDynamics(points: MarketValuePoint[], marketValue: number | null, currentDelta: number | null): MarketDynamics {
  const steps = dailySteps(points, currentDelta).slice(-8);
  if (steps.length < 2) return dynamicsResult("UNKNOWN", steps, null, null);

  const recentCount = Math.min(3, Math.max(1, Math.floor(steps.length / 2)));
  const olderCount = Math.min(3, steps.length - recentCount);
  const recent = steps.slice(-recentCount);
  const older = olderCount ? steps.slice(-(recentCount + olderCount), -recentCount) : [];
  const recentVelocity = mean(recent);
  const olderVelocity = older.length ? mean(older) : steps[steps.length - 2]!;
  const noise = noiseFloor(marketValue, steps);

  let code: MarketDynamicsCode;
  if (Math.abs(recentVelocity) <= noise) {
    code = "SIDEWAYS";
  } else if (recentVelocity > 0) {
    if (olderVelocity < -noise) code = "TURNING_UP";
    else if (olderVelocity <= noise) code = "ACCELERATING_UP";
    else {
      const ratio = recentVelocity / Math.max(Math.abs(olderVelocity), noise);
      if (ratio >= 1.2 && recentVelocity - olderVelocity >= noise) code = "ACCELERATING_UP";
      else if (ratio <= 0.7 && olderVelocity - recentVelocity >= noise) code = "SLOWING_UP";
      else code = "STABLE_UP";
    }
  } else {
    if (olderVelocity > noise) code = "TURNING_DOWN";
    else if (olderVelocity >= -noise) code = "ACCELERATING_DOWN";
    else {
      const ratio = Math.abs(recentVelocity) / Math.max(Math.abs(olderVelocity), noise);
      if (ratio >= 1.2 && Math.abs(recentVelocity) - Math.abs(olderVelocity) >= noise) code = "ACCELERATING_DOWN";
      else if (ratio <= 0.7 && Math.abs(olderVelocity) - Math.abs(recentVelocity) >= noise) code = "RECOVERING";
      else code = "STABLE_DOWN";
    }
  }

  return dynamicsResult(code, steps.slice(-6), Math.round(recentVelocity), Math.round(olderVelocity));
}

export function analyzePoints(entries: PlayerPerformanceEntry[]): PointsAnalytics {
  const active = entries
    .filter((entry) => entry.dayNumber > 0 && entry.points != null)
    .sort((a, b) => a.dayNumber - b.dayNumber);
  const points = active.map((entry) => entry.points as number);
  const minutes = active.map((entry) => entry.minutes).filter((value): value is number => value != null && Number.isFinite(value));

  if (!points.length) {
    return {
      sampleSize: 0, seasonAverage: null, rolling3: null, rolling5: null, median: null, floor: null, ceiling: null,
      minutesAverage: null, form: "UNKNOWN", formLabel: "Zu wenig Daten", volatility: "UNKNOWN", volatilityLabel: "Zu wenig Daten",
    };
  }

  const seasonAverage = mean(points);
  const med = percentile(points, 0.5);
  const rolling3 = points.length >= 3 ? mean(points.slice(-3)) : null;
  const rolling5 = points.length >= 5 ? mean(points.slice(-5)) : null;

  let form: PointsAnalytics["form"] = "UNKNOWN";
  if (points.length >= 4) {
    const recentCount = Math.min(3, Math.floor(points.length / 2));
    const recent = mean(points.slice(-recentCount));
    const previous = mean(points.slice(-(recentCount * 2), -recentCount));
    const threshold = Math.max(10, Math.abs(previous) * 0.1);
    form = recent - previous > threshold ? "UP" : previous - recent > threshold ? "DOWN" : "STABLE";
  }

  const sd = standardDeviation(points);
  const denominator = Math.max(Math.abs(seasonAverage), 35);
  const cv = sd / denominator;
  const volatility: PointsAnalytics["volatility"] = points.length < 3 ? "UNKNOWN" : cv <= 0.28 ? "VERY_STABLE" : cv <= 0.58 ? "NORMAL" : "VOLATILE";

  return {
    sampleSize: points.length,
    seasonAverage,
    rolling3,
    rolling5,
    median: med,
    floor: percentile(points, 0.25),
    ceiling: percentile(points, 0.75),
    minutesAverage: minutes.length ? mean(minutes) : null,
    form,
    formLabel: form === "UP" ? "Steigend" : form === "DOWN" ? "Fallend" : form === "STABLE" ? "Stabil" : "Zu wenig Daten",
    volatility,
    volatilityLabel: volatility === "VERY_STABLE" ? "Sehr konstant" : volatility === "NORMAL" ? "Normal schwankend" : volatility === "VOLATILE" ? "Stark volatil" : "Zu wenig Daten",
  };
}

function dynamicsResult(code: MarketDynamicsCode, recentSteps: number[], recentVelocity: number | null, olderVelocity: number | null): MarketDynamics {
  const positive = new Set<MarketDynamicsCode>(["ACCELERATING_UP", "STABLE_UP", "TURNING_UP"]);
  const negative = new Set<MarketDynamicsCode>(["STABLE_DOWN", "ACCELERATING_DOWN", "TURNING_DOWN"]);
  const warning = new Set<MarketDynamicsCode>(["SLOWING_UP", "RECOVERING"]);
  return {
    code,
    label: LABELS[code],
    tone: positive.has(code) ? "positive" : negative.has(code) ? "negative" : warning.has(code) ? "warning" : "neutral",
    reason: REASONS[code],
    recentSteps,
    recentVelocity,
    olderVelocity,
    streak: streak(recentSteps),
  };
}

function dailySteps(points: MarketValuePoint[], currentDelta: number | null): number[] {
  // The DB can already contain a snapshot row for today before/around the refresh.
  // When a live 24h delta is available, that delta is the authoritative step for
  // the current refresh. Using today's DB point as well would create a synthetic
  // 0-step (yesterday close -> today's pre-refresh value) and then append the real
  // currentDelta once more.
  const byDay = new Map<string, MarketValuePoint>();
  for (const point of points) {
    byDay.set(point.date.slice(0, 10), point);
  }

  let sorted = [...byDay.values()].sort((a, b) => a.date.localeCompare(b.date));

  if (currentDelta != null && sorted.length) {
    const today = localDateKey(new Date());
    if (sorted[sorted.length - 1]!.date.slice(0, 10) === today) {
      sorted = sorted.slice(0, -1);
    }
  }

  const steps: number[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const previous = dateNumber(sorted[i - 1].date);
    const current = dateNumber(sorted[i].date);
    if (current - previous !== 86_400_000) continue;
    steps.push(sorted[i].value - sorted[i - 1].value);
  }

  if (currentDelta != null) steps.push(currentDelta);
  return steps;
}

function localDateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function noiseFloor(marketValue: number | null, steps: number[]) {
  const mvFloor = Math.abs(marketValue ?? 0) * 0.0005;
  const nonZero = steps.slice(-6).filter(Boolean).map(Math.abs).sort((a, b) => a - b);
  const observed = nonZero.length ? percentile(nonZero, 0.5) : 0;
  return Math.max(10_000, mvFloor, observed * 0.1);
}

function streak(steps: number[]) {
  if (!steps.length || steps[steps.length - 1] === 0) return 0;
  const sign = Math.sign(steps[steps.length - 1]!);
  let count = 0;
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i] === 0 || Math.sign(steps[i]) !== sign) break;
    count++;
  }
  return sign * count;
}

function percentile(values: number[], p: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * p;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function mean(values: number[]) { return values.reduce((sum, value) => sum + value, 0) / values.length; }
function standardDeviation(values: number[]) { const avg = mean(values); return Math.sqrt(mean(values.map((value) => (value - avg) ** 2))); }
function dateNumber(value: string) { return new Date(`${value.slice(0, 10)}T00:00:00Z`).getTime(); }
