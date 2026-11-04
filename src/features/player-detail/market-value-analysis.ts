import type { MarketValuePoint } from "./types.ts";

export type MarketValueChange = MarketValuePoint & {
  change: number;
  changePct: number;
};

export type MarketValueAnalysis = {
  points: MarketValuePoint[];
  changes: MarketValueChange[];
  totalChange: number;
  totalChangePct: number;
  high: MarketValuePoint;
  low: MarketValuePoint;
  averageValue: number;
  averageChange: number;
  upDays: number;
  downDays: number;
  currentStreak: { direction: "up" | "down" | "flat"; count: number };
  longestUpStreak: number;
  longestDownStreak: number;
  bestDay: MarketValueChange | null;
  worstDay: MarketValueChange | null;
  volatilityPct: number;
  distanceFromHighPct: number;
};

/**
 * Calculates changes between recorded observations. Missing calendar days are
 * deliberately not synthesized and therefore never count as zero-change days.
 */
export function analyzeMarketValues(input: MarketValuePoint[]): MarketValueAnalysis | null {
  const byDate = new Map<string, MarketValuePoint>();
  for (const point of input) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(point.date) && Number.isFinite(point.value) && point.value > 0) {
      byDate.set(point.date, point);
    }
  }
  const points = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  if (!points.length) return null;

  const changes = points.slice(1).map((point, index) => {
    const previous = points[index];
    const change = point.value - previous.value;
    return {
      ...point,
      change,
      changePct: previous.value > 0 ? change / previous.value * 100 : 0,
    };
  });
  const first = points[0];
  const current = points[points.length - 1];
  const high = points.reduce((best, point) => point.value > best.value ? point : best, first);
  const low = points.reduce((best, point) => point.value < best.value ? point : best, first);
  const totalChange = current.value - first.value;
  const percentages = changes.map((change) => change.changePct);
  const percentageMean = mean(percentages);
  const volatilityPct = percentages.length
    ? Math.sqrt(mean(percentages.map((value) => (value - percentageMean) ** 2)))
    : 0;

  let longestUpStreak = 0;
  let longestDownStreak = 0;
  let upStreak = 0;
  let downStreak = 0;
  for (const change of changes) {
    if (change.change > 0) {
      upStreak += 1;
      downStreak = 0;
    } else if (change.change < 0) {
      downStreak += 1;
      upStreak = 0;
    } else {
      upStreak = 0;
      downStreak = 0;
    }
    longestUpStreak = Math.max(longestUpStreak, upStreak);
    longestDownStreak = Math.max(longestDownStreak, downStreak);
  }

  const lastDirection = changes.length ? changes[changes.length - 1].change : 0;
  let currentStreakCount = 0;
  if (lastDirection !== 0) {
    for (let index = changes.length - 1; index >= 0; index -= 1) {
      if (Math.sign(changes[index].change) !== Math.sign(lastDirection)) break;
      currentStreakCount += 1;
    }
  }

  return {
    points,
    changes,
    totalChange,
    totalChangePct: first.value > 0 ? totalChange / first.value * 100 : 0,
    high,
    low,
    averageValue: mean(points.map((point) => point.value)),
    averageChange: mean(changes.map((change) => change.change)),
    upDays: changes.filter((change) => change.change > 0).length,
    downDays: changes.filter((change) => change.change < 0).length,
    currentStreak: {
      direction: lastDirection > 0 ? "up" : lastDirection < 0 ? "down" : "flat",
      count: currentStreakCount,
    },
    longestUpStreak,
    longestDownStreak,
    bestDay: changes.length ? changes.reduce((best, change) => change.change > best.change ? change : best) : null,
    worstDay: changes.length ? changes.reduce((worst, change) => change.change < worst.change ? change : worst) : null,
    volatilityPct,
    distanceFromHighPct: high.value > 0 ? (current.value - high.value) / high.value * 100 : 0,
  };
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}
